"""
统一 TTS 服务
支持 embedded（直接调用 F5-TTS 模型）和 remote（HTTP 调用）两种模式
合并了原 TTSClient 的流式合成、情感语音、音效、Triton 推理等功能
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

import httpx

from server.core.utils import get_shared_http_client, close_shared_http_client, retry_with_backoff
from server.services.emotion_parser import extract_emotions_with_text, parse_text_with_emotions
from server.services.effect_parser import EffectParser
from server.services.tts_audio_utils import (
    split_text_by_sentences,
    generate_silence,
    concatenate_audio,
    load_emotion_voices,
)

logger = logging.getLogger(__name__)


class TTSService:
    def __init__(
        self,
        mode: str = "remote",
        model_dir: str = "",
        device: str = "cuda",
        remote_url: str = "http://127.0.0.1:5000",
        ref_audio_path: str = "",
        ref_text: str = "",
        speed: float = 1.0,
        cross_fade_duration: float = 0.15,
        emotion_voices: dict[str, dict[str, str]] | None = None,
        effects_dir: str | Path | None = None,
        voice_refs_dir: str | Path | None = None,
        gateway_url: str | None = None,
        use_triton: bool = False,
        orpheus_url: str = "http://127.0.0.1:5060",
        orpheus_voice: str = "tara",
        orpheus_timeout: int = 60,
    ):
        self._mode = mode
        self._model_dir = model_dir
        self._device = device
        self._remote_url = remote_url
        self._ref_audio_path = ref_audio_path
        self._ref_text = ref_text
        self._speed = speed
        self._cross_fade_duration = cross_fade_duration
        self._initialized = False

        self._emotion_voices = emotion_voices or {}
        self._effect_parser = EffectParser(effects_dir)
        self._emotion_audio_cache: dict[str, bytes] = {}
        self._voice_refs_dir = Path(voice_refs_dir) if voice_refs_dir else Path(__file__).parent.parent / "data" / "voice_refs"
        self._gateway_url = gateway_url.rstrip("/") if gateway_url else None
        self._use_triton = use_triton
        self._ref_audio_data: bytes | None = None
        # Orpheus TTS 配置：使用预设音色（tara 等），无需 ref_audio / ref_text
        self._orpheus_url = orpheus_url.rstrip("/")
        self._orpheus_voice = orpheus_voice
        self._orpheus_timeout = orpheus_timeout

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self):
        if self._mode != "embedded":
            logger.info(f"TTS service in remote mode, target: {self._remote_url}")
            self._initialized = True
            return

        from f5_tts.api import load_model, get_f5tts
        if get_f5tts() is not None:
            self._initialized = True
            return

        logger.info(f"Loading F5-TTS model...")
        if not load_model():
            raise RuntimeError("Failed to load F5-TTS model")
        self._initialized = True
        logger.info("F5-TTS model loaded successfully")

    async def shutdown(self):
        import f5_tts.api as _api
        _api._f5tts_instance = None
        self._initialized = False

    async def _validate_triton_for_low_latency(self, **kwargs) -> None:
        """
        低延迟 TTS 模型的 Triton 强制校验。

        当检测到底层调用低延迟 TTS 模型（如 Qwen3-TTS）且 use_triton=False 时，
        记录警告日志并尝试自动启用 Triton 推理，以保障首包音频延迟 <300ms。
        可通过 model_type 参数或配置判断是否为低延迟模型。
        """
        # 低延迟 TTS 模型标识集合（小写匹配，兼容大小写写法）
        low_latency_models = {"qwen3-tts", "qwen3_tts", "qwen-tts"}
        model_type = kwargs.get("model_type", "")
        is_low_latency = (
            isinstance(model_type, str) and model_type.lower() in low_latency_models
        )

        if is_low_latency and not self._use_triton:
            logger.warning(
                f"检测到低延迟 TTS 模型 ({model_type}) 但 use_triton=False，"
                f"首包延迟可能无法达标（目标 <300ms）。尝试自动启用 Triton 推理以降低延迟。"
            )
            # 自动启用 Triton 需 gateway_url 可用，否则无法切换推理后端
            if self._gateway_url:
                self._use_triton = True
                logger.info("已自动启用 Triton 推理模式以保障低延迟首包。")
            else:
                logger.warning(
                    "无法自动启用 Triton：gateway_url 未配置，"
                    "低延迟首包可能无法保证 <300ms。"
                )

    async def _load_ref_audio(self) -> bytes:
        if self._ref_audio_data is None:
            if not self._ref_audio_path:
                raise ValueError(
                    "TTS requires reference audio. "
                    "Please provide ref_audio in request data or configure ref_audio_path in config.json"
                )
            if not Path(self._ref_audio_path).exists():
                raise ValueError(f"Reference audio file not found: {self._ref_audio_path}")
            with open(self._ref_audio_path, "rb") as f:
                self._ref_audio_data = f.read()
        return self._ref_audio_data

    def _resolve_audio_path(self, ref_audio: str) -> Path | None:
        if not ref_audio:
            return None

        if Path(ref_audio).is_absolute():
            return Path(ref_audio)

        if Path(ref_audio).exists():
            return Path(ref_audio)

        voice_refs_path = self._voice_refs_dir / ref_audio
        if voice_refs_path.exists():
            return voice_refs_path

        return None

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
        # orpheus 模式：直接调用远程服务
        if self._mode == "orpheus":
            return await self._synthesize_orpheus(text, **kwargs)
        
        # 入口校验：低延迟模型强制启用 Triton，避免首包延迟超标
        await self._validate_triton_for_low_latency(**kwargs)

        audio_path = ref_audio_path or self._ref_audio_path
        text_ref = ref_text or self._ref_text
        spd = speed or self._speed
        cfd = cross_fade_duration or self._cross_fade_duration

        if ref_audio:
            try:
                audio_data = base64.b64decode(ref_audio)
            except Exception as e:
                raise ValueError(f"Invalid base64 ref_audio: {e}")
        elif audio_path and Path(audio_path).exists():
            audio_data = open(audio_path, "rb").read()
        else:
            audio_data = await self._load_ref_audio()

        if not text_ref:
            raise ValueError(
                "TTS requires reference text that matches the reference audio. "
                "Please provide ref_text in request data or configure it in config.json"
            )

        if self._mode == "embedded":
            from f5_tts.api import get_f5tts
            if get_f5tts() is not None:
                return await self._synthesize_embedded(text, audio_path, text_ref, spd, cfd, **kwargs)

        if self._use_triton and self._gateway_url:
            return await self._synthesize_triton(text, audio_data, text_ref, **kwargs)
        else:
            return await self._synthesize_remote(text, audio_data, text_ref, spd, cfd, **kwargs)

    async def _synthesize_embedded(
        self, text: str, ref_audio_path: str, ref_text: str, speed: float, cross_fade_duration: float, **kwargs
    ) -> bytes:
        from f5_tts.api import infer

        ref_path = ref_audio_path
        output_fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(output_fd)

        try:
            infer(
                ref_file=ref_path,
                ref_text=ref_text,
                gen_text=text,
                output_path=output_path,
                speed=speed,
                cross_fade_duration=cross_fade_duration,
                nfe_step=kwargs.get("nfe_step", 32),
                cfg_strength=kwargs.get("cfg_strength", 2),
                seed=kwargs.get("seed", -1),
                remove_silence=kwargs.get("remove_silence", False),
            )

            with open(output_path, "rb") as f:
                audio_data = f.read()
            return audio_data
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def _build_tts_request_data(
        self,
        gen_text: str,
        ref_text: str,
        audio_data: bytes,
        **kwargs
    ) -> tuple[dict, dict]:
        """构建TTS请求的files和data字典"""
        files = {
            "ref_audio": ("ref_audio.wav", audio_data, "audio/wav")
        }
        data = {
            "ref_text": ref_text,
            "gen_text": gen_text,
            "model_type": kwargs.get("model_type", "F5-TTS"),
            "remove_silence": str(kwargs.get("remove_silence", False)).lower(),
            "cross_fade_duration": str(kwargs.get("cross_fade_duration", 0.15)),
            "speed": str(kwargs.get("speed", 1.0)),
            "nfe_step": str(kwargs.get("nfe_step", 32)),
            "cfg_strength": str(kwargs.get("cfg_strength", 2)),
            "seed": str(kwargs.get("seed", -1))
        }
        return files, data

    async def _make_tts_request(
        self,
        gen_text: str,
        ref_text: str,
        audio_data: bytes,
        **kwargs
    ) -> bytes:
        """执行TTS HTTP请求"""
        async def _make_request():
            client = get_shared_http_client()
            files, data = self._build_tts_request_data(gen_text, ref_text, audio_data, **kwargs)
            response = await client.post(f"{self._remote_url}/tts/", files=files, data=data)
            response.raise_for_status()
            return response.content

        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="TTS")

    async def _synthesize_remote(
        self, text: str, audio_data: bytes, ref_text: str, speed: float, cross_fade_duration: float, **kwargs
    ) -> bytes:
        return await self._make_tts_request(
            gen_text=text,
            ref_text=ref_text,
            audio_data=audio_data,
            speed=speed,
            cross_fade_duration=cross_fade_duration,
            **kwargs
        )

    async def _synthesize_triton(
        self,
        text: str,
        audio_data: bytes,
        ref_text: str,
        **kwargs
    ) -> bytes:
        async def _make_request():
            client = get_shared_http_client()
            ref_audio_b64 = base64.b64encode(audio_data).decode("utf-8")

            response = await client.post(
                f"{self._gateway_url}/api/v1/tts/synthesize",
                json={
                    "reference_audio": ref_audio_b64,
                    "reference_text": ref_text,
                    "target_text": text,
                    "speed": float(kwargs.get("speed", 1.0))
                }
            )
            response.raise_for_status()
            result = response.json()

            if "audio_data" in result:
                return base64.b64decode(result["audio_data"])
            elif "error" in result:
                raise ValueError(f"TTS error: {result['error']}")
            else:
                raise ValueError("TTS response missing audio_data")

        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="TTS-Triton")

    async def _synthesize_orpheus(
        self,
        text: str,
        voice: str | None = None,
        **kwargs
    ) -> bytes:
        """
        调用 Orpheus TTS（vLLM OpenAI 兼容 API）合成音频。

        设计说明：
        - Orpheus 使用预设音色（tara/leo 等），不传 ref_audio / ref_text，
          通过 voice 参数选择音色，因此无需参考音频。
        - 请求体格式：{"input": "{voice}: {text}", "voice": voice, "stream": false}
          voice 前缀是 Orpheus 模型的音色控制约定（如 "tara: 你好"）。
        - text 中的 <laugh>、<giggle> 等情感标签原样透传，由 Orpheus 模型自行解析，
          本方法不做任何解析或剥离，以保留 Orpheus 原生情感控制能力。
        - 返回完整 audio bytes（WAV 格式，24000Hz 16-bit PCM）。
        """
        # 选定音色：优先使用调用方传入的 voice，否则回退到构造时配置的默认音色
        selected_voice = voice or self._orpheus_voice

        # 拼接 Orpheus 约定的输入格式："{voice}: {text}"
        # 情感标签（如 <laugh>...</laugh>）原样保留在 text 中透传
        orpheus_input = f"{selected_voice}: {text}"

        async def _make_request():
            # 使用独立 httpx.AsyncClient 以便精确控制超时（Orpheus 合成可能较慢）
            async with httpx.AsyncClient(
                timeout=self._orpheus_timeout
            ) as client:
                response = await client.post(
                    f"{self._orpheus_url}/v1/audio/speech",
                    json={
                        "input": orpheus_input,
                        "voice": selected_voice,
                        "stream": False,
                    }
                )
                response.raise_for_status()
                # 响应体为完整 audio/wav（24000Hz, 16-bit PCM），直接返回 bytes
                return response.content

        return await retry_with_backoff(
            _make_request,
            max_retries=3,
            base_delay=1.0,
            max_delay=30.0,
            service_name="TTS-Orpheus",
        )

    async def _validate_orpheus_service(self) -> None:
        """
        Orpheus 服务健康检查：启动时 ping {orpheus_url}/health。

        设计说明：
        - Orpheus 不使用 Triton，因此跳过 _validate_triton_for_low_latency() 校验。
        - 健康检查失败仅记录警告日志，不阻塞服务启动（允许 Orpheus 后置启动）。
        """
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                response = await client.get(f"{self._orpheus_url}/health")
                if response.status_code == 200:
                    logger.info(
                        f"Orpheus TTS 服务健康检查通过: {self._orpheus_url}/health"
                    )
                else:
                    logger.warning(
                        f"Orpheus TTS 服务健康检查返回非 200 状态码: "
                        f"{response.status_code}，服务可能未完全就绪。"
                    )
        except Exception as e:
            # 健康检查失败不阻塞启动，仅记录警告（Orpheus 可随后启动）
            logger.warning(
                f"Orpheus TTS 服务健康检查失败（不阻塞启动）: {self._orpheus_url}/health - {e}"
            )

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        # 入口校验：低延迟模型强制启用 Triton，避免首包延迟超标
        await self._validate_triton_for_low_latency(**kwargs)

        sentences = split_text_by_sentences(text)

        audio_path = ref_audio_path or self._ref_audio_path
        text_ref = ref_text or self._ref_text

        if not audio_path:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": "TTS requires reference audio. Please provide ref_audio in request data."
            }
            return

        if not text_ref:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": "TTS requires reference text. Please provide ref_text in request data."
            }
            return

        try:
            if ref_audio_path and Path(ref_audio_path).exists():
                audio_data = open(ref_audio_path, "rb").read()
            else:
                audio_data = await self._load_ref_audio()
        except ValueError as e:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": str(e)
            }
            return

        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue

            try:
                if self._mode == "embedded":
                    from f5_tts.api import get_f5tts
                    if get_f5tts() is not None:
                        audio_bytes = await self._synthesize_embedded(
                            sentence, audio_path, text_ref,
                            kwargs.get("speed", self._speed),
                            kwargs.get("cross_fade_duration", self._cross_fade_duration),
                            **kwargs
                        )
                        chunk = {
                            "text_segment": sentence,
                            "audio_data": audio_bytes,
                            "chunk_index": i,
                            "is_final": i == len(sentences) - 1
                        }
                        if on_chunk and audio_bytes:
                            on_chunk(sentence, audio_bytes)
                        yield chunk
                        continue

                audio_bytes = await self._make_tts_request(
                    gen_text=sentence,
                    ref_text=text_ref,
                    audio_data=audio_data,
                    **kwargs
                )

                chunk = {
                    "text_segment": sentence,
                    "audio_data": audio_bytes,
                    "chunk_index": i,
                    "is_final": i == len(sentences) - 1
                }

                if on_chunk and audio_bytes:
                    on_chunk(sentence, audio_bytes)

                yield chunk

            except Exception as e:
                logger.error(f"TTS stream error for sentence {i}: {e}")
                yield {
                    "text_segment": sentence,
                    "audio_data": None,
                    "chunk_index": i,
                    "is_final": i == len(sentences) - 1,
                    "error": str(e)
                }

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
        # 阈值范围保护：限制在 3~5 之间，过小会导致切片过碎增加 TTS 调用开销，
        # 过大则失去细粒度优势、退化为接近整句分割
        char_threshold = max(3, min(5, int(char_threshold)))

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
        char_threshold: int = 4,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        细粒度流式合成：直接对接 LLM token 流，边收边切边合成。

        全链路使用 async/await，绝不阻塞主线程：
        LLM token 流 → split_text_streaming 细粒度切片 → 逐块调用 TTS 引擎 → yield 音频块

        支持 embedded / remote / triton / orpheus 四种模式（复用现有合成方法）。
        每个 yield 的 dict 包含：text_segment, audio_data, chunk_index, is_final。
        """
        # 入口校验：orpheus 模式跳过 Triton 校验（Orpheus 不使用 Triton，使用预设音色）
        if self._mode == "orpheus":
            await self._validate_orpheus_service()
        else:
            # 低延迟模型强制启用 Triton，避免首包延迟超标
            await self._validate_triton_for_low_latency(**kwargs)

        # Orpheus 模式使用预设音色（tara 等），无需 ref_audio / ref_text，跳过参考音频加载
        if self._mode == "orpheus":
            audio_path = None
            text_ref = None
            audio_data = None
        else:
            audio_path = ref_audio_path or self._ref_audio_path
            text_ref = ref_text or self._ref_text

            # 预加载参考音频：一次性加载复用，避免每个 chunk 重复磁盘 IO 拖慢首包
            try:
                if ref_audio_path and Path(ref_audio_path).exists():
                    audio_data = open(ref_audio_path, "rb").read()
                else:
                    audio_data = await self._load_ref_audio()
            except ValueError as e:
                yield {
                    "text_segment": "",
                    "audio_data": None,
                    "chunk_index": 0,
                    "is_final": True,
                    "error": str(e),
                }
                return

            if not text_ref:
                yield {
                    "text_segment": "",
                    "audio_data": None,
                    "chunk_index": 0,
                    "is_final": True,
                    "error": "TTS requires reference text. Please provide ref_text in request data.",
                }
                return

        chunk_index = 0
        # 对接 token 流与细粒度分块器：边收 LLM token 边切分，切出一段即送 TTS
        # 这是压缩首包延迟的核心：第一段 4 字即可触发 TTS，无需等整句
        async for text_segment in self.split_text_streaming(
            token_stream, char_threshold=char_threshold
        ):
            if not text_segment.strip():
                continue

            try:
                # 根据模式分发到对应 TTS 引擎（orpheus / embedded / triton / remote）
                if self._mode == "orpheus":
                    # Orpheus 模式：使用预设音色，文本（含 <laugh> 等情感标签）原样透传
                    # 不传 ref_audio_path / ref_text，由 Orpheus 模型按 voice 选择音色
                    voice = kwargs.get("voice", self._orpheus_voice)
                    audio_bytes = await self._synthesize_orpheus(
                        text_segment, voice=voice, **kwargs
                    )
                elif self._mode == "embedded":
                    from f5_tts.api import get_f5tts
                    if get_f5tts() is not None:
                        audio_bytes = await self._synthesize_embedded(
                            text_segment, audio_path, text_ref,
                            kwargs.get("speed", self._speed),
                            kwargs.get("cross_fade_duration", self._cross_fade_duration),
                            **kwargs
                        )
                    else:
                        audio_bytes = await self._make_tts_request(
                            gen_text=text_segment,
                            ref_text=text_ref,
                            audio_data=audio_data,
                            **kwargs
                        )
                elif self._use_triton and self._gateway_url:
                    audio_bytes = await self._synthesize_triton(
                        text_segment, audio_data, text_ref, **kwargs
                    )
                else:
                    audio_bytes = await self._make_tts_request(
                        gen_text=text_segment,
                        ref_text=text_ref,
                        audio_data=audio_data,
                        **kwargs
                    )

                chunk = {
                    "text_segment": text_segment,
                    "audio_data": audio_bytes,
                    "chunk_index": chunk_index,
                    # 流式无法预知是否最后一块，结束时单独发 final 标记
                    "is_final": False,
                }

                if on_chunk and audio_bytes:
                    on_chunk(text_segment, audio_bytes)

                yield chunk
                chunk_index += 1

            except Exception as e:
                logger.error(f"TTS fine stream error for chunk {chunk_index}: {e}")
                yield {
                    "text_segment": text_segment,
                    "audio_data": None,
                    "chunk_index": chunk_index,
                    "is_final": False,
                    "error": str(e),
                }
                chunk_index += 1

        # token 流结束，发送最终标记，通知下游音频流已完结
        yield {
            "text_segment": "",
            "audio_data": None,
            "chunk_index": chunk_index,
            "is_final": True,
        }

    async def synthesize_with_emotions(
        self,
        text: str,
        **kwargs
    ) -> bytes:
        segments = extract_emotions_with_text(text)

        if not segments:
            return await self.synthesize(text, **kwargs)

        audio_segments: list[bytes] = []
        current_emotion = "normal"

        for segment in segments:
            if segment["type"] == "emotion":
                current_emotion = segment["emotion"]
                continue

            if segment["type"] == "sleep":
                silence = self._generate_silence(segment["duration_ms"])
                audio_segments.append(silence)
                continue

            if segment["type"] == "text":
                text_segment = segment["content"]
                if not text_segment.strip():
                    continue

                voice_config = self.get_emotion_voice(current_emotion)
                ref_audio = voice_config.get("ref_audio", self._ref_audio_path)
                ref_text = voice_config.get("ref_text", self._ref_text)

                if not ref_audio:
                    ref_audio = self._ref_audio_path
                if not ref_text:
                    ref_text = self._ref_text

                if not ref_audio or not ref_text:
                    raise ValueError(
                        f"TTS requires reference audio and text for emotion '{current_emotion}'."
                    )

                audio_data = await self._load_emotion_audio(current_emotion)

                if self._mode == "embedded":
                    from f5_tts.api import get_f5tts
                    if get_f5tts() is not None:
                        seg_bytes = await self._synthesize_embedded(
                            text_segment, ref_audio, ref_text,
                            kwargs.get("speed", self._speed),
                            kwargs.get("cross_fade_duration", self._cross_fade_duration),
                            **kwargs
                        )
                        audio_segments.append(seg_bytes)
                        continue

                audio_segments.append(await self._make_tts_request(
                    gen_text=text_segment,
                    ref_text=ref_text,
                    audio_data=audio_data,
                    **kwargs
                ))

        if not audio_segments:
            return b""

        if len(audio_segments) == 1:
            return audio_segments[0]

        return await concatenate_audio(audio_segments)

    async def synthesize_stream_with_emotions(
        self,
        text: str,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        segments = parse_text_with_emotions(text)

        effect_segments = []
        for seg in segments:
            if seg["type"] == "text":
                effect_result = self._effect_parser.parse_text_with_effects(seg["content"])
                effect_segments.extend(effect_result)
            else:
                effect_segments.append(seg)

        segments = effect_segments

        if not segments:
            return

        chunk_index = 0
        current_emotion = "normal"

        for segment in segments:
            if segment["type"] == "emotion":
                current_emotion = segment["emotion"]
                continue

            if segment["type"] == "sound":
                effect_name = segment["name"]
                audio_data = self._load_effect_audio(effect_name)

                if audio_data:
                    chunk = {
                        "text_segment": f"（{effect_name}）",
                        "audio_data": audio_data,
                        "chunk_index": chunk_index,
                        "is_final": False,
                        "emotion": None,
                        "is_effect": True,
                        "effect_name": effect_name
                    }

                    if on_chunk:
                        on_chunk(f"（{effect_name}）", audio_data)

                    yield chunk
                    chunk_index += 1
                continue

            if segment["type"] == "sleep":
                silence = self._generate_silence(segment["duration_ms"])
                chunk = {
                    "text_segment": "",
                    "audio_data": silence,
                    "chunk_index": chunk_index,
                    "is_final": False,
                    "emotion": current_emotion,
                    "is_effect": False,
                    "is_sleep": True,
                    "sleep_duration_ms": segment["duration_ms"]
                }
                yield chunk
                chunk_index += 1
                continue

            if segment["type"] == "text":
                text_content = segment["content"]
                if not text_content.strip():
                    continue

                sentences = split_text_by_sentences(text_content)

                voice_config = self.get_emotion_voice(current_emotion)
                ref_text = voice_config.get("ref_text", self._ref_text)

                if not ref_text:
                    ref_text = self._ref_text

                if not ref_text:
                    yield {
                        "text_segment": text_content,
                        "audio_data": None,
                        "chunk_index": chunk_index,
                        "is_final": True,
                        "emotion": current_emotion,
                        "is_effect": False,
                        "error": "TTS requires reference text."
                    }
                    return

                try:
                    audio_data = await self._load_emotion_audio(current_emotion)
                except ValueError as e:
                    yield {
                        "text_segment": text_content,
                        "audio_data": None,
                        "chunk_index": chunk_index,
                        "is_final": True,
                        "emotion": current_emotion,
                        "is_effect": False,
                        "error": str(e)
                    }
                    return

                for sentence in sentences:
                    if not sentence.strip():
                        continue

                    try:
                        if self._mode == "embedded":
                            from f5_tts.api import get_f5tts
                            if get_f5tts() is not None:
                                voice_config = self.get_emotion_voice(current_emotion)
                                ref_audio_path = voice_config.get("ref_audio", self._ref_audio_path)
                                audio_bytes = await self._synthesize_embedded(
                                    sentence, ref_audio_path, ref_text,
                                    kwargs.get("speed", self._speed),
                                    kwargs.get("cross_fade_duration", self._cross_fade_duration),
                                    **kwargs
                                )
                                chunk = {
                                    "text_segment": sentence,
                                    "audio_data": audio_bytes,
                                    "chunk_index": chunk_index,
                                    "is_final": False,
                                    "emotion": current_emotion,
                                    "is_effect": False
                                }
                                if on_chunk and audio_bytes:
                                    on_chunk(sentence, audio_bytes)
                                yield chunk
                                chunk_index += 1
                                continue

                        audio_bytes = await self._make_tts_request(
                            gen_text=sentence,
                            ref_text=ref_text,
                            audio_data=audio_data,
                            **kwargs
                        )

                        chunk = {
                            "text_segment": sentence,
                            "audio_data": audio_bytes,
                            "chunk_index": chunk_index,
                            "is_final": False,
                            "emotion": current_emotion,
                            "is_effect": False
                        }

                        if on_chunk and audio_bytes:
                            on_chunk(sentence, audio_bytes)

                        yield chunk
                        chunk_index += 1

                    except Exception as e:
                        logger.error(f"TTS stream error for sentence: {e}")
                        yield {
                            "text_segment": sentence,
                            "audio_data": None,
                            "chunk_index": chunk_index,
                            "is_final": False,
                            "emotion": current_emotion,
                            "is_effect": False,
                            "error": str(e)
                        }
                        chunk_index += 1

        yield {
            "text_segment": "",
            "audio_data": None,
            "chunk_index": chunk_index,
            "is_final": True,
            "emotion": current_emotion,
            "is_effect": False
        }

    async def get_voices(self) -> list[dict[str, Any]]:
        return [{"id": "default", "name": "Default Voice"}]

    def get_emotion_voice(self, emotion: str) -> dict[str, str]:
        if emotion in self._emotion_voices:
            return self._emotion_voices[emotion]
        if "normal" in self._emotion_voices:
            return self._emotion_voices["normal"]
        return {
            "ref_audio": self._ref_audio_path,
            "ref_text": self._ref_text
        }

    async def _load_emotion_audio(self, emotion: str) -> bytes:
        if emotion in self._emotion_audio_cache:
            return self._emotion_audio_cache[emotion]

        voice_config = self.get_emotion_voice(emotion)
        ref_audio = voice_config.get("ref_audio", "")

        if not ref_audio:
            return await self._load_ref_audio()

        audio_path = self._resolve_audio_path(ref_audio)

        if not audio_path or not audio_path.exists():
            logger.warning(f"Emotion audio file not found: {ref_audio}, using default")
            return await self._load_ref_audio()

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        self._emotion_audio_cache[emotion] = audio_data
        return audio_data

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


def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        from server.config import get_settings
        settings = get_settings()
        _tts_service = TTSService(
            mode=settings.tts.mode,
            model_dir=settings.tts.model_dir,
            device=settings.tts.device,
            remote_url=settings.tts.remote_url,
            ref_audio_path=settings.tts.ref_audio_path,
            ref_text=settings.tts.ref_text,
            speed=settings.tts.speed,
            cross_fade_duration=settings.tts.cross_fade_duration,
            emotion_voices=_load_emotion_voices(settings.tts.emotion_refs_dir) if settings.tts.emotion_enabled else {},
            effects_dir=settings.tts.transitions_dir if settings.tts.effects_enabled else None,
            voice_refs_dir=settings.tts.emotion_refs_dir if settings.tts.emotion_enabled else None,
            gateway_url=settings.tts.remote_url,
            use_triton=(settings.tts.mode == "triton"),
            # Orpheus 配置：从 settings.tts.orpheus 读取（mode == "orpheus" 时生效，
            # 其他模式下 orpheus 参数被忽略，保持向后兼容）
            orpheus_url=settings.tts.orpheus.url,
            orpheus_voice=settings.tts.orpheus.voice,
            orpheus_timeout=settings.tts.orpheus.timeout,
        )
    return _tts_service
