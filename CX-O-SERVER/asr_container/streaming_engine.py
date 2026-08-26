"""ASR 容器流式引擎：fsmn-vad 分句 + paraformer 增量 ASR + cam++ 声纹 + 在线聚类。

架构说明
========
本模块是流式语音识别 + 说话人声纹判定的核心引擎，运行于 asr-sensevoice 容器内。

模型
----
三个彼此独立的 FunASR ``AutoModel`` 实例，严禁组合在单个 AutoModel 里带 vad/punc
（实测组合在流式 generate 报 ``unsupported operand /: 'list' and 'int'``）：

- ASR（增量识别）: ``paraformer-zh-streaming``（别名解析到 iic paraformer-large-online，已缓存）
- VAD（语音端点/分句）: ``fsmn-vad``
- SPK（说话人声纹）: ``iic/speech_campplus_sv_zh-cn_16k-common``（zh_en 版 modelscope 404，勿用）

模型为模块级懒加载单例，加载失败降级置 None（不崩溃，仅日志告警）。

线程模型
--------
- 模块级 ``_EXECUTOR``（``ThreadPoolExecutor(max_workers=2)``）：推理类阻塞操作
  一律丢进线程池，通过 ``asyncio`` 的 ``run_in_executor`` 编排，避免阻塞事件循环。
- 每个 WS 连接对应一个 ``StreamSession``（独立累积状态 + 独立 SpeakerSession 临时簇）。
- VAD 检出句子时，ASR(final) 与 SPK 声纹提取两个任务并行提交、并行执行。

聚类
----
``SpeakerClusterer``（见同目录 speaker_cluster.py）持有服务端权威注册画像池，并为每个
哙面派发独立的 ``SpeakerSession`` 临时簇。句子 final 时用 cam++ embedding 经
``session.classify`` 判定说话人：命中注册画像 → registered=True；命中会话内临时簇 →
registered=False；都低于阈值则新建临时簇 spk_{n}。临时簇跨 utterance 保留（session 不重置）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

import numpy as np

from funasr import AutoModel

from asr_container.speaker_cluster import SpeakerClusterer

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 模型常量（已实测缓存，容器内勿改）
# --------------------------------------------------------------------------- #
ASR_MODEL = "paraformer-zh-streaming"
VAD_MODEL = "fsmn-vad"
SPK_MODEL = "iic/speech_campplus_sv_zh-cn_16k-common"

# 流式 ASR 增量参数（预研 gate v4 实测通过）
CHUNK_SIZE = [0, 10, 5]
ENCODER_LOOK_BACK = 4
DECODER_LOOK_BACK = 1

# 引擎行为阈值
SPK_SIM_DEFAULT = "0.65"


def _spk_inflight_max() -> int:
    """声纹 in-flight 后台任务上限：优先 config，其次 CXO_SPK_INFLIGHT_MAX，默认 2。

    与现状（SPK_INFLIGHT_MAX=2）一致；允许通过配置放大。配置读取失败（如独立
    asr 容器无 server 包）时回退默认，保证零侵入。
    """
    try:
        from server.config import get_config as _gc
        v = int(getattr(_gc().executor, "spk_inflight_max", 2) or 2)
        if v > 0:
            return v
    except Exception:  # noqa: BLE001 - 容器内无 server.config 时走 env/默认
        pass
    try:
        return max(1, int(os.getenv("CXO_SPK_INFLIGHT_MAX", "2")))
    except ValueError:
        return 2


# 会话级声纹后台任务 in-flight 上限：超过上限丢弃该句（保持 pending，由后续更新），绝不阻塞
SPK_INFLIGHT_MAX = _spk_inflight_max()

# 缓冲上限（样本数），病理兜底：超出整体清空重置
MAX_BUFFER = 960000
# VAD 检查间隔（样本）
VAD_INTERVAL = 4800
# 首次/增量 partial 触发阈值（样本）
# 2026-08-25 优化：4800→2400（每新增 ~0.15s 出一次 partial 候选项）。服务端
# on_partial_result 首帧需下一拍确认才下发 voice.partial，较密节拍可显著提前
# 真实 T2（实测 T2≈0.85s 中约一拍 0.3s 由确认节奏贡献）。
PARTIAL_MIN_SAMPLES = 2400
# 句内累计最小样本（样本），句内累计不足不产 partial
# 2026-08-25 优化：对齐 2026-08-18 文档口径（T2≈280~340ms 达标基线）。
# paraformer-zh-streaming 独立实例对 2400 样本块即可投机解码；投机 partial 提前到
# 0.15s，保证 T2 回到文档水平（旧 SenseVoice 引擎 0.5s 阈值即出 partial）。
SENTENCE_MIN_SAMPLES = 2400
# 投机 partial 阈值（样本）：短句一次性解码提前发 partial，驱动服务端 LLM Prefill
# （2026-08-25 新增：paraformer 流式增量在 <0.5s 短句上无文本，靠投机解码兜底）
SPEC_MIN_SAMPLES = 2400

# 声纹 profiles 权威文件路径（容器内 bind mount，只读消费）
PROFILES_PATH = "/app/data/voiceprint/speaker_profiles.json"

# --------------------------------------------------------------------------- #
# 模块级全局单例（懒加载 + 线程安全）
# --------------------------------------------------------------------------- #
_ASR: Optional[AutoModel] = None
_VAD: Optional[AutoModel] = None
_SPK: Optional[AutoModel] = None
_load_lock = threading.Lock()
_loaded = False

def _engine_workers() -> int:
    """流式引擎共享线程池大小（ASR 推理 + 声纹共用）：优先 config，其次
    CXO_SPK_ENGINE_WORKERS，默认 4。与现状（max_workers=4）一致；允许配置放大。

    配置读取失败（如独立 asr 容器无 server 包）时回退 env/默认，保证零侵入。
    """
    try:
        from server.config import get_config as _gc
        w = int(getattr(_gc().executor, "spk_engine_workers", 4) or 4)
        if w > 0:
            return w
    except Exception:  # noqa: BLE001 - 容器内无 server.config 时走 env/默认
        pass
    try:
        return max(1, int(os.getenv("CXO_SPK_ENGINE_WORKERS", "4")))
    except ValueError:
        return 4


# 2026-08-25 优化：2→4 workers，避免投机 partial / 增量 / VAD / 声纹任务在单批
# 并发（多连接）下排队拉高 ASR partial 时延（对齐文档 T2≈280~340ms 达标基线）
_EXECUTOR = ThreadPoolExecutor(max_workers=_engine_workers(), thread_name_prefix="asr-engine")

# 在线说话人聚类器（阈值从环境变量读，缺省 0.65）
clusterer = SpeakerClusterer(
    threshold=float(os.getenv("SPK_SIM_THRESHOLD", SPK_SIM_DEFAULT))
)


class _EngineUnavailable(Exception):
    """引擎降级占位异常（模型均不可用时内部标记用，不需要向外部抛出）。"""


def _load_models() -> None:
    """懒加载三个模型实例（线程安全，幂等）。加载失败置 None 降级，不抛出。"""
    global _ASR, _VAD, _SPK, _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return

        _loaded = True  # 置位防止其余线程重复加载

        if _ASR is None:
            try:
                _ASR = AutoModel(model=ASR_MODEL, device="cpu", disable_update=True)
                logger.info(f"[ENGINE] ASR 模型加载成功: {ASR_MODEL}")
            except Exception as e:  # noqa: BLE001
                _ASR = None
                logger.error(f"[ENGINE] ASR 模型加载失败，已降级禁用: {e}")

        if _VAD is None:
            try:
                _VAD = AutoModel(model=VAD_MODEL, device="cpu", disable_update=True)
                logger.info(f"[ENGINE] VAD 模型加载成功: {VAD_MODEL}")
            except Exception as e:  # noqa: BLE001
                _VAD = None
                logger.error(f"[ENGINE] VAD 模型加载失败，已降级禁用: {e}")

        if _SPK is None:
            try:
                _SPK = AutoModel(model=SPK_MODEL, device="cpu", disable_update=True)
                logger.info(f"[ENGINE] SPK 模型加载成功: {SPK_MODEL}")
            except Exception as e:  # noqa: BLE001
                _SPK = None
                logger.error(f"[ENGINE] SPK 模型加载失败，已降级禁用: {e}")


# --------------------------------------------------------------------------- #
# 对外状态查询与工具函数
# --------------------------------------------------------------------------- #
def asr_loaded() -> bool:
    """ASR 模型是否可用（流式识别的硬依赖）。"""
    _load_models()
    return _ASR is not None


def spk_loaded() -> bool:
    """声纹模型是否可用。"""
    _load_models()
    return _SPK is not None


def extract_embedding(audio_float: np.ndarray) -> Optional[np.ndarray]:
    """用 cam++ 提取 192 维说话人 embedding（L2 归一化后返回一维向量）。

    模型未加载时返回 None。
    """
    _load_models()
    if _SPK is None:
        return None
    try:
        res = _SPK.generate(input=audio_float)
        if not (res and isinstance(res[0], dict)):
            return None
        e = np.asarray(res[0].get("spk_embedding"), dtype=np.float32)
        if e.ndim == 2:
            e = e[0]
        e = e.reshape(-1)
        norm = float(np.linalg.norm(e))
        if norm > 0:
            e = e / norm
        return e
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ENGINE] 声纹提取失败: {e}")
        return None


def profile_count() -> int:
    """当前注册说话人画像数量。"""
    return clusterer.profile_count()


def profile_names() -> List[str]:
    """当前注册说话人名称列表。"""
    return clusterer.profile_names()


def status_dict() -> dict:
    """引擎状态快照（供 /api/v1/voiceprint/status）。"""
    _load_models()
    return {
        "status": "ok" if _SPK is not None else "error",
        "spk_model": SPK_MODEL,
        "profiles_count": clusterer.profile_count(),
        "threshold": float(clusterer.threshold),
        "profile_names": clusterer.profile_names(),
    }


def load_profiles() -> int:
    """从权威文件重载声纹画像。

    读取 ``{version, profiles:[{name, embeddings}]}``，全量替换 clusterer 注册池。
    文件缺失/解析失败 → 空池。返回当前注册 profiles 数量。
    """
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ENGINE] 读取 profiles 文件失败（按空池处理）: {e}")
        return 0

    profiles = data.get("profiles", []) if isinstance(data, dict) else []
    n = clusterer.upsert_profiles(profiles)
    logger.info(f"[ENGINE] 声纹 profiles 已加载: {n} 个注册说话人")
    return n


# --------------------------------------------------------------------------- #
# 独立推理运行器（在线程池执行，供 Session/REST 复用）
# --------------------------------------------------------------------------- #
def _run_asr_final(audio_slice: np.ndarray) -> str:
    """整句一次性 ASR 解码（cache={} + is_final=True）。返回文本，可为空串。"""
    if _ASR is None:
        return ""
    try:
        res = _ASR.generate(
            input=audio_slice, cache={}, is_final=True,
            chunk_size=CHUNK_SIZE,
            encoder_chunk_look_back=ENCODER_LOOK_BACK,
            decoder_chunk_look_back=DECODER_LOOK_BACK,
        )
        return str(res[0].get("text", "") or "") if res and isinstance(res[0], dict) else ""
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ENGINE] ASR final 失败: {e}")
        return ""


def _run_asr_partial(audio_slice: np.ndarray, asr_cache: dict) -> str:
    """增量 ASR 解码（带 cache，is_final=False）。返回文本，可为空串（噪声无幻觉）。"""
    if _ASR is None:
        return ""
    try:
        res = _ASR.generate(
            input=audio_slice, cache=asr_cache, is_final=False,
            chunk_size=CHUNK_SIZE,
            encoder_chunk_look_back=ENCODER_LOOK_BACK,
            decoder_chunk_look_back=DECODER_LOOK_BACK,
        )
        return str(res[0].get("text", "") or "") if res and isinstance(res[0], dict) else ""
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ENGINE] ASR partial 失败: {e}")
        return ""


def _run_vad(audio: np.ndarray, is_final: bool, vad_cache: dict) -> List[List[int]]:
    """fsmn-vad 流式分句。返回 segment 列表 [[beg, end], ...]（16k 采样索引）。"""
    if _VAD is None:
        return []
    try:
        res = _VAD.generate(input=audio, is_final=is_final, cache=vad_cache)
        if res and isinstance(res[0], dict):
            return res[0].get("value", []) or []
        return []
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ENGINE] VAD 失败: {e}")
        return []


def _run_spk_embedding(audio_slice: np.ndarray) -> Optional[np.ndarray]:
    """cam++ 声纹提取（L2 归一化一维向量）；模型不可用或失败返回 None。"""
    return extract_embedding(audio_slice)


# --------------------------------------------------------------------------- #
# StreamSession：每条 WS 连接一个，持有独立累积状态与说话人临时簇
# --------------------------------------------------------------------------- #
class StreamSession:
    """单条 WS 连接的流式识别会话。

    - 累积 float32 音频、维护当前句起点、ASR 增量 cache、VAD cache。
    - ``feed_pcm`` 触发 VAD 分句（句子 final：ASR + SPK 并行）+ 增量 partial。
    - ``finish`` 对剩余尾段做整句 final 识别（含说话人判定）。
    - 说话人临时簇（SpeakerSession）跨 utterance 保留，不随 sentence 重置。
    """

    def __init__(self) -> None:
        _load_models()
        self._audio = np.empty(0, dtype=np.float32)   # 累积音频（当前 utterance）
        self._cur_start = 0                           # 当前句起点样本索引
        self._asr_cache: dict = {}                    # 当前句增量 ASR cache
        self._vad_cache: dict = {}                    # VAD 流式 cache
        self._last_vad_t = 0                          # 距上次 VAD 检查累计样本
        self._last_asr_t = 0                          # 距上次 partial 累计样本
        self._spec_sent = False                       # 当前句是否已发过投机 partial
        self.session = clusterer.create_session()     # 说话人临时簇（跨 utterance 保留）
        self._speaker: Optional[Tuple[str, bool, float]] = None  # 最近发言判定缓存
        self._spk_pending_count = 0        # 会话内 in-flight 声纹任务数
        self._pending_spk_msgs: List[dict] = []  # 待下发的 spk 补充消息
        self._classify_lock = asyncio.Lock()     # classify 并发互斥

    # ------------------------------------------------------------------ #
    # 消息构造
    # ------------------------------------------------------------------ #
    @staticmethod
    def _partial_msg(text: str) -> dict:
        return {
            "text": text,
            "is_final": False,
            "language": "",
            "emotion": "",
            "speaker_id": "",
            "speaker_registered": False,
            "speaker_conf": 0.0,
        }

    def _final_msg(self, text: str, status: str, spk_id: str = "", registered: bool = False, conf: float = 0.0) -> dict:
        """status: "pending"（声纹计算中，前端显示"识别中"）| "ready"（本句声纹已就绪）。
        仅 status=="ready" 且 spk_id 非空时才更新 self._speaker（最近已知）。"""
        if status == "ready" and spk_id:
            self._speaker = (spk_id, bool(registered), float(conf))
        return {
            "text": text, "is_final": True, "language": "", "emotion": "",
            "speaker_status": status,
            "speaker_id": spk_id, "speaker_registered": bool(registered),
            "speaker_conf": float(conf),
        }

    # ------------------------------------------------------------------ #
    # 缓冲重置
    # ------------------------------------------------------------------ #
    def _reset_buffer(self, pathological: bool = False) -> None:
        """整体清空 utterance 缓冲并复位句/缓存状态（保留说话人临时簇）。"""
        if pathological:
            logger.warning(
                f"[SESSION] 缓冲超限（>{MAX_BUFFER} 样本），整体清空重置（病理兜底）"
            )
        self._audio = np.empty(0, dtype=np.float32)
        self._cur_start = 0
        self._asr_cache = {}
        self._vad_cache = {}
        self._last_vad_t = 0
        self._last_asr_t = 0
        self._spec_sent = False  # 当前句是否已发过投机 partial（短句兜底触发）

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    async def feed_pcm(self, pcm_int16_bytes: bytes) -> List[dict]:
        """喂入 int16 PCM 字节，执行 VAD 检查与 ASR partial 检查，返回消息列表（可空）。"""
        chunk = np.frombuffer(pcm_int16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        n = int(chunk.size)
        if n <= 0:
            return []

        # 病理兜底：缓冲超限整体清空重置
        if len(self._audio) + n > MAX_BUFFER:
            self._reset_buffer(pathological=True)
        self._audio = np.append(self._audio, chunk)
        self._last_vad_t += n
        # 全量转发下（服务端不再做 VAD 门控）纯数字静音帧仍喂 VAD，但不计入 ASR
        # partial 步进锚点，避免静默空转解码烧 CPU（语音帧 RMS 通常 >> 1e-4）。
        if float(np.abs(chunk).mean()) >= 1e-4:
            self._last_asr_t += n

        msgs: List[dict] = []

        # -- VAD 检查（间隔 VAD_INTERVAL）→ 产出句子 final -- #
        if self._last_vad_t >= VAD_INTERVAL and _VAD is not None:
            self._last_vad_t = 0
            seg_msgs = await self._vad_sweep()
            msgs.extend(seg_msgs)

        # -- ASR partial 检查（新增样本 + 句内累计双阈值）
        # 2026-08-25：阈值降为 SPEC_MIN_SAMPLES(2400=0.15s) —— 增量无文本时
        # _maybe_partial 内的投机单次解码提前出 partial，驱动服务端 LLM Prefill，
        # 恢复 2026-08-18 文档口径的 T2≈280~340ms 达标基线。-- #
        if _ASR is not None and self._last_asr_t >= SPEC_MIN_SAMPLES:
            sentence_len = len(self._audio) - self._cur_start
            if sentence_len >= SPEC_MIN_SAMPLES:
                await self._maybe_partial(msgs)

        return msgs

    async def _vad_sweep(self) -> List[dict]:
        """VAD 分句并产出句子 final 消息。多句并行提交 ASR(final) 与 SPK。"""
        loop = asyncio.get_running_loop()
        segments = await loop.run_in_executor(
            _EXECUTOR, _run_vad, self._audio, False, self._vad_cache
        )

        # 只处理「结束索引不越界 且 起点在当前句起点之后」的完整新句子
        cur = self._cur_start
        new_sentences = [
            seg for seg in segments
            if len(seg) >= 2 and seg[1] <= len(self._audio) and seg[0] >= cur
        ]
        if not new_sentences:
            return []

        msgs: List[dict] = []
        for start, end in new_sentences:
            audio_slice = self._audio[start:end]
            asr_fut = loop.run_in_executor(_EXECUTOR, _run_asr_final, audio_slice)
            spk_fut = loop.run_in_executor(_EXECUTOR, _run_spk_embedding, audio_slice)
            text = await asr_fut                     # 唯一阻塞点
            if spk_fut.done():
                emb = spk_fut.result()               # 不阻塞：已完成直接取
                if emb is not None:
                    async with self._classify_lock:
                        spk_id, registered, conf = self.session.classify(emb)
                    msgs.append(self._final_msg(text, "ready", spk_id, registered, conf))
                else:
                    msgs.append(self._final_msg(text, "ready"))   # 声纹模型不可用
            else:
                msgs.append(self._final_msg(text, "pending"))     # "识别中"，后补
                self._track_spk_pump(spk_fut, audio_slice)

        # 推进当前句起点到最后一句结束处，重置 ASR 增量状态
        self._cur_start = new_sentences[-1][1]
        self._asr_cache = {}
        self._last_asr_t = 0
        self._spec_sent = False
        return msgs

    def _track_spk_pump(self, spk_fut, audio_slice: np.ndarray) -> None:
        """登记声纹后台任务（in-flight 上限控制）；超限丢弃该句，保持 pending。"""
        if self._spk_pending_count >= SPK_INFLIGHT_MAX:
            # E3: 被丢弃的 future 仍占用 _EXECUTOR 线程并可能产生未取回的异常
            # （"Future exception was never retrieved"）。尽力取消，并挂 done
            # 回调消费结果/异常，避免告警日志噪音。
            if not spk_fut.done():
                spk_fut.cancel()
                spk_fut.add_done_callback(
                    lambda f: None if f.cancelled() else f.exception()
                )
            return
        self._spk_pending_count += 1
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._spk_pump(spk_fut, audio_slice))
        task.add_done_callback(self._on_spk_pump_done)

    def _on_spk_pump_done(self, task: asyncio.Task) -> None:
        self._spk_pending_count -= 1
        try:
            task.result()      # 吞掉异常，不外抛
        except Exception:
            pass

    async def _spk_pump(self, spk_fut, audio_slice: np.ndarray) -> None:
        """后台完成声纹判定：classify → 更新最近已知 → push spk 补充消息。"""
        try:
            emb = await spk_fut
        except Exception:
            emb = None
        if emb is None:
            return
        try:
            async with self._classify_lock:
                spk_id, registered, conf = self.session.classify(emb)
            self._speaker = (spk_id, bool(registered), float(conf))
        except Exception:
            return
        match = self.session.recent_match()
        # 显式判空后再访问（条件表达式易误读为 None 时仍取 match[1] 的语义）
        em_embedding = []
        if match:
            em_embedding = [float(x) for x in match[1]]
        self._pending_spk_msgs.append({
            "type": "spk",
            "speaker_status": "ready",
            "speaker_id": spk_id,
            "speaker_registered": bool(registered),
            "speaker_conf": float(conf),
            "em_embedding": em_embedding,
        })

    def drain_spk_messages(self) -> List[dict]:
        """取走并清空待发 spk 补充消息（供 WS 发送侧调用）。"""
        msgs = self._pending_spk_msgs
        self._pending_spk_msgs = []
        return msgs

    async def _maybe_partial(self, msgs: List[dict]) -> None:
        """增量 partial：对 [_cur_start:] 增量解码，文本非空才产出 partial 消息。

        短句兜底：增量路径无文本且本句尚未发过投机 partial 时，对当前缓冲做
        一次性整句解码（_run_asr_final）作为投机 partial 早发，防止
        双流式服务端无 partial 输入而饿死（修复 2026-08-25）。
        """
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            _EXECUTOR, _run_asr_partial, self._audio[self._cur_start:], self._asr_cache
        )
        if not text and not self._spec_sent:
            spec = await loop.run_in_executor(
                _EXECUTOR, _run_asr_final, self._audio[self._cur_start:]
            )
            if spec:
                text = spec
                self._spec_sent = True
        self._last_asr_t = 0  # 无论是否有文本，都复位步进锚点
        if text:
            msgs.append(self._partial_msg(text))

    async def finish(self, full_audio_slice: Optional[np.ndarray] = None) -> List[dict]:
        """客户端发 final 时：对当前句剩余尾段做整句 final 识别 + 说话人判定，随后重置。

        ``full_audio_slice`` 若传入则用它作为识别切片（否则用自 [_cur_start:] 的尾段）。
        """
        _load_models()
        tail = (
            full_audio_slice
            if full_audio_slice is not None
            else self._audio[self._cur_start:]
        )
        tail = np.asarray(tail, dtype=np.float32)

        loop = asyncio.get_running_loop()
        text_fut = loop.run_in_executor(_EXECUTOR, _run_asr_final, tail)
        emb_fut = loop.run_in_executor(_EXECUTOR, _run_spk_embedding, tail)
        text = await text_fut
        # 只 await 文本；声纹就绪则快速路径带 ready，否则 pending 后补
        if emb_fut.done():
            emb = emb_fut.result()
            if emb is not None:
                async with self._classify_lock:
                    spk_id, registered, conf = self.session.classify(emb)
                msg = self._final_msg(text, "ready", spk_id, registered, conf)
            else:
                msg = self._final_msg(text, "ready")   # 声纹模型不可用
        else:
            msg = self._final_msg(text, "pending")     # "识别中"，后补
            self._track_spk_pump(emb_fut, tail)

        # 重置 utterance 缓冲与缓存（说话人临时簇 session 保留跨 utterance）
        self._reset_buffer(pathological=False)
        return [msg]


# 导入时先加载 profiles（服务端后续更新经由 /profiles/sync 重载）
load_profiles()