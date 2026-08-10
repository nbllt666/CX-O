"""
统一 ASR 服务
支持 embedded（直接调用 SenseVoice 模型）和 remote（HTTP 调用）两种模式
合并了原 ASRClient 的 base64/文件识别功能
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import websockets
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Optional


from server.core.utils import get_shared_http_client, retry_with_backoff

logger = logging.getLogger(__name__)

TARGET_FS = 16000
regex = r"<\|.*\|>"

_model_instance = None
_model_kwargs = None
_executor: Optional[ThreadPoolExecutor] = None


class ASRService:
    def __init__(self, mode: str = "remote", model_dir: str = "", device: str = "cuda",
                 remote_url: str = "http://127.0.0.1:8001",
                 ws_url: str = "ws://127.0.0.1:8005/ws/asr/stream"):
        self._mode = mode
        self._model_dir = model_dir
        self._device = device
        self._remote_url = remote_url
        self._ws_url = ws_url
        self._initialized = False
        # Streaming 接口状态（vad_processor.AudioStreamProcessor 调用）
        # 方案B：WebSocket 流式接口
        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._ws_lock: asyncio.Lock = asyncio.Lock()
        self._ws_recv_queue: asyncio.Queue = asyncio.Queue()
        self._ws_recv_task: Optional[asyncio.Task] = None
        self._ws_final_received: bool = False  # 是否已收到 final 结果（避免 final 后继续读 queue）

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self):
        global _model_instance, _model_kwargs, _executor
        if self._mode != "embedded":
            logger.info(f"ASR service in remote mode, target: {self._remote_url}")
            self._initialized = True
            return

        if _model_instance is not None:
            self._initialized = True
            return

        logger.info(f"Loading SenseVoice model: {self._model_dir} on device: {self._device}")
        _executor = ThreadPoolExecutor(max_workers=2)

        try:
            from sensevoice.model import SenseVoiceSmall
            _model_instance, _model_kwargs = SenseVoiceSmall.from_pretrained(
                model=self._model_dir,
                device=self._device
            )
            _model_instance.eval()
            self._initialized = True
            logger.info("SenseVoice model loaded successfully in embedded mode")
        except Exception as e:
            error_msg = f"Failed to load SenseVoice model in embedded mode: {e}"
            logger.error(error_msg)
            
            logger.warning("Attempting to fallback to remote ASR mode...")
            try:
                if _executor:
                    _executor.shutdown(wait=False)
                    _executor = None
                
                self._mode = "remote"
                self._initialized = True
                logger.info(f"ASR service successfully switched to remote mode: {self._remote_url}")
            except Exception as fallback_error:
                logger.error(f"Failed to fallback to remote ASR mode: {fallback_error}")
                raise RuntimeError(f"ASR service initialization failed: {error_msg}. Fallback to remote mode also failed: {fallback_error}")

    async def shutdown(self):
        global _model_instance, _model_kwargs, _executor
        if _executor:
            _executor.shutdown(wait=False)
            _executor = None
        _model_instance = None
        _model_kwargs = None
        self._initialized = False

    async def recognize(self, audio_data: bytes, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        if self._mode == "embedded" and _model_instance is not None:
            return await self._recognize_embedded(audio_data, language, use_itn)
        else:
            return await self._recognize_remote(audio_data, language, use_itn)

    async def recognize_base64(self, audio_base64: str, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        if self._mode == "embedded" and _model_instance is not None:
            audio_data = base64.b64decode(audio_base64)
            return await self._recognize_embedded(audio_data, language, use_itn)
        else:
            return await self._recognize_remote_base64(audio_base64, language, use_itn)

    async def recognize_file(self, file_path: str | Path, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        with open(path, "rb") as f:
            audio_data = f.read()

        return await self.recognize(audio_data, language, use_itn)

    async def _recognize_embedded(self, audio_data: bytes, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        audio_tensor, success = self._process_audio(BytesIO(audio_data))
        if not success:
            return {"text": "", "error": "Failed to process audio"}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            self._run_inference,
            [audio_tensor],
            language,
            use_itn
        )
        return result

    async def _recognize_remote(self, audio_data: bytes, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        async def _make_request():
            import time as _diag_time
            _t0 = _diag_time.monotonic()
            client = get_shared_http_client()
            _t1 = _diag_time.monotonic()
            files = {"file": ("audio.wav", audio_data, "audio/wav")}
            data = {"language": language, "use_itn": str(use_itn), "task": "rich"}
            _t2 = _diag_time.monotonic()
            response = await client.post(f"{self._remote_url}/api/v1/asr", files=files, data=data)
            _t3 = _diag_time.monotonic()
            logger.info(f"[DIAG-ASR] get_client={(_t1-_t0)*1000:.1f}ms prep={(_t2-_t1)*1000:.1f}ms post={(_t3-_t2)*1000:.1f}ms url={self._remote_url}")
            if response.status_code == 200:
                result = response.json()
                if result.get("results"):
                    return {
                        "text": result["results"][0].get("text", ""),
                        "language": result["results"][0].get("language", ""),
                        "emotion": result["results"][0].get("emotion", ""),
                        "event": result["results"][0].get("event", ""),
                    }
            return {"text": "", "error": f"ASR remote error: HTTP {response.status_code}"}
        
        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="ASR")

    async def _recognize_remote_base64(self, audio_base64: str, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        async def _make_request():
            client = get_shared_http_client()
            response = await client.post(
                f"{self._remote_url}/asr",
                json={
                    "audio": audio_base64,
                    "language": language
                }
            )
            response.raise_for_status()
            return response.json()

        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="ASR")

    def _process_audio(self, file_io: BytesIO) -> tuple:
        try:
            import torch
            import torchaudio
            import numpy as np
            from scipy.io import wavfile
            from scipy import signal as scipy_signal

            file_io.seek(0)
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(file_io.read())
                tmp_path = tmp.name

            try:
                sr, data = wavfile.read(tmp_path)
                if data.dtype == np.int16:
                    audio_data = data.astype(np.float32) / 32768.0
                else:
                    audio_data = data.astype(np.float32)

                if audio_data.ndim > 1:
                    audio_data = audio_data.mean(axis=1)

                if sr != TARGET_FS:
                    num_samples = int(len(audio_data) * TARGET_FS / sr)
                    audio_data = scipy_signal.resample(audio_data, num_samples)

                return torch.from_numpy(audio_data), True
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            try:
                import torch
                import torchaudio
                file_io.seek(0)
                data_or_path, audio_fs = torchaudio.load(file_io)
                if audio_fs != TARGET_FS:
                    resampler = torchaudio.transforms.Resample(orig_freq=audio_fs, new_freq=TARGET_FS)
                    data_or_path = resampler(data_or_path)
                if data_or_path.dim() > 1:
                    data_or_path = data_or_path.mean(0)
                return data_or_path, True
            except Exception as e2:
                logger.error(f"Error processing audio fallback: {e2}")
                return None, False

    def _run_inference(self, audios: list, lang: str, use_itn: bool) -> dict[str, Any]:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        key = [f"audio_{i}" for i in range(len(audios))]
        res = _model_instance.inference(
            data_in=audios,
            language=lang,
            use_itn=use_itn,
            key=key,
            fs=TARGET_FS,
            **_model_kwargs,
        )

        if len(res) > 0 and len(res[0]) > 0:
            item = res[0][0]
            raw_text = item.get("text", "")
            clean_text = re.sub(regex, "", raw_text, count=0, flags=re.MULTILINE)
            text = rich_transcription_postprocess(raw_text) if use_itn else clean_text

            lang_match = re.search(r"<\|(\w+)\|>", raw_text)
            emo_match = re.search(r"<\|(HAPPY|SAD|ANGRY|NEUTRAL|FEARFUL|DISGUSTED|SURPRISED)\|>", raw_text)
            event_match = re.search(r"<\|(BGM|Speech|Applause|Laughter|Cry|Sneeze|Breath|Cough|Sing|Speech_Noise)\|>", raw_text)

            return {
                "text": text,
                "language": lang_match.group(1) if lang_match else "",
                "emotion": emo_match.group(1) if emo_match else "",
                "event": event_match.group(1) if event_match else "",
            }
        return {"text": "", "language": "", "emotion": "", "event": ""}

    # ------------------------------------------------------------------ #
    # Streaming 接口（vad_processor.AudioStreamProcessor 调用契约）
    # ------------------------------------------------------------------ #
    # 方案B：WebSocket 流式接口
    # - send_audio_chunk: 通过 WS 发送二进制 PCM 音频；is_last=True 发送 {"action":"final"}
    # - receive_result: 非阻塞从 queue 读取服务端返回的 JSON，解析为 StreamingASRResult
    # - reset: 清空本地 queue（服务端 final 后自动清空 buffer）
    # - 懒加载 WS 连接，后台接收任务把消息放入 queue
    # ------------------------------------------------------------------ #

    async def _ensure_ws(self) -> bool:
        """懒加载 WebSocket 连接，启动后台接收任务。"""
        if self._ws is not None:
            return True
        async with self._ws_lock:
            if self._ws is not None:
                return True
            try:
                logger.info(f"[ASR-WS] Connecting to {self._ws_url}")
                self._ws = await websockets.connect(
                    self._ws_url,
                    max_size=None,  # 不限制单帧大小（音频 chunk 可能大）
                    ping_interval=20,
                    ping_timeout=10,
                )
                # 启动后台接收任务
                self._ws_recv_task = asyncio.create_task(self._ws_recv_loop())
                logger.info("[ASR-WS] Connected, recv task started")
                return True
            except Exception as e:
                logger.error(f"[ASR-WS] Connect failed: {e}")
                self._ws = None
                return False

    async def _ws_recv_loop(self) -> None:
        """后台接收 WS 消息，放入 queue。连接断开时清理状态。"""
        _n = 0
        try:
            async for message in self._ws:
                _n += 1
                logger.info(f"[ASR-WS] Recv #{_n}: {str(message)[:80]}")
                await self._ws_recv_queue.put(message)
        except Exception as e:
            logger.error(f"[ASR-WS] Recv loop error: {e}")
        finally:
            self._ws = None
            logger.info(f"[ASR-WS] Recv loop ended (total {_n} msgs), ws cleared")

    async def send_audio_chunk(self, audio_data: bytes, is_last: bool = False) -> bool:
        """通过 WebSocket 发送音频 chunk。

        Args:
            audio_data: PCM 16kHz mono int16 LE 音频字节
            is_last: 是否为最后一帧（VAD speech_end 触发）

        Returns:
            True 表示成功发送，False 表示服务未就绪或发送失败
        """
        if not self._initialized:
            logger.warning("ASRService not initialized, skip send_audio_chunk")
            return False
        if not await self._ensure_ws():
            return False
        try:
            # 发送二进制音频
            await self._ws.send(audio_data)
            if is_last:
                # 发送 final 信号，触发服务端识别剩余 buffer
                await self._ws.send(json.dumps({"action": "final"}))
        except Exception as e:
            logger.error(f"[ASR-WS] Send error: {e}")
            self._ws = None
            return False
        return True

    async def receive_result(self, timeout: float = 0.1) -> Optional["StreamingASRResult"]:
        """从 WebSocket 接收识别结果。

        双流式模式契约：
        - 语音期间（is_last=False）：返回 Partial 结果（is_final=False），
          vad_processor.AudioStreamProcessor 据此触发 on_partial_result → LLM Speculative Prefill
        - 语音结束（is_last=True，VAD speech_end 触发）：返回 Final 结果（is_final=True），
          handler 据此调用 on_vad_speech_end 修正上下文

        Args:
            timeout: 等待超时（秒），超时返回 None

        Returns:
            StreamingASRResult 或 None（无消息时）
        """
        if self._ws is None and self._ws_recv_queue.empty():
            return None
        # timeout=0 必须走 get_nowait() 同步路径：
        # Python 3.12+ asyncio.wait_for 对 timeout<=0 有快速路径——
        # ensure_future 后任务尚未运行即判定 not done 并直接取消，
        # 导致 wait_for(get(), timeout=0) 永远 TimeoutError（即使队列非空），
        # ASR 结果全部积压丢失（2026-08-05 实测复现，端到端延迟暴涨根因）。
        if timeout == 0:
            try:
                message = self._ws_recv_queue.get_nowait()
                logger.info(f"[ASR-WS] receive_result GOT: {str(message)[:60]} (qsize={self._ws_recv_queue.qsize()})")
            except asyncio.QueueEmpty:
                return None
        else:
            try:
                message = await asyncio.wait_for(
                    self._ws_recv_queue.get(), timeout=timeout
                )
            except asyncio.TimeoutError:
                return None

        if isinstance(message, bytes):
            # 忽略二进制消息（服务端只发 JSON 文本）
            return None
        try:
            data = json.loads(message)
            text = data.get("text", "")
            is_final = data.get("is_final", False)
            if is_final:
                self._ws_final_received = True
            return StreamingASRResult(
                text=text,
                clean_text=text,
                language=data.get("language", ""),
                is_final=is_final,
                emotion=data.get("emotion", ""),
            )
        except Exception as e:
            logger.error(f"[ASR-WS] Parse result error: {e}, raw={message[:200]}")
            return None

    async def reset(self) -> None:
        """清空 streaming 状态（vad_processor 在 is_last 后调用）。

        不发送 reset 信号给服务端——服务端在 final 后自动清空 buffer。
        只清空本地 queue，准备下一轮语音。
        """
        # 清空 queue
        while not self._ws_recv_queue.empty():
            try:
                self._ws_recv_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._ws_final_received = False
        # 不关闭 WS 连接，复用给下一轮


class StreamingASRResult:
    """Streaming ASR 结果数据类（vad_processor.AudioStreamProcessor 期望的契约）。"""

    def __init__(
        self,
        text: str = "",
        clean_text: str = "",
        language: str = "",
        is_final: bool = False,
        emotion: str = "",
    ):
        self.text = text
        self.clean_text = clean_text
        self.language = language
        self.is_final = is_final
        self.emotion = emotion


_asr_service: Optional[ASRService] = None


def get_asr_service() -> ASRService:
    global _asr_service
    if _asr_service is None:
        from server.config import get_settings
        settings = get_settings()
        _asr_service = ASRService(
            mode=settings.asr.mode,
            model_dir=settings.asr.model_dir,
            device=settings.asr.device,
            remote_url=settings.asr.remote_url,
            ws_url=settings.asr.ws_url,
        )
    return _asr_service
