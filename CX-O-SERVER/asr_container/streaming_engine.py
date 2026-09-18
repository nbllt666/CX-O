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
import re
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
# 整句 final 解码模型：SenseVoiceSmall 离线识别（比 paraformer 在线整句解码快 ~4x，
# 实测 9.44s 音频 581ms vs 2249ms）。仅用于句尾 final；partial 仍用 paraformer 流式
# （SenseVoice 流式实测跨语言串字、精度不可用，2026-09-18 实测结论）。
SV_MODEL = "iic/SenseVoiceSmall"

# 流式 ASR 增量参数（预研 gate v4 实测通过）
CHUNK_SIZE = [0, 10, 5]
ENCODER_LOOK_BACK = 4
DECODER_LOOK_BACK = 1
# 流式契约：每次 generate 必须喂「对齐块」= chunk_size[1] * 960 = 9600 样本（600ms），
# 返回值是该块的**增量文本**，调用方需自行累积。喂非对齐长度会得到碎片文本。
ASR_CHUNK_STRIDE = CHUNK_SIZE[1] * 960

# SenseVoice 富标签（<|zh|><|HAPPY|><|Speech|><|woitn|> 等）剥离正则
_SV_TAG_RE = re.compile(r"<\|[^|]*\|>")

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
# 16kHz 采样下 ms → 样本的换算系数（VAD 返回的 segment 单位是**毫秒**）
MS_TO_SAMPLES = 16
# VAD 流式块长（ms）。funasr 以 `chunk_size >= 15000` 判定「非流式」，故必须显式给
# 小值才能进流式模式（默认 60000=60s 会导致 60s 内根本不处理音频）。
VAD_CHUNK_MS = 200
# VAD 检查间隔（样本）。对齐 VAD_CHUNK_MS（200ms=3200 样本）：每次恰好喂一个 VAD
# 流式块，模型内部无残留缓冲，句尾检出时机更贴近真实静音起点。
VAD_INTERVAL = VAD_CHUNK_MS * MS_TO_SAMPLES
# 句尾静音阈值（ms）。容器内 funasr 为改版实现：dynamic silence schedule 会把该阈值
# 覆盖为「语音累计 <10s → 1850ms」，除非显式传 max_end_silence_time 或
# dynamic_silence=False（见 fsmn_vad_streaming/model.py inference）。两参数都必须显式传。
VAD_END_SILENCE_MS = 400
# 句首回退（样本，600ms）：VAD 上报的起始点晚于真实人声起点（实测约 0.5s），
# 严格按上报点切片会吞掉句首音节；回退后与上一句尾取 max，不会引入长静音。
VAD_SEG_START_PAD = 9600
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
# 2026-09-18：2400→1600（0.15s→0.10s）。服务端 on_partial_result 对音频起始边缘的
# 首个 partial 会「暂存等下一帧延续」才下发 voice.partial（防 SenseVoice 边缘幻觉），
# 故首包时刻 ≈ 首个有效 partial 时刻 + 一个节拍。
# ⚠️ 勿再下调（实测反例 2026-09-18）：降到 800（50ms）后容器两个 partial 的间隔**不变**
# （仍 ~130ms），服务端首推反而从 377ms 退到 402~455ms——间隔由投机解码耗时（CPU 上
# paraformer 整句解码 ~120ms，与 _ASR_LOCK 串行）决定，加密节拍只是徒增解码次数与锁争用。
SPEC_MIN_SAMPLES = 1600
# 投机解码的音频长度上限（样本，3s）：投机解码是「整句全量解码」，只在句首短音频上
# 廉价；句内累计超过该长度仍无文本（多为噪声/静音）时不再反复全量解码——否则长噪声
# 段会按揭触发昂贵重解码（旧实现隐患，2026-09-18 修复一并加上界）。
SPEC_MAX_SAMPLES = 48000
# 投机解码重试步长（样本，100ms）：句长每增长该值就重试一次整句投机解码，**持续刷新**
# partial 直到增量对齐块产出文本为止。实测（2026-09-18，EvalKit 9.44s 资产）paraformer
# 整句解码在 0.15s 音频处即输出正确的「你好」，而首个对齐块要到 0.6s 才有 '你'：
# 旧逻辑「出文本即停止投机」会让服务端在 0.15s 拿到候选后、必须干等到 0.6s 才有第二个
# 样本可供「延续性确认」，实测 voice.partial 首包因此落在 722ms。持续刷新后 0.25s 即可
# 提供延续样本，首包提前约 300ms。开销有上界：一旦对齐块产出文本（`_asr_text` 非空）
# 立即停止，故每句投机次数 ≈ 0.6s/0.1s = 6 次。
SPEC_RETRY_STEP = 1600

# 声纹 profiles 权威文件路径（容器内 bind mount，只读消费）
PROFILES_PATH = "/app/data/voiceprint/speaker_profiles.json"

# 推理设备：默认 cpu。2026-09-18 按人类裁决"试挂 GPU1"验证过 GPU 加速，**实测无收益**
# 并已回退（docker-compose.yml 的 asr-sensevoice 恢复不申请 GPU 设备）：
#   - 150ms 音频投机解码 GPU 125ms / CPU 173ms（首次含预热，看似略快）
#   - 600ms 音频 GPU 249ms / CPU 255ms（无优势）；SenseVoice 300ms GPU 170ms / CPU 158ms（更慢）
#   - 决定性证据：**10ms 音频在 GPU 上仍耗时 116ms** —— 投机解码 ~120ms 中约 116ms 是
#     funasr `AutoModel.generate` 的固定开销（cache 初始化/特征提取/结果后处理，与音频
#     长度无关），非算力瓶颈；GPU 只会额外引入主机-设备传输开销。
# 保留本常量（而非回写 4 处字面量）是为了让设备选择显式可配：换更大模型或换机器时可
# 用 ASR_DEVICE=cuda 覆盖，无需改代码。
DEVICE = os.getenv("ASR_DEVICE", "cpu").strip() or "cpu"

# --------------------------------------------------------------------------- #
# 模块级全局单例（懒加载 + 线程安全）
# --------------------------------------------------------------------------- #
_ASR: Optional[AutoModel] = None
_VAD: Optional[AutoModel] = None
_SPK: Optional[AutoModel] = None
_SV: Optional[AutoModel] = None
# 三模型懒加载互斥锁：防止并发调用 _load_models 重复加载（首次 WS 连接触发的
# 加载耗时数十秒，多连接同时首连会并发进入）。加载本身保持同步，由调用方放入
# to_thread / run_in_executor 执行，不阻塞事件循环。
_MODELS_LOAD_LOCK = threading.Lock()
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

# M10（第五轮）: 三个 AutoModel 为模块级共享单例，但 _EXECUTOR 线程池由
# 多会话/多句并发提交推理任务。funasr AutoModel 内部持有 generate 相关可变状态，
# 并发调用可能产生结果错乱。按模型分别串行化推理（推理是 GPU/CPU 密集串行操作，
# 锁不引入吞吐损失，只消除并发交错）。
_ASR_LOCK = threading.Lock()
_VAD_LOCK = threading.Lock()
_SPK_LOCK = threading.Lock()
_SV_LOCK = threading.Lock()


class _EngineUnavailable(Exception):
    """引擎降级占位异常（模型均不可用时内部标记用，不需要向外部抛出）。"""


def _load_models() -> None:
    """懒加载三个模型实例（线程安全，幂等）。加载失败置 None 降级，不抛出。

    持模块级 ``_MODELS_LOAD_LOCK`` 双重检查：首个进入者执行同步加载（调用方应
    将本函数置于 to_thread / run_in_executor，避免阻塞事件循环），其余线程在锁上
    等待或经 ``_loaded`` 快速返回。
    """
    global _ASR, _VAD, _SPK, _SV, _loaded
    if _loaded:
        return
    with _MODELS_LOAD_LOCK:
        if _loaded:
            return

        _loaded = True  # 置位防止其余线程重复加载

        if _ASR is None:
            try:
                _ASR = AutoModel(model=ASR_MODEL, device=DEVICE, disable_update=True)
                logger.info(f"[ENGINE] ASR 模型加载成功: {ASR_MODEL}")
            except Exception as e:  # noqa: BLE001
                _ASR = None
                logger.error(f"[ENGINE] ASR 模型加载失败，已降级禁用: {e}")

        if _VAD is None:
            try:
                _VAD = AutoModel(model=VAD_MODEL, device=DEVICE, disable_update=True)
                # 句尾静音窗 800ms(funasr 默认) → 400ms：实测说完→出声延迟中分句等待
                # 占大头（能量说完→首包 995ms，其中分句等待 ~800ms）。400ms 仍足以
                # 区分自然停顿与换气，配合服务端 VAD 150ms 兜底（双流式仅作修正）。
                # funasr fsmn-vad 把该值放在内层 model.max_end_silence_time 与
                # model.vad_opts.max_end_silence_time（无 .config），两处都显式覆盖。
                _patched = 0
                for holder in (
                    getattr(_VAD.model, "vad_opts", None),
                    _VAD.model,
                ):
                    if holder is not None and hasattr(holder, "max_end_silence_time"):
                        holder.max_end_silence_time = 400
                        _patched += 1
                logger.info(
                    f"[ENGINE] VAD max_end_silence_time=400ms 已覆盖 {(_patched)} 处"
                    f"（当前值: model={getattr(_VAD.model, 'max_end_silence_time', 'n/a')} "
                    f"vad_opts={getattr(getattr(_VAD.model, 'vad_opts', None), 'max_end_silence_time', 'n/a')}）"
                )
                logger.info(f"[ENGINE] VAD 模型加载成功: {VAD_MODEL}")
            except Exception as e:  # noqa: BLE001
                _VAD = None
                logger.error(f"[ENGINE] VAD 模型加载失败，已降级禁用: {e}")

        if _SPK is None:
            try:
                _SPK = AutoModel(model=SPK_MODEL, device=DEVICE, disable_update=True)
                logger.info(f"[ENGINE] SPK 模型加载成功: {SPK_MODEL}")
            except Exception as e:  # noqa: BLE001
                _SPK = None
                logger.error(f"[ENGINE] SPK 模型加载失败，已降级禁用: {e}")

        if _SV is None:
            try:
                _SV = AutoModel(model=SV_MODEL, device=DEVICE, disable_update=True)
                logger.info(f"[ENGINE] SenseVoice(final) 模型加载成功: {SV_MODEL}")
            except Exception as e:  # noqa: BLE001
                _SV = None
                # 降级语义：final 路径自动回退 paraformer 在线整句解码（_run_asr_final_sv）
                logger.warning(f"[ENGINE] SenseVoice(final) 加载失败，final 回退 paraformer: {e}")


def preload_streaming_models() -> None:
    """启动期预载入口：供 api_server startup 经 asyncio.to_thread 调用。

    背景：三个 FunASR AutoModel 串行同步加载数十秒，若由首次 WS 连接触发懒加载
    会阻塞容器事件循环。预载把该开销移到服务启动期（startup 在 to_thread 中执行，
    不阻塞事件循环）。内部经 _load_models 持 _MODELS_LOAD_LOCK 幂等执行——启动后
    首次 WS 连接的懒加载调用变为零开销快速返回；加载失败仍按降级语义置 None，
    不抛出。
    """
    _load_models()


# --------------------------------------------------------------------------- #
# 对外状态查询与工具函数
# --------------------------------------------------------------------------- #
# 懒加载触发说明（状态查询路径，行为影响最小方案）：asr_loaded/spk_loaded/
# status_dict/extract_embedding/StreamSession.__init__ 中的同步 _load_models()
# 调用保持不变——api_server startup 已预载（经 to_thread），此后这些调用均为
# _loaded=True 的零开销快速返回（无锁直返）；预载完成前 FastAPI 尚未开始接收
# 连接，故不存在事件循环阻塞窗口。仅 finish()（可能在预载完成前被首连触发）改为
# 经 to_thread 触发加载。
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
        with _SPK_LOCK:  # M10: 共享单例串行推理
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
        with _ASR_LOCK:  # M10: 共享单例串行推理
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


def _run_asr_final_sv(audio_slice: np.ndarray) -> str:
    """整句 final 解码：SenseVoiceSmall 离线识别（比 paraformer 在线整句解码快 ~4x）。

    实测（2026-09-18，9.44s 音频）：SenseVoice 581ms vs paraformer 2249ms。返回剥离
    富标签（``<|zh|><|HAPPY|><|Speech|><|woitn|>``）后的纯文本。模型不可用或失败时
    回退 ``_run_asr_final``（paraformer 在线整句），保证 final 路径始终有结果。
    """
    if _SV is None:
        return _run_asr_final(audio_slice)
    try:
        with _SV_LOCK:  # 共享单例串行推理
            res = _SV.generate(input=audio_slice, is_final=True)
        raw = str(res[0].get("text", "") or "") if res and isinstance(res[0], dict) else ""
        return _SV_TAG_RE.sub("", raw).strip()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[ENGINE] SenseVoice final 失败，回退 paraformer: {e}")
        return _run_asr_final(audio_slice)


def _run_asr_partial(audio_slice: np.ndarray, asr_cache: dict) -> str:
    """增量 ASR 解码（带 cache，is_final=False）。返回该块的**增量文本**（可为空串）。

    契约：调用方每次必须喂恰好 ``ASR_CHUNK_STRIDE``（9600 样本/600ms）的对齐块，并把
    返回文本累积起来（返回值不是整句全文）。喂非对齐长度会得到碎片文本（实测）。
    """
    if _ASR is None:
        return ""
    try:
        with _ASR_LOCK:  # M10: 共享单例串行推理
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
    """fsmn-vad 流式分句。返回 segment 列表 ``[[beg_ms, end_ms], ...]``（**单位毫秒**）。

    调用契约（2026-09-18 容器内实测修正）：
    - 只喂**新增音频**（旧实现每次重喂整段累积缓冲，与流式 cache 叠加会重复解码同一段
      音频：内部时间轴被拉长、段落判定错乱，并伴随 O(n²) 开销）；
    - 必须显式传 ``chunk_size``（<15000 才进流式模式）与 ``max_end_silence_time``；
      不传后者时容器内改版 funasr 的 dynamic silence schedule 会把句尾静音阈值拉到
      1850ms（语音累计 <10s 档），句尾 final 会晚到 ~2s；
    - 返回索引是毫秒（与 funasr 官方 ``slice_padding_audio_samples`` 口径一致，
      官方按 ``int(seg[0] * 16)`` 换算样本），调用方需自行 ×16 换算；
    - 起始点与结束点是**两个事件**：``[beg, -1]``（检出人声起点）/ ``[-1, end]``
      （检出句尾），调用方需配对累积。
    """
    if _VAD is None:
        return []
    try:
        with _VAD_LOCK:  # M10: 共享单例串行推理
            res = _VAD.generate(
                input=audio, is_final=is_final, cache=vad_cache,
                chunk_size=VAD_CHUNK_MS,
                max_end_silence_time=VAD_END_SILENCE_MS,
                dynamic_silence=False,
            )
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
# 音频缓冲：摊还 O(1) 追加（L 级修复：替代逐帧 np.append 的 O(n²) 全量拷贝）
# --------------------------------------------------------------------------- #
class _GrowableAudioBuffer:
    """可增长 float32 音频缓冲。

    此前 ``feed_pcm`` 每帧执行 ``np.append(self._audio, chunk)``——每次都整段
    拷贝重建数组，随缓冲增长呈 O(n²)。改为「倍增容量的后备数组 + 已写长度」：
    - ``append`` 摊还 O(1)，仅在容量不足时搬运一次；
    - ``view()`` 返回 ``[0:_size]`` 的 ndarray 视图，对 VAD/ASR 喂入与
      ``len()/切片/索引`` 等既有消费点语义与连续 ndarray 完全一致；
    - 已写入区间永不回写覆盖（只在尾部追加；扩容时旧块整块拷贝后仍由旧视图持有），
      在途切片（如声纹后台任务的 audio_slice）数据不变性等同旧的按次拷贝行为。
    """

    __slots__ = ("_data", "_size")

    def __init__(self) -> None:
        self._data = np.empty(0, dtype=np.float32)
        self._size = 0

    def reset(self) -> None:
        """清空缓冲（丢弃后备数组，下次追加重新起步）。"""
        self._data = np.empty(0, dtype=np.float32)
        self._size = 0

    def append(self, chunk: np.ndarray) -> None:
        """追加一段样本（一维 float32/可转换数组），摊还 O(1)。"""
        n = int(chunk.size)
        need = self._size + n
        if need > self._data.shape[0]:
            cap = max(need, self._data.shape[0] * 2, 4096)
            new_data = np.empty(cap, dtype=np.float32)
            new_data[: self._size] = self._data[: self._size]
            self._data = new_data
        self._data[self._size : need] = chunk
        self._size = need

    def view(self) -> np.ndarray:
        """返回已写入区间的 ndarray 视图（[0:_size]，消费方按只读对待）。"""
        return self._data[: self._size]

    def __len__(self) -> int:
        return self._size


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
        self._buf = _GrowableAudioBuffer()            # 增长式累积音频缓冲（O(1) 追加）
        self._cur_start = 0                           # 当前句起点样本索引
        self._asr_cache: dict = {}                    # 当前句增量 ASR cache
        # 流式 partial 契约状态（2026-09-18）：已喂给流式模型的对齐块数 + 累积增量文本。
        # 流式模型每次只吃一个对齐块（9600 样本）并返回该块增量文本，调用方累积，
        # 避免旧实现「整句重喂」的 O(n²) 全量重算（单轮 9.44s 音频曾累计 66.7s CPU）。
        self._asr_fed_chunks = 0
        self._asr_text = ""
        self._vad_cache: dict = {}                    # VAD 流式 cache
        self._vad_fed = 0                             # 已喂给 VAD 的样本数（增量游标）
        self._vad_seg_start_ms: Optional[int] = None   # 待配对的人声起点（ms，等句尾事件）
        self._last_vad_t = 0                          # 距上次 VAD 检查累计样本
        self._last_asr_t = 0                          # 距上次 partial 累计样本
        self._spec_last_len = 0                       # 上次投机解码时的句长（节流用）
        self._spec_text = ""                          # 最近一次投机解码的文本（单调增长保护）
        self._pending_trim = False                    # 上一句已闭合，待把句起点对齐到新句人声
        self.session = clusterer.create_session()     # 说话人临时簇（跨 utterance 保留）
        self._speaker: Optional[Tuple[str, bool, float]] = None  # 最近发言判定缓存
        self._spk_pending_count = 0        # 会话内 in-flight 声纹任务数
        self._pending_spk_msgs: List[dict] = []  # 待下发的 spk 补充消息
        self._classify_lock = asyncio.Lock()     # classify 并发互斥

    @property
    def _audio(self) -> np.ndarray:
        """已累积音频视图（兼容既有消费点：len/切片/整段喂 VAD）。"""
        return self._buf.view()

    @_audio.setter
    def _audio(self, value: np.ndarray) -> None:
        """整体替换缓冲内容（兼容旧调用点/测试直塞整段音频的场景）。"""
        self._buf.reset()
        arr = np.asarray(value, dtype=np.float32).reshape(-1)
        if arr.size:
            self._buf.append(arr)

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
        self._buf.reset()
        self._cur_start = 0
        self._asr_cache = {}
        self._asr_fed_chunks = 0
        self._asr_text = ""
        self._vad_cache = {}
        self._vad_fed = 0
        self._vad_seg_start_ms = None
        self._last_vad_t = 0
        self._last_asr_t = 0
        self._spec_last_len = 0
        self._spec_text = ""
        self._pending_trim = False

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
        self._buf.append(chunk)
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
        """VAD 分句并产出句子 final 消息。多句并行提交 ASR(final) 与 SPK。

        2026-09-18 修正（容器内实测）：
        - **增量喂**：只把 ``self._vad_fed`` 之后的新音频交给 VAD。旧实现每次重喂整段
          累积缓冲，与流式 cache 叠加会把同一段音频反复解码进内部时间轴，段落判定
          错乱（实测出现 15 段「句子洪水」），且开销随缓冲增长近似 O(n²)。
        - **毫秒换算**：VAD 返回的是毫秒（非采样索引），旧实现按采样索引切片，句尾
          final 切到错误音频（实测输出 ``'し'``/``'え'`` 等日语碎片）。
        - **事件配对**：``[beg, -1]`` 是人声起点事件、``[-1, end]`` 是句尾事件，两者
          分属不同次调用，须跨调用配对累积（``_vad_seg_start_ms``）。
        - **起点回退**：VAD 上报的起点晚于真实人声起点约 0.5s，按 ``VAD_SEG_START_PAD``
          回退，避免吞句首音节；与上一句尾取 max 防止重叠。
        """
        loop = asyncio.get_running_loop()
        new_audio = self._audio[self._vad_fed:]
        if len(new_audio) == 0:
            return []
        segments = await loop.run_in_executor(
            _EXECUTOR, _run_vad, new_audio, False, self._vad_cache
        )
        self._vad_fed = len(self._audio)

        # 配对起点/终点事件 → 完整句区间（毫秒）
        spans: List[Tuple[int, int]] = []
        for seg in segments:
            if not seg or len(seg) < 2:
                continue
            beg_ms, end_ms = int(seg[0]), int(seg[1])
            if beg_ms >= 0 and end_ms < 0:
                # 人声起点事件：仅记录用于句尾切片配对。**不**用它 rebase ASR 句起点——
                # 容器内实测 VAD 的毫秒时间轴比实际喂入音频超前 ~300-500ms，起点事件
                # 被推迟到句中才触发，rebase 会清空已累积的 ASR 增量状态（实测首 partial
                # 从 0.6s 退到 2.6s）。句起点改由 _align_sentence_start 按能量对齐。
                if self._vad_seg_start_ms is None:
                    self._vad_seg_start_ms = beg_ms
            elif end_ms >= 0:
                beg = self._vad_seg_start_ms if beg_ms < 0 else beg_ms
                if beg is not None:
                    spans.append((beg, end_ms))
                self._vad_seg_start_ms = None
        if not spans:
            return []

        msgs: List[dict] = []
        for beg_ms, end_ms in spans:
            # 毫秒 → 样本；起点回退 + 与上一句尾取 max 防重叠/吞音
            beg_s = max(self._cur_start, beg_ms * MS_TO_SAMPLES - VAD_SEG_START_PAD)
            end_s = min(len(self._audio), end_ms * MS_TO_SAMPLES)
            if end_s <= beg_s:
                continue
            audio_slice = self._audio[beg_s:end_s]
            # 句尾 final：SenseVoice 离线解码（实测比 paraformer 整句快 ~4x；
            # 不可用时 _run_asr_final_sv 内部回退 paraformer，行为不中断）
            asr_fut = loop.run_in_executor(_EXECUTOR, _run_asr_final_sv, audio_slice)
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
            self._cur_start = end_s

        # 重置 ASR 增量状态（新句重新从 0 计对齐块数，累积文本清空）。
        # 注意：VAD 游标 ``_vad_fed`` 与 ``_vad_cache`` 不重置——VAD 是连续流，
        # 重置会让它重新从缓冲头部解码，正是被修掉的重复喂入问题。
        self._asr_cache = {}
        self._asr_fed_chunks = 0
        self._asr_text = ""
        self._last_asr_t = 0
        self._spec_last_len = 0
        self._spec_text = ""
        # 句已闭合：下一句的 ASR 流起点需对齐到新句真实人声（_trim_leading_silence）
        self._pending_trim = True
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
                # M10（第五轮）: recent_match 须与 classify 在同一锁内读取——
                # 旧实现锁外读，并发 classify（另一 in-flight spk 任务/句）可能在
                # 两步之间改写 _last_match，导致本条 spk 消息的 em_embedding 与
                # spk_id 不属于同一 utterance。
                match = self.session.recent_match()
            self._speaker = (spk_id, bool(registered), float(conf))
        except Exception:
            return
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

    def _trim_leading_silence(self) -> None:
        """把当前句起点对齐到「上一句已闭合」之后的首个有声窗。

        上一句结束时 ``_cur_start`` 被设为 VAD 上报的句尾（落在句尾静音窗内，且**可能
        仍含上一句的语音尾巴**——实测 142ms 语音 + 1.2s 静音）。若新句的 ASR 流仍从
        这里起步：前几个 600ms 对齐块会空转（解码静音），投机解码的切片也带静音前缀
        （paraformer 对「静音+短语音」常返回空），首 partial 被整体推后——实测 WS 多轮
        首 partial 在 460/668/2639/1008/1024ms 间大幅抖动。

        判定：仅当 ``_pending_trim``（上一句已闭合）置位时执行，扫描 200ms 能量窗，
        取**首个「前一窗无声、本窗有声」的位置**为新句起点——这样即使 ``_cur_start``
        当前落在上一句的语音尾巴里，也能越过尾巴与静音落到新句真实起点。未找到候选
        （新句尚未开始说话）则保持不动、标记保留，等下次再试。仅在本句尚无文本
        （``_asr_text == ""``）时生效，避免句中长停顿把起点推到后半句。
        """
        if not self._pending_trim or self._asr_text:
            return
        audio = self._audio
        total = len(audio)
        win = VAD_INTERVAL
        found: Optional[int] = None
        prev_voiced: Optional[bool] = None
        pos = self._cur_start
        while pos < total:
            # 末窗允许不足一个窗口：若要求候选窗之后还有完整一窗才判定，会白等
            # 一个 200ms 节拍才对齐（实测轮 2 首 partial 因此多花 200ms+409ms）。
            seg = audio[pos:min(pos + win, total)]
            if seg.size == 0:
                break
            voiced = float(np.abs(seg).mean()) >= 1e-4
            if voiced and prev_voiced is False:
                found = pos
                break
            prev_voiced = voiced
            pos += win
        if found is None or found <= self._cur_start:
            return
        # 细化：粗扫窗（200ms）只定位到「静音→有声」的窗边界，窗内可能仍有最多一窗的
        # 静音（实测轮 3 候选窗含 0.15s 静音，投机解码切片带静音前缀后连返 4 次空，
        # 首 partial 从 0.23s 退到 2.0s）。按 10ms 子窗在候选窗内前推到首个有声位置。
        sub = 160  # 10ms @16k
        limit = min(found + win, total)
        p = found
        while p + sub <= limit:
            if float(np.abs(audio[p:p + sub]).mean()) >= 1e-4:
                found = p
                break
            p += sub
        if found <= self._cur_start:
            return
        self._cur_start = found
        self._pending_trim = False
        self._asr_cache = {}
        self._asr_fed_chunks = 0
        self._asr_text = ""
        self._last_asr_t = 0
        self._spec_last_len = 0
        self._spec_text = ""

    async def _maybe_partial(self, msgs: List[dict]) -> None:
        """增量 partial：按流式契约喂「对齐块」并**累积**增量文本，产出部分结果。

        契约修正（2026-09-18）：paraformer-zh-streaming（chunk_size=[0,10,5]）要求每次
        ``generate`` 恰好喂 ``ASR_CHUNK_STRIDE``（9600 样本/600ms）对齐块，返回该块的
        增量文本，调用方自行累积。旧实现每次把「整句累积音频」整段重喂（块长不对齐 +
        模型全量重算），单轮 9.44s 音频累计 66.7s CPU（7.1x 实时）——容器追不上实时
        输入，partial 延迟/缺失、跨轮劣化，并以 GIL 争用饿死事件循环引发 WS ping 超时。
        修正后单轮同音频 2130ms（0.20x 实时，31 倍提速），文本与整句离线解码逐字一致。

        短句兜底：对齐块尚不足一个（<600ms 音频）时，对当前缓冲做一次性整句解码作为
        投机 partial 早发（短音频解码廉价），保持首个 partial 早出（驱动 LLM Prefill）；
        并加 ``SPEC_MAX_SAMPLES`` 上界，避免长噪声段反复触发昂贵全量解码。
        """
        loop = asyncio.get_running_loop()
        self._trim_leading_silence()
        # 按对齐块喂未处理音频（每块恰好 ASR_CHUNK_STRIDE；累积增量文本）
        while True:
            offset = self._cur_start + self._asr_fed_chunks * ASR_CHUNK_STRIDE
            if len(self._audio) - offset < ASR_CHUNK_STRIDE:
                break
            chunk = self._audio[offset:offset + ASR_CHUNK_STRIDE]
            out = await loop.run_in_executor(
                _EXECUTOR, _run_asr_partial, chunk, self._asr_cache
            )
            self._asr_fed_chunks += 1
            if out:
                self._asr_text += out

        text = self._asr_text
        # 句起点尚未对齐（``_pending_trim`` 为真，切片带静音前缀）时不做投机解码：
        # paraformer 对「静音 + 短语音」返回空，这次整句解码纯属浪费（实测一次
        # 1.55s 切片白烧 409ms，还占着 _ASR_LOCK 拖慢增量块）。
        #
        # 持续刷新（2026-09-18）：只要对齐块还没产出文本（``_asr_text`` 为空），每个
        # 节拍都重试整句投机解码并下发 partial。旧逻辑「出一次文本就停」会让服务端
        # 拿到首个候选后无后续样本可做延续性确认，被迫干等到首个对齐块（0.6s）才下发。
        if not text and not self._pending_trim:
            sentence_len = len(self._audio) - self._cur_start
            first_try = self._spec_last_len == 0
            if (
                SPEC_MIN_SAMPLES <= sentence_len <= SPEC_MAX_SAMPLES
                and (first_try or sentence_len - self._spec_last_len >= SPEC_RETRY_STEP)
            ):
                self._spec_last_len = sentence_len
                spec = await loop.run_in_executor(
                    _EXECUTOR, _run_asr_final, self._audio[self._cur_start:]
                )
                if spec:
                    text = spec
                    self._spec_text = spec
        # partial 文本单调增长保护：整句投机结果（如 '你好呀'）常比同期的增量对齐块
        # 累积文本（如 '你'）更长——直接切到累积文本会让前端显示的文字**回退**。
        # 仅当累积文本确实是投机结果的前缀（两者描述同一段语音）时才保留较长的投机
        # 文本；一旦累积追平/超出，或与投机结果分叉（前缀不成立），立即以累积为准。
        elif (
            text
            and self._spec_text
            and len(self._spec_text) > len(text)
            and self._spec_text.startswith(text)
        ):
            text = self._spec_text
        self._last_asr_t = 0  # 无论是否有文本，都复位步进锚点
        if text:
            msgs.append(self._partial_msg(text))

    async def finish(self, full_audio_slice: Optional[np.ndarray] = None) -> List[dict]:
        """客户端发 final 时：对当前句剩余尾段做整句 final 识别 + 说话人判定，随后重置。

        ``full_audio_slice`` 若传入则用它作为识别切片（否则用自 [_cur_start:] 的尾段）。

        懒加载触发改造（行为影响最小方案）：保留"未加载则触发加载"语义，但经
        ``asyncio.to_thread`` 执行——同步 ``_load_models()`` 在首次连接时会阻塞
        事件循环数十秒；移入线程后 finish 仍等待模型就绪（外部行为不变），仅不再
        卡住循环。启动期已由 api_server startup 预载，正常路径此调用为零开销。
        """
        await asyncio.to_thread(_load_models)
        tail = (
            full_audio_slice
            if full_audio_slice is not None
            else self._audio[self._cur_start:]
        )
        tail = np.asarray(tail, dtype=np.float32)

        loop = asyncio.get_running_loop()
        # 尾段 final 与 _vad_sweep 保持一致：SenseVoice 离线解码（快 ~4x，
        # 不可用时内部回退 paraformer）
        text_fut = loop.run_in_executor(_EXECUTOR, _run_asr_final_sv, tail)
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