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


from server.core.utils import (
    get_shared_http_client,
    make_bounded_queue,
    retry_with_backoff,
)

logger = logging.getLogger(__name__)

TARGET_FS = 16000
regex = r"<\|.*?\|>"


def _safe_float(value: Any, default: float = 0.0) -> float:
    """数值/字符串安全解析为 float；None、空串或非法值（如 "abc"）返回 default。

    避免 `float(None)` / `float("")` 对非法 speaker_conf 抛异常导致整条结果被吞。
    """
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    """布尔安全解析：bool 原样；'true'/'1'/'yes'（不区分大小写）→ True；其余（含 None/''）→ False。

    避免 `bool("false")==True` 语义错误的 speaker_registered。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("true", "1", "yes")

_model_instance = None
_model_kwargs = None
_executor: Optional[ThreadPoolExecutor] = None


def _asr_infer_workers() -> int:
    """读取 ASR embedded 推理线程池大小（默认 2，与现状一致；允许配置放大）。

    配置读取失败时回退默认 2，保证零侵入（不破坏既有测试与生产默认）。
    """
    try:
        from server.config import get_settings as _gs
        w = int(_gs().config.executor.asr_infer_workers or 2)
        return w if w > 0 else 2
    except Exception:  # noqa: BLE001 - 配置缺失/加载失败回退默认
        return 2


def _asr_recv_queue_maxsize() -> int:
    """读取 ASR WS 接收队列有界上限（默认 0=无界，与现状一致；>0 启用背压）。"""
    try:
        from server.config import get_settings as _gs
        v = int(_gs().config.executor.asr_recv_queue_maxsize or 0)
        return v if v > 0 else 0
    except Exception:  # noqa: BLE001 - 配置缺失/加载失败回退无界
        return 0


class _StreamState:
    """Per-client 流式会话状态。

    每个客户端持有一条独立的 ASR WebSocket 连接 / 锁 / 接收队列 / 后台接收任务 /
    final 标记，使并发会话各自上行、各自收结果，互不串扰。
    """

    __slots__ = ("ws", "lock", "recv_queue", "recv_task", "final_received",
                 "recent_speaker", "recent_spk_embedding")

    def __init__(self):
        self.ws: Any = None  # websockets.WebSocketClientProtocol
        self.lock: asyncio.Lock = asyncio.Lock()
        # 有界队列（配置 asr_recv_queue_maxsize>0 时启用背压；默认 0=无界，与现状一致）
        self.recv_queue: asyncio.Queue = make_bounded_queue(_asr_recv_queue_maxsize())
        self.recv_task: Optional[asyncio.Task] = None
        self.final_received: bool = False
        self.recent_speaker: tuple = ()
        self.recent_spk_embedding: Optional[list] = None


class _StreamAccessor:
    """统一读写默认（self 属性）或 per-client（_StreamState）的流式状态。

    默认路径（client_id 为 None）沿用 ASRService 上的 _ws/_ws_lock/... 属性，
    保持既有调用点与单会话测试向后兼容；per-client 路径读写独立的 _StreamState。
    """

    def __init__(self, svc: "ASRService", state: Optional[_StreamState]):
        self._svc = svc
        self._state = state

    @property
    def ws(self):
        return self._svc._ws if self._state is None else self._state.ws

    @ws.setter
    def ws(self, value):
        if self._state is None:
            self._svc._ws = value
        else:
            self._state.ws = value

    @property
    def lock(self):
        return self._svc._ws_lock if self._state is None else self._state.lock

    @property
    def recv_queue(self):
        return self._svc._ws_recv_queue if self._state is None else self._state.recv_queue

    @recv_queue.setter
    def recv_queue(self, value):
        if self._state is None:
            self._svc._ws_recv_queue = value
        else:
            self._state.recv_queue = value

    @property
    def recv_task(self):
        return self._svc._ws_recv_task if self._state is None else self._state.recv_task

    @recv_task.setter
    def recv_task(self, value):
        if self._state is None:
            self._svc._ws_recv_task = value
        else:
            self._state.recv_task = value

    @property
    def final_received(self):
        return self._svc._ws_final_received if self._state is None else self._state.final_received

    @final_received.setter
    def final_received(self, value):
        if self._state is None:
            self._svc._ws_final_received = value
        else:
            self._state.final_received = value

    @property
    def recent_speaker(self):
        return self._svc._recent_speaker if self._state is None else self._state.recent_speaker

    @recent_speaker.setter
    def recent_speaker(self, value):
        if self._state is None:
            self._svc._recent_speaker = value
        else:
            self._state.recent_speaker = value

    @property
    def recent_spk_embedding(self):
        return self._svc._recent_spk_embedding if self._state is None else self._state.recent_spk_embedding

    @recent_spk_embedding.setter
    def recent_spk_embedding(self, value):
        if self._state is None:
            self._svc._recent_spk_embedding = value
        else:
            self._state.recent_spk_embedding = value


class ASRService:
    """统一 ASR 服务，支持 embedded 与 remote 两种识别模式，并提供 WebSocket 流式识别接口。

    流式识别支持 per-client 并发：带 client_id 的调用建立/复用独立的
    ASR WebSocket 连接与接收队列，并发会话各自上行、各自收结果。
    """

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
        self._ws: Any = None  # websockets.WebSocketClientProtocol（默认会话向后兼容）
        self._ws_lock: asyncio.Lock = asyncio.Lock()
        self._ws_recv_queue: asyncio.Queue = make_bounded_queue(_asr_recv_queue_maxsize())
        self._ws_recv_task: Optional[asyncio.Task] = None
        self._ws_final_received: bool = False  # 是否已收到 final 结果（避免 final 后继续读 queue）
        # 默认会话最近说话人状态（spk 补充消息 / final 回填）
        self._recent_speaker: tuple = ()
        self._recent_spk_embedding: Optional[list] = None
        # per-client 流式会话注册表（client_id -> _StreamState）
        self._stream_sessions: dict = {}

    def _stream_accessor(self, client_id: Optional[str]) -> "_StreamAccessor":
        """按 client_id 解析流式会话访问器。client_id 为 None 时返回默认会话访问器。"""
        if client_id is None:
            return _StreamAccessor(self, None)
        if client_id not in self._stream_sessions:
            self._stream_sessions[client_id] = _StreamState()
        return _StreamAccessor(self, self._stream_sessions[client_id])

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
        _executor = ThreadPoolExecutor(max_workers=_asr_infer_workers())

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

        loop = asyncio.get_running_loop()
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
            _diag = logger.isEnabledFor(logging.DEBUG)
            if _diag:
                import time as _diag_time
                _t0 = _diag_time.monotonic()
            client = get_shared_http_client()
            if _diag:
                _t1 = _diag_time.monotonic()
            files = {"file": ("audio.wav", audio_data, "audio/wav")}
            data = {"language": language, "use_itn": str(use_itn), "task": "rich"}
            if _diag:
                _t2 = _diag_time.monotonic()
            response = await client.post(f"{self._remote_url}/api/v1/asr", files=files, data=data)
            if _diag:
                _t3 = _diag_time.monotonic()
                logger.debug(f"[DIAG-ASR] get_client={(_t1-_t0)*1000:.1f}ms prep={(_t2-_t1)*1000:.1f}ms post={(_t3-_t2)*1000:.1f}ms url={self._remote_url}")
            if response.status_code == 200:
                result = response.json()
                if result.get("results"):
                    return {
                        "text": result["results"][0].get("text", ""),
                        "language": result["results"][0].get("language", ""),
                        "emotion": result["results"][0].get("emotion", ""),
                        "event": result["results"][0].get("event", ""),
                    }
            # E1: 5xx 属临时故障，raise 使 retry_with_backoff 重试（旧实现裸返回
            # 错误 dict，5xx 永不重试）；4xx 为客户端错误，返回错误结果不重试。
            if response.status_code >= 500:
                response.raise_for_status()
            return {"text": "", "error": f"ASR remote error: HTTP {response.status_code}"}
        
        try:
            return await retry_with_backoff(
                _make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="ASR"
            )
        except Exception as exc:
            # E1: 5xx 触发重试；重试耗尽后仍失败时降级为错误 dict（不向调用方
            # 抛裸异常），维持调用方统一的「空文本 + error」契约（test 同款断言）。
            logger.warning("ASR remote 请求重试后仍失败: %s", exc)
            return {"text": "", "error": f"ASR remote error after retries: {exc}"}

    async def _recognize_remote_base64(self, audio_base64: str, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        async def _make_request():
            client = get_shared_http_client()
            response = await client.post(
                f"{self._remote_url}/asr/recognize",
                json={
                    "audio": audio_base64,
                    "language": language,
                    "use_itn": use_itn,
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

    async def _ensure_ws(self, client_id: Optional[str] = None) -> bool:
        """懒加载 WebSocket 连接，启动后台接收任务。

        client_id: 指定客户端会话；None 表示默认会话（向后兼容）。
        """
        st = self._stream_accessor(client_id)
        if st.ws is not None:
            return True
        async with st.lock:
            if st.ws is not None:
                return True
            try:
                logger.info(f"[ASR-WS] Connecting to {self._ws_url} (client={client_id})")
                ws = await websockets.connect(
                    self._ws_url,
                    max_size=None,  # 不限制单帧大小（音频 chunk 可能大）
                    ping_interval=20,
                    ping_timeout=10,
                )
                st.ws = ws
                # 启动后台接收任务
                st.recv_task = asyncio.create_task(self._ws_recv_loop(st))
                logger.info("[ASR-WS] Connected, recv task started (client=%s)", client_id)
                return True
            except Exception as e:
                logger.error(f"[ASR-WS] Connect failed: {e}")
                st.ws = None
                return False

    async def _ws_recv_loop(self, st: "_StreamAccessor") -> None:
        """后台接收 WS 消息，放入 queue。连接断开时清理状态。"""
        _n = 0
        _debug = logger.isEnabledFor(logging.DEBUG)
        try:
            async for message in st.ws:
                _n += 1
                # isEnabledFor 门控：避免每帧对 str(message)[:80] 急切求值（含 JSON 字符串切片）。
                # 仅在实际触发 DEBUG 时才做 % 拼接与切片，消除热路径无谓开销。
                if _debug:
                    logger.debug("[ASR-WS] Recv #%d: %s", _n, str(message)[:80])
                await st.recv_queue.put(message)
        except Exception as e:
            logger.error(f"[ASR-WS] Recv loop error: {e}")
        finally:
            st.ws = None
            logger.info(f"[ASR-WS] Recv loop ended (total {_n} msgs), ws cleared")

    async def send_audio_chunk(self, audio_data: bytes, is_last: bool = False,
                               client_id: Optional[str] = None) -> bool:
        """通过 WebSocket 发送音频 chunk。

        Args:
            audio_data: PCM 16kHz mono int16 LE 音频字节
            is_last: 是否为最后一帧（VAD speech_end 触发）
            client_id: 所属客户端。None 走默认会话（向后兼容）；指定则走该客户端
            独立流式连接，并发会话各自上行不串扰。

        Returns:
            True 表示成功发送，False 表示服务未就绪或发送失败
        """
        if not self._initialized:
            logger.warning("ASRService not initialized, skip send_audio_chunk")
            return False
        st = self._stream_accessor(client_id)
        if not await self._ensure_ws(client_id):
            return False
        try:
            # 发送二进制音频
            await st.ws.send(audio_data)
            if is_last:
                # 发送 final 信号，触发服务端识别剩余 buffer
                await st.ws.send(json.dumps({"action": "final"}))
        except Exception as e:
            logger.error(f"[ASR-WS] Send error: {e}")
            # 发送失败：清理该 client 的流式会话（复用 release_streaming_session
            # 的清理逻辑），取消并等待收包 recv_task、置空 ws、关闭旧连接，
            # 避免孤儿连接与存活 recv task 累积，下次 _ensure_ws 可重建干净连接。
            try:
                task = st.recv_task
                if task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                old_ws = st.ws
                st.ws = None
                if old_ws is not None:
                    try:
                        await old_ws.close()
                    except Exception as err:
                        logger.debug("[ASR-WS] close error on send failure: %s", err)
                # 同步排空 recv_queue 并复位 final_received（复用 reset() 的排空逻辑）：
                # 否则重连复用同一队列会读到旧连接残留结果，且 final_received 保持 True
                # 会跳过 final 状态判定，导致下一轮语音结果被误判
                while not st.recv_queue.empty():
                    try:
                        st.recv_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                st.final_received = False
            except Exception as cleanup_e:
                logger.warning(f"[ASR-WS] Cleanup after send error failed: {cleanup_e}")
            return False
        return True

    async def receive_result(self, timeout: float = 0.1,
                             client_id: Optional[str] = None) -> Optional["StreamingASRResult"]:
        """从 WebSocket 接收识别结果。

        双流式模式契约：
        - 语音期间（is_last=False）：返回 Partial 结果（is_final=False），
          vad_processor.AudioStreamProcessor 据此触发 on_partial_result → LLM Speculative Prefill
        - 语音结束（is_last=True，VAD speech_end 触发）：返回 Final 结果（is_final=True），
          handler 据此调用 on_vad_speech_end 修正上下文

        Args:
            timeout: 等待超时（秒），超时返回 None
            client_id: 所属客户端。None 走默认会话队列（向后兼容）；
            指定则从该客户端独立接收队列取结果，并发会话互不混插。

        Returns:
            StreamingASRResult 或 None（无消息时）
        """
        st = self._stream_accessor(client_id)
        if st.ws is None and st.recv_queue.empty():
            return None
        # timeout=0 必须走 get_nowait() 同步路径：
        # Python 3.12+ asyncio.wait_for 对 timeout<=0 有快速路径——
        # ensure_future 后任务尚未运行即判定 not done 并直接取消，
        # 导致 wait_for(get(), timeout=0) 永远 TimeoutError（即使队列非空），
        # ASR 结果全部积压丢失（2026-08-05 实测复现，端到端延迟暴涨根因）。
        if timeout == 0:
            try:
                message = st.recv_queue.get_nowait()
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("[ASR-WS] receive_result GOT: %s (qsize=%d)", str(message)[:60], st.recv_queue.qsize())
            except asyncio.QueueEmpty:
                return None
        else:
            try:
                message = await asyncio.wait_for(
                    st.recv_queue.get(), timeout=timeout
                )
            except asyncio.TimeoutError:
                return None

        if isinstance(message, bytes):
            # 忽略二进制消息（服务端只发 JSON 文本）
            return None
        try:
            data = json.loads(message)
            # spk 补充消息：无文本，仅带回 speaker 声纹元信息（含 embedding），
            # 回填会话最近说话人状态后直接返回，不再走普通结果解析。
            if data.get("type") == "spk":
                speaker_id = data.get("speaker_id", "") or ""
                speaker_registered = _safe_bool(data.get("speaker_registered"))
                speaker_conf = _safe_float(data.get("speaker_conf"))
                speaker_name = data.get("speaker_name") or (speaker_id if speaker_registered else "")
                # 回填会话状态
                st.recent_speaker = (speaker_id, speaker_registered, speaker_conf)
                emb = data.get("em_embedding")
                if isinstance(emb, list) and emb:
                    st.recent_spk_embedding = [float(x) for x in emb]
                return StreamingASRResult(
                    text="", clean_text="", language=data.get("language", ""),
                    is_final=False, emotion=data.get("emotion", ""),
                    speaker_status="ready", speaker_id=speaker_id, speaker_name=speaker_name,
                    speaker_registered=speaker_registered, speaker_conf=speaker_conf,
                )
            text = data.get("text", "")
            is_final = data.get("is_final", False)
            if is_final:
                st.final_received = True
            speaker_status = data.get("speaker_status", "ready")
            # 声纹字段解析（兼容旧容器缺字段）：缺失时取默认值/空串
            speaker_id = data.get("speaker_id", "") or ""
            speaker_registered = _safe_bool(data.get("speaker_registered"))
            speaker_conf = _safe_float(data.get("speaker_conf"))
            speaker_name = data.get("speaker_name") or (speaker_id if speaker_registered else "")
            # final 回填最近说话人：仅当本句含非空 speaker_id 且状态为 ready 时更新
            if is_final and speaker_id and speaker_status == "ready":
                st.recent_speaker = (speaker_id, speaker_registered, speaker_conf)
            return StreamingASRResult(
                text=text,
                clean_text=text,
                language=data.get("language", ""),
                is_final=is_final,
                emotion=data.get("emotion", ""),
                speaker_status=speaker_status,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                speaker_registered=speaker_registered,
                speaker_conf=speaker_conf,
            )
        except Exception as e:
            logger.error(f"[ASR-WS] Parse result error: {e}, raw={message[:200]}")
            return None

    async def reset(self, client_id: Optional[str] = None) -> None:
        """清空 streaming 状态（vad_processor 在 is_last 后调用）。

        不发送 reset 信号给服务端——服务端在 final 后自动清空 buffer。
        只清空本地 queue，准备下一轮语音。

        client_id: 指定客户端会话；None 表示默认会话（向后兼容）。
        """
        st = self._stream_accessor(client_id)
        # 清空 queue
        while not st.recv_queue.empty():
            try:
                st.recv_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        st.final_received = False
        # 不关闭 WS 连接，复用给下一轮

    async def release_streaming_session(self, client_id: str) -> None:
        """释放指定客户端的流式会话：关闭其 ASR WS 连接并取消后台接收任务。

        仅在客户端断开/会话结束时调用，不影响其它客户端会话。
        """
        state = self._stream_sessions.pop(client_id, None)
        if state is None:
            return
        task = state.recv_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        ws = state.ws
        state.ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception as e:
                logger.debug("[ASR-WS] close error for %s: %s", client_id, e)


class StreamingASRResult:
    """Streaming ASR 结果数据类（vad_processor.AudioStreamProcessor 期望的契约）。"""

    def __init__(
        self,
        text: str = "",
        clean_text: str = "",
        language: str = "",
        is_final: bool = False,
        emotion: str = "",
        speaker_id: str = "",
        speaker_name: str = "",
        speaker_registered: bool = False,
        speaker_conf: float = 0.0,
        speaker_status: str = "ready",
    ):
        self.text = text
        self.clean_text = clean_text
        self.language = language
        self.is_final = is_final
        self.emotion = emotion
        # 声纹识别字段（Task 4）：说话人标识/姓名/是否已注册/相似度置信度
        self.speaker_id = speaker_id
        self.speaker_name = speaker_name
        self.speaker_registered = speaker_registered
        self.speaker_conf = speaker_conf
        # 声纹注册状态：pending=待注册确认 / ready=已就绪（spk 补充消息恒为 ready）
        self.speaker_status = speaker_status


_asr_service: Optional[ASRService] = None


def get_asr_service() -> ASRService:
    """获取全局唯一的 ASRService 单例，按配置惰性初始化。"""

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


def get_recent_spk_embedding(client_id: Optional[str] = None) -> Optional[list]:
    """返回指定客户端最近收到的 spk 补充消息中的说话人 embedding（192 float 列表）。

    client_id 为 None 时读取默认会话的最近 embedding；未收到过 spk 补充消息时返回 None。
    """
    svc = get_asr_service()
    st = svc._stream_accessor(client_id)
    return st.recent_spk_embedding
