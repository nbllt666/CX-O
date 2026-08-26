"""
统一 TTS 服务
Qwen3 TTS 唯一合成入口，提供非流式、流式与细粒度流式合成能力。
合并了原 TTSClient 的流式合成、情感语音、音效等功能。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional


from server.core.utils import get_shared_http_client, make_semaphore
from server.services.emotion_instruction_service import (
    generate_instruction,
    strip_instruction,
)
from server.services.effect_parser import EffectParser

logger = logging.getLogger(__name__)


def _tts_concurrency() -> tuple[int, bool]:
    """读取 TTS 统一 in-flight 并发上限与背压模式（默认 8 / wait 排队）。

    - 上限取一个不破坏现状的较大数（默认 8），生产可通过 config 调整。
    - 模式：``"wait"`` 超限排队等待；``"drop"`` 超限拒绝（返回空/提前结束）。
    配置读取失败时回退默认，保证零侵入（不破坏既有测试与生产默认）。
    """
    try:
        from server.config import get_settings as _gs
        exec_cfg = _gs().config.executor
        limit = int(getattr(exec_cfg, "tts_concurrency", 8) or 8)
        if limit <= 0:
            limit = 8
        mode = str(getattr(exec_cfg, "tts_backpressure_mode", "wait") or "wait").lower()
        return limit, (mode == "drop")
    except Exception:  # noqa: BLE001 - 配置缺失/加载失败回退默认
        return 8, False


# <tts_instruction> 结构化 JSON 内是否显式含 speed/volume 键的检测
_SPEED_KEY = "speed"
_VOLUME_KEY = "volume"


def _has_json_key(text: str, key: str) -> bool:
    """判断文本内嵌 <tts_instruction> JSON 是否含 `key` 键（精确匹配，避免子串误匹配）。"""
    for tag_m in _TTAG_RE.finditer(text):
        stripped = tag_m.group(1).strip()
        _fence = _FENCE_RE.search(stripped)
        if _fence:
            stripped = _fence.group(1).strip()
        if not stripped.startswith("{"):
            # 纯文本指令（非 JSON），不算显式结构化指定
            continue
        try:
            data = json.loads(stripped)
        except Exception:
            continue
        if isinstance(data, dict) and key in data:
            return True
    return False


# <tts_instruction> 块提取正则（与 emotion_instruction_service._TTS_INSTRUCTION_RE 对齐）
_TTAG_RE = re.compile(r"<tts_instruction\s*>([\s\S]*?)</tts_instruction>")
# Markdown 围栏 JSON 提取
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _label_has_speed_volume(text: str) -> tuple[bool, bool]:
    """检测一段文本内嵌 <tts_instruction> 结构化 JSON 是否显式指定 speed/volume。

    仅当键存在且其值非默认可判定时才返回 True，避免标签缺省覆盖 config 层默认 speed。
    返回 (has_speed, has_volume)。
    """
    has_speed = _has_json_key(text, _SPEED_KEY)
    has_volume = _has_json_key(text, _VOLUME_KEY)
    return has_speed, has_volume


def _inject_label_params(base_kwargs: dict, text: str, instruction) -> dict:
    """从内嵌标签将 speed/volume 注入合成参数；仅当标签显式指定对应键才覆盖。

    instruction 缺省（None / 关闭 / 无标签）时保持 base_kwargs 不变，
    不覆盖 config 层默认 speed。
    """
    out = dict(base_kwargs)
    if instruction is None:
        return out
    has_speed, has_volume = _label_has_speed_volume(text)
    if has_speed:
        out["speed"] = instruction.speed
    if has_volume:
        out["volume"] = instruction.volume
    return out


class TTSService:
    """统一 TTS 服务，Qwen3 TTS 唯一合成入口，提供非流式、流式与细粒度流式合成能力。"""

    def __init__(
        self,
        mode: str = "remote",
        device: str = "cuda",
        remote_url: str = "http://127.0.0.1:5000",
        ref_audio_path: str = "",
        ref_text: str = "",
        speed: float = 1.0,
        cross_fade_duration: float = 0.15,
        effects_dir: str | Path | None = None,
        gateway_url: str | None = None,
        # Qwen3 统一编排：Qwen3 TTS 为唯一合成路径。qwen3_provider 可注入（测试用）。
        qwen3_enabled: bool = False,
        qwen3_provider: Any = None,
        emotion_instruction_enabled: bool = True,
    ):
        self._mode = mode
        self._device = device
        self._remote_url = remote_url
        self._ref_audio_path = ref_audio_path
        self._ref_text = ref_text
        self._speed = speed
        self._cross_fade_duration = cross_fade_duration
        self._initialized = False

        self._effect_parser = EffectParser(effects_dir)
        self._gateway_url = gateway_url.rstrip("/") if gateway_url else None
        self._ref_audio_data: bytes | None = None
        # Qwen3 统一编排状态
        self._qwen3_enabled = bool(qwen3_enabled)
        self._qwen3_provider = qwen3_provider
        self._emotion_instruction_enabled = bool(emotion_instruction_enabled)
        # 语音多会话并发治理：统一 in-flight 信号量 + 背压模式（默认 8 / wait）
        self._tts_limit, self._tts_drop = _tts_concurrency()
        self._tts_sem = make_semaphore(self._tts_limit)

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self):
        logger.info(f"TTS service in {self._mode} mode, target: {self._remote_url}")
        self._initialized = True

    async def shutdown(self):
        self._initialized = False

    # ================================================================ Qwen3 统一编排
    def _qwen3_defaults(self) -> dict:
        """读取 Qwen3 默认合成参数（voice/language/output_format/speed），失败回退内置默认。"""
        try:
            from server.config import get_settings
            d = get_settings().config.qwen3_tts.default
            return {
                "voice": d.voice,
                "language": d.language,
                "output_format": d.output_format,
                "speed": float(d.speed),
            }
        except Exception:  # noqa: BLE001 - 配置缺失时回退内置默认
            return {"voice": None, "language": None, "output_format": "wav", "speed": 1.0}

    def _register_file_asset(self, path: str, ref_text: str | None) -> str:
        """旧协议 ref_audio_path + ref_text → 经 ref_audio_store 注册为资产，返回 ref_ 前缀 ID。"""
        from server import ref_audio_store
        asset = ref_audio_store.register_from_file(str(path), ref_text=ref_text)
        return asset.id

    def _register_base64_asset(self, b64: str, ref_text: str | None) -> str:
        """旧协议 base64 ref_audio → 写入资产目录并注册为资产，返回 ref_ 前缀 ID。"""
        audio_data = base64.b64decode(b64)
        from server.config import get_settings
        assets_dir = Path(get_settings().tts.ref_audio_assets_dir)
        assets_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".wav", dir=str(assets_dir))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio_data)
            return self._register_file_asset(tmp, ref_text)
        finally:
            try:
                os.unlink(tmp)
            except Exception:  # noqa: BLE001 - 清理尽力而为
                pass

    def _build_ref_ids(self, kwargs: dict) -> list[str]:
        """把调用方传入的参考音频（refs / ref_asset_id / ref_audio 资产ID / 旧协议 path+base64）
        归一化为 ref_ 前缀资产 ID 列表。无参考音频时回退当前默认资产；再无则空列表
        （Qwen3 可无 refs 合成）。

        旧协议（ref_audio_path / base64 ref_audio）尽量经 register_from_file 注册为资产再取 ID，
        注册失败（非法音频/路径穿越）由 ref_audio_store 抛 InvalidRefAudioError。
        """
        ids: list[str] = []

        refs = kwargs.get("refs")
        if isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, (list, tuple)):
            for r in refs:
                if r:
                    ids.append(str(r))

        ref_asset_id = kwargs.get("ref_asset_id")
        if ref_asset_id:
            ids.append(str(ref_asset_id))

        ref_audio = kwargs.get("ref_audio")
        if ref_audio:
            if isinstance(ref_audio, str) and ref_audio.startswith("ref_"):
                # ref_audio 作为资产 ID 传入（新协议）
                ids.append(ref_audio)
            else:
                # 旧协议：base64 参考音频 → 注册为资产
                ids.append(self._register_base64_asset(ref_audio, kwargs.get("ref_text")))

        ref_audio_path = kwargs.get("ref_audio_path")
        if ref_audio_path:
            # 旧协议：磁盘路径 → 注册为资产
            ids.append(self._register_file_asset(ref_audio_path, kwargs.get("ref_text")))

        result: list[str] = []
        for i in ids:
            if i and i not in result:
                result.append(i)

        # 显式未指定任何参考音频时，按优先级回退：
        #   1) kwargs["agent_id"] 对应 Agent 的 per-agent 绑定资产（A3）
        #   2) 当前默认资产（get_current）
        if not result:
            from server import ref_audio_store
            agent_id = kwargs.get("agent_id")
            if agent_id:
                binding = ref_audio_store.get_for_agent(agent_id)
                if binding and binding.get("asset_id"):
                    result.append(binding["asset_id"])
                    logger.info(
                        f"使用 Agent {agent_id} 绑定参考音频资产: {binding['asset_id']}"
                    )
            if not result:
                current = ref_audio_store.get_current()
                if current is not None:
                    result.append(current.id)
                    logger.info(f"使用当前默认参考音频资产: {current.id}")

        return result

    async def _gen_instruction(self, text: str) -> str | None:
        """生成 tts_instruction 自然语言文本；emotion_instruction 关闭时返回 None。"""
        inst = await self._gen_instruction_full(text)
        return inst.text or None if inst else None

    async def _gen_instruction_full(self, text: str):
        """生成完整 EmotionInstruction（含 speed/volume 真实参数），关闭时返回 None。

        对 speed/volume 做防御性读取（兼容测试中仅实现 .text 的轻量替身）。
        """
        if not self._emotion_instruction_enabled:
            return None
        try:
            instruction = await generate_instruction(text)
        except Exception:
            return None
        if instruction is None:
            return None
        # 防御性读取：缺省时 speed/volume 保持 1.0（与 EmotionInstruction 默认值一致）
        try:
            speed = float(getattr(instruction, "speed", 1.0) or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        try:
            volume = float(getattr(instruction, "volume", 1.0) or 1.0)
        except (TypeError, ValueError):
            volume = 1.0
        if speed <= 0:
            speed = 1.0
        if volume <= 0:
            volume = 1.0
        # 简单封装，统一 .text/.speed/.volume 访问
        from types import SimpleNamespace
        return SimpleNamespace(
            text=(instruction.text or None) if getattr(instruction, "text", None) else None,
            speed=speed,
            volume=volume,
        )

    def _build_qwen3_request(self, text, ref_ids, instruction_text, stream, **kwargs):
        """组装 Qwen3 SynthesisRequest（defaults 从配置读取，kwargs 可覆盖）。

        speed 优先级：kwargs.speed > defaults.speed > 1.0；
        volume 优先级：kwargs.volume > 1.0（由 _synthesize_stream_fine 从标签注入）。
        """
        from server.qwen3_tts_provider import SynthesisRequest
        defaults = self._qwen3_defaults()
        speed = float(kwargs.get("speed") if kwargs.get("speed") is not None else defaults.get("speed") or 1.0)
        volume = float(kwargs.get("volume") if kwargs.get("volume") is not None else 1.0)
        if speed <= 0:
            speed = 1.0
        if volume <= 0:
            volume = 1.0
        return SynthesisRequest(
            text=text,
            refs=ref_ids,
            tts_instruction=instruction_text,
            voice=kwargs.get("voice") or defaults.get("voice"),
            language=(kwargs.get("language") or defaults.get("language")) or None,
            stream=stream,
            output_format=kwargs.get("output_format") or defaults.get("output_format") or "wav",
            speed=speed,
            volume=volume,
        )

    async def _synthesize_qwen3(self, text: str, **kwargs) -> bytes:
        """Qwen3 非流式合成：剥离指令 → 生成指令 → 委托 Provider，返回完整音频 bytes。"""
        clean = strip_instruction(text)
        instruction = await self._gen_instruction_full(text)
        ref_ids = self._build_ref_ids(kwargs)
        req_kwargs = _inject_label_params(kwargs, text, instruction)
        req = self._build_qwen3_request(clean, ref_ids, instruction.text if instruction else None,
                                        stream=False, **req_kwargs)
        resp = await self._qwen3_provider.synthesize(req)
        return resp.audio

    async def _synthesize_stream_qwen3(self, text: str, **kwargs):
        """Qwen3 流式合成：直接委托 Provider 的 AudioChunk 流，保持 chunk 顺序与 is_final。"""
        clean = strip_instruction(text)
        instruction = await self._gen_instruction_full(text)
        ref_ids = self._build_ref_ids(kwargs)
        req_kwargs = _inject_label_params(kwargs, text, instruction)
        req = self._build_qwen3_request(clean, ref_ids, instruction.text if instruction else None,
                                        stream=True, **req_kwargs)
        async for chunk in self._qwen3_provider.synthesize_stream(req):
            yield {
                "text_segment": clean if chunk.is_start else "",
                "audio_data": chunk.data,
                "chunk_index": chunk.index,
                "is_final": chunk.is_final,
            }

    async def _synthesize_stream_fine_qwen3(self, token_stream, char_threshold: int = 3, **kwargs):
        """Qwen3 细粒度流式合成：token 流 → 分块 → 逐段流式合成，末尾发 final 标记。

        每段从内嵌 <tts_instruction> 解析出 speed/volume 后，仅当标签显式指定时才
        覆盖本段真实合成参数（避免用标签缺省值覆盖 config 层默认 speed）。
        """
        ref_ids = self._build_ref_ids(kwargs)
        chunk_index = 0
        async for text_segment in self.split_text_streaming(
            token_stream, char_threshold=char_threshold
        ):
            if not text_segment.strip():
                continue
            clean = strip_instruction(text_segment)
            instruction = await self._gen_instruction_full(text_segment)
            # 逐段标签覆盖：仅当标签显式包含 speed/volume 键才注入，不覆盖 config 默认
            seg_kwargs = _inject_label_params(kwargs, text_segment, instruction)
            req = self._build_qwen3_request(clean, ref_ids, instruction.text if instruction else None,
                                            stream=True, **seg_kwargs)
            async for chunk in self._qwen3_provider.synthesize_stream(req):
                yield {
                    "text_segment": text_segment if chunk.is_start else "",
                    "audio_data": chunk.data,
                    "chunk_index": chunk_index,
                    "is_final": False,
                }
                chunk_index += 1
        yield {"text_segment": "", "audio_data": None, "chunk_index": chunk_index, "is_final": True}

    async def synthesize(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        ref_audio: str | None = None,
        speed: float | None = None,
        cross_fade_duration: float | None = None,
        **kwargs
    ) -> bytes:
        """非流式合成：Qwen3 TTS 唯一合成路径。受统一 in-flight 信号量约束。"""
        # drop 模式：超限直接拒绝（返回空 bytes），不进入排队
        if self._tts_drop and self._tts_sem.locked():
            logger.warning("TTS in-flight 已达 %s，drop 模式丢弃本次合成", self._tts_limit)
            return b""
        await self._tts_sem.acquire()
        try:
            combined = dict(kwargs)
            if ref_audio_path:
                combined["ref_audio_path"] = ref_audio_path
            if ref_text:
                combined["ref_text"] = ref_text
            if ref_audio:
                combined["ref_audio"] = ref_audio
            if speed is not None:
                combined["speed"] = speed
            return await self._synthesize_qwen3(text, **combined)
        finally:
            self._tts_sem.release()

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式合成：Qwen3 TTS 唯一合成路径。受统一 in-flight 信号量约束。"""
        # drop 模式：超限直接结束（不产生任何 chunk），不进入排队
        if self._tts_drop and self._tts_sem.locked():
            logger.warning("TTS in-flight 已达 %s，drop 模式丢弃本次流式合成", self._tts_limit)
            return
        await self._tts_sem.acquire()
        try:
            combined = dict(kwargs)
            if ref_audio_path:
                combined["ref_audio_path"] = ref_audio_path
            if ref_text:
                combined["ref_text"] = ref_text
            async for chunk in self._synthesize_stream_qwen3(text, **combined):
                yield chunk
        finally:
            self._tts_sem.release()

    async def split_text_streaming(
        self,
        token_stream: AsyncGenerator[str, None],
        char_threshold: int = 4,
    ) -> AsyncGenerator[str, None]:
        """
        细粒度流式分块器：基于「字数阈值 + 停顿标点」双重触发机制。

        相比 split_text_by_sentences() 必须等到句号才切片，本方法在累积
        中文字符达到阈值或遇到停顿标点时立即切片，使 TTS 不必死等 LLM
        吐出整句，从而将首包音频延迟压缩数百毫秒（目标 <300ms）。

        - 字数阈值（默认 4，范围 3~5）：累积中文字符达标即切片，
          省去等待句号/逗号的数百毫秒阻塞。
        - 停顿标点（，、；：）：遇到即切片，利用自然语义边界，
          保证切片位置在可朗读的停顿处，避免语音割裂感。
        """
        # 阈值范围保护：限制在 2~5 之间，过小会导致切片过碎增加 TTS 调用开销，
        # 过大则失去细粒度优势、退化为接近整句分割
        # C4 P50<600ms 二轮优化：硬下限 3 → 2，允许更激进的 2 字切片（本次仍用 3）
        char_threshold = max(2, min(5, int(char_threshold)))

        # 停顿标点集合：中文逗号/顿号/分号/冒号 + 英文兼容写法
        pause_punctuation = "，、；：,;:"

        buffer = ""
        chinese_char_count = 0  # 仅统计中文字符，避免英文/数字/标点干扰阈值判断

        async for token in token_stream:
            if not token:
                continue

            buffer += token

            # 统计本 token 新增的中文字符数（CJK 统一表意文字范围）
            for char in token:
                if "\u4e00" <= char <= "\u9fff":
                    chinese_char_count += 1

            # 双重触发判定：任一条件满足即立即切片
            should_slice = False
            cut_pos = -1

            # 触发条件 1：遇到停顿标点 → 在最后一个停顿标点之后切分（保留标点）
            # 这样切片落在自然停顿处，TTS 合成的语音片段语义完整、听感自然
            for p in pause_punctuation:
                idx = buffer.rfind(p)
                if idx != -1:
                    cut_pos = max(cut_pos, idx + 1)
                    should_slice = True

            # 触发条件 2：中文字数达到阈值 → 强制切片，避免死等标点
            # 这是压缩首包延迟的关键：LLM 流式吐字时，凑够 4 个字即可送 TTS，
            # 不必等待句号（往往要等十几个字甚至整句），可省下数百毫秒
            if chinese_char_count >= char_threshold:
                should_slice = True
                # 若未命中标点，则整段 buffer 作为切片（LLM token 通常 1~3 字，
                # buffer 一般不会远超阈值）
                if cut_pos == -1:
                    cut_pos = len(buffer)

            if should_slice and cut_pos > 0:
                chunk = buffer[:cut_pos]
                buffer = buffer[cut_pos:]
                # 重新统计剩余 buffer 的中文字数，保证下一轮阈值判定准确
                chinese_char_count = sum(
                    1 for c in buffer if "\u4e00" <= c <= "\u9fff"
                )

                if chunk.strip():
                    yield chunk

        # 流结束后吐出剩余 buffer，保证末尾文本不丢失
        if buffer.strip():
            yield buffer

    async def synthesize_stream_fine(
        self,
        token_stream: AsyncGenerator[str, None],
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        char_threshold: int = 3,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        细粒度流式合成：直接对接 LLM token 流，边收边切边合成（Qwen3 流式合成）。

        全链路使用 async/await，绝不阻塞主线程：
        LLM token 流 → split_text_streaming 细粒度切片 → 逐块调用 Qwen3 流式合成 → yield 音频块

        每个 yield 的 dict 包含：text_segment, audio_data, chunk_index, is_final。

        第五轮 M6：并入统一 in-flight 信号量——旧实现绕过 ``_tts_sem``，
        双流式主路径（DualStreamSession._run_pipeline/_play_reply）可无限制
        建立 Qwen3 流式合成，绕过为此链路设计的背压护栏。
        """
        # drop 模式：超限直接结束（不产生任何 chunk），与 synthesize_stream 一致
        if self._tts_drop and self._tts_sem.locked():
            logger.warning(
                "TTS in-flight 已达 %s，drop 模式丢弃细粒度流式合成", self._tts_limit
            )
            return
        await self._tts_sem.acquire()
        try:
            combined = dict(kwargs)
            if ref_audio_path:
                combined["ref_audio_path"] = ref_audio_path
            if ref_text:
                combined["ref_text"] = ref_text
            async for chunk in self._synthesize_stream_fine_qwen3(
                token_stream, char_threshold=char_threshold, **combined
            ):
                yield chunk
        finally:
            self._tts_sem.release()

    async def synthesize_with_emotions(
        self,
        text: str,
        **kwargs
    ) -> bytes:
        """带情感标注的非流式合成：情感由 tts_instruction 承载，委托 Qwen3 合成。"""
        return await self._synthesize_qwen3(text, **kwargs)

    async def synthesize_stream_with_emotions(
        self,
        text: str,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """带情感标注的流式合成：情感由 tts_instruction 承载，委托 Qwen3 流式合成。"""
        async for chunk in self._synthesize_stream_qwen3(text, **kwargs):
            yield chunk

    async def get_voices(self) -> list[dict[str, Any]]:
        """列出可用音色：参考音频资产优先，保留 default 兜底。

        #14（CX-O问题汇总报告）: 旧实现硬编码单一 default，未接资产库。
        现枚举 ref_audio_store 已注册资产（id=资产 id，name 取 note/文件名），
        资产库不可用时降级为默认音色。
        """
        voices: list[dict[str, Any]] = [{"id": "default", "name": "Default Voice"}]
        try:
            from server import ref_audio_store

            for asset in ref_audio_store.list():
                if asset.is_deleted:
                    continue
                voices.append({
                    "id": asset.id,
                    "name": asset.note or asset.file_name or asset.prompt or asset.id,
                })
        except Exception as e:
            logger.warning(f"读取参考音频资产失败，仅返回默认音色: {e}")
        return voices

    def _load_effect_audio(self, effect_name: str) -> bytes | None:
        return self._effect_parser._load_effect(effect_name)

    async def health_check(self) -> bool:
        try:
            client = get_shared_http_client()
            response = await client.get(f"{self._remote_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"TTS health check failed: {e}")
            return False


_tts_service: Optional[TTSService] = None

# VoiceDesign 参考音频生成时的默认合成文本（用自然语言音色描述作为 instructions）
_VOICEDESIGN_SAMPLE_TEXT = "你好，我是由语音设计模型生成的音色，希望你喜欢我的声音。"


def get_tts_service() -> TTSService:
    """获取全局唯一的 TTSService 单例，按配置惰性初始化。"""

    global _tts_service
    if _tts_service is None:
        from server.config import get_settings
        settings = get_settings()

        # Qwen3 统一编排：配置启用时注入 Provider，ref_resolver 接到 ref_audio_store
        qwen3_enabled = bool(settings.config.qwen3_tts.enabled)
        qwen3_provider = None
        emotion_instruction_enabled = bool(
            settings.config.qwen3_tts.emotion_instruction.enabled
        )
        if qwen3_enabled:
            from server import ref_audio_store
            from server.qwen3_tts_provider import Qwen3TTSProvider, SynthesisRequest

            def _ref_resolver(asset_id):
                asset = ref_audio_store.resolve(asset_id)
                data = ref_audio_store.get_audio_path(asset_id).read_bytes()
                return {
                    "data": data,
                    "sample_rate": asset.sample_rate or 24000,
                    "ref_text": asset.ref_text or "",
                    "channels": asset.channels or 1,
                }

            qwen3_provider = Qwen3TTSProvider(ref_resolver=_ref_resolver)

            async def _prompt_generator(prompt, language=None):
                """VoiceDesign 根据自然语言音色描述生成参考音频（source=prompt）。

                无 refs 的日常/情感合成由 Provider 路由到 vLLM VoiceDesign，
                tts_instruction 承载音色描述（instructions）。
                """
                from server.ref_audio_store import GeneratedAudio

                req = SynthesisRequest(
                    text=_VOICEDESIGN_SAMPLE_TEXT,
                    refs=[],
                    tts_instruction=prompt,
                    voice=None,
                    language=language or None,
                    stream=False,
                    output_format="wav",
                    speed=1.0,
                )
                resp = await qwen3_provider.synthesize(req)
                return GeneratedAudio(
                    audio=resp.audio,
                    format=resp.format,
                    sample_rate=resp.sample_rate,
                    channels=resp.channels,
                    duration_seconds=resp.duration_seconds or 0.0,
                )

            ref_audio_store.set_prompt_generator(_prompt_generator)

        _tts_service = TTSService(
            mode=settings.tts.mode,
            device=settings.tts.device,
            remote_url=settings.tts.remote_url,
            ref_audio_path=settings.tts.ref_audio_path,
            ref_text=settings.tts.ref_text,
            speed=settings.tts.speed,
            cross_fade_duration=settings.tts.cross_fade_duration,
            effects_dir=settings.tts.transitions_dir if settings.tts.effects_enabled else None,
            gateway_url=settings.tts.remote_url,
            # Qwen3 统一编排
            qwen3_enabled=qwen3_enabled,
            qwen3_provider=qwen3_provider,
            emotion_instruction_enabled=emotion_instruction_enabled,
        )
    return _tts_service
