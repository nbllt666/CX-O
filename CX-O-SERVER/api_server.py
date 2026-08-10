"""
ASR SenseVoice API Server
基于 FunASR 的 SenseVoice 语音识别 HTTP + WebSocket API
"""
import asyncio
import base64
import io
import json
import logging
import re
import struct
import tempfile
import wave
from pathlib import Path
from typing import Optional, List

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from pydantic import BaseModel

# 导入 SenseVoice 模型
from funasr import AutoModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ASR SenseVoice Service")

# 全局模型实例
_model = None
_kwargs = {}

# 富文本后处理正则（去掉 <|...|> 标记）
RICH_REGEX = r"<\|.*\|>"


class ASRRequest(BaseModel):
    audio: str  # base64 encoded audio
    language: str = "auto"
    use_itn: bool = True


class ASRResponse(BaseModel):
    status: str
    text: str
    language: str = ""


@app.on_event("startup")
async def load_model():
    global _model, _kwargs
    model_dir = Path("/root/.cache/modelscope/models/iic--SenseVoiceSmall/snapshots/master")
    logger.info(f"Loading SenseVoice model from {model_dir}")

    try:
        _model = AutoModel(
            model=str(model_dir),
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        logger.info("SenseVoice model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load model from cache: {e}")
        try:
            logger.info("Attempting to download from ModelScope Hub...")
            _model = AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                trust_remote_code=True,
                device="cuda" if torch.cuda.is_available() else "cpu"
            )
            logger.info("Loaded SenseVoice from ModelScope Hub")
        except Exception as e2:
            logger.error(f"Failed to load from ModelScope Hub: {e2}")
            raise


def _clean_text(raw: str) -> str:
    """去除 SenseVoice 输出的富文本标记 <|...|>。"""
    return re.sub(RICH_REGEX, "", raw, 0, re.MULTILINE).strip()


def _run_inference(audio_float: np.ndarray, language: str = "auto", use_itn: bool = True) -> dict:
    """对 float32 16kHz 单声道音频执行 SenseVoice 推理，返回 {text, language, emotion}。"""
    global _model, _kwargs
    if _model is None:
        return {"text": "", "language": "", "emotion": ""}

    result = _model.inference(
        audio_float,
        language=language if language != "auto" else None,
        use_itn=use_itn,
        **_kwargs
    )

    if isinstance(result, list) and len(result) > 0:
        item = result[0]
        raw_text = item.get("text", "") if isinstance(item, dict) else str(item)
        emo_match = re.search(r"<\|([A-Z]+)\|>", raw_text)
        emotion = emo_match.group(1) if emo_match else ""
        clean = _clean_text(raw_text)
        return {"text": clean, "language": language, "emotion": emotion}
    elif isinstance(result, dict):
        raw_text = result.get("text", "")
        clean = _clean_text(raw_text)
        return {"text": clean, "language": language, "emotion": ""}
    return {"text": "", "language": language, "emotion": ""}


def _pcm_bytes_to_float(pcm_bytes: bytes) -> np.ndarray:
    """PCM int16 LE bytes → float32 numpy array。"""
    arr = np.frombuffer(pcm_bytes, dtype=np.int16)
    return arr.astype(np.float32) / 32768.0


# ------------------------------------------------------------------ #
# HTTP 端点：/asr/recognize（base64 JSON，原有接口保持兼容）
# ------------------------------------------------------------------ #
@app.post("/asr/recognize", response_model=ASRResponse)
async def recognize_audio(request: ASRRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        audio_bytes = base64.b64decode(request.audio)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        with wave.open(temp_path, 'rb') as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if sample_width == 2:
            dtype = np.int16
        elif sample_width == 4:
            dtype = np.int32
        else:
            dtype = np.uint8

        audio_array = np.frombuffer(frames, dtype=dtype)

        if dtype == np.uint8:
            audio_float = (audio_array - 128) / 128.0
        elif dtype == np.int16:
            audio_float = audio_array / 32768.0
        else:
            audio_float = audio_array / 2147483648.0

        if channels > 1:
            audio_float = audio_float.reshape(-1, channels).mean(axis=1)

        if sample_rate != 16000:
            target_length = int(len(audio_float) * 16000 / sample_rate)
            indices = np.linspace(0, len(audio_float) - 1, target_length)
            audio_float = np.interp(indices, np.arange(len(audio_float)), audio_float)

        result = _run_inference(audio_float, request.language, request.use_itn)

        Path(temp_path).unlink(missing_ok=True)

        return ASRResponse(
            status="success",
            text=result["text"],
            language=request.language
        )

    except Exception as e:
        logger.error(f"ASR error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------ #
# HTTP 端点：/api/v1/asr（multipart form，兼容 CX-O-SERVER _recognize_remote）
# ------------------------------------------------------------------ #
@app.post("/api/v1/asr")
async def api_v1_asr(
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    use_itn: str = Form(default="true"),
    task: str = Form(default="rich"),
):
    """兼容 CX-O-SERVER 的 multipart/form-data ASR 调用。"""
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        audio_bytes = await file.read()
        use_itn_bool = use_itn.lower() in ("true", "1", "yes")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        with wave.open(temp_path, 'rb') as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if sample_width == 2:
            dtype = np.int16
        elif sample_width == 4:
            dtype = np.int32
        else:
            dtype = np.uint8

        audio_array = np.frombuffer(frames, dtype=dtype)

        if dtype == np.uint8:
            audio_float = (audio_array - 128) / 128.0
        elif dtype == np.int16:
            audio_float = audio_array / 32768.0
        else:
            audio_float = audio_array / 2147483648.0

        if channels > 1:
            audio_float = audio_float.reshape(-1, channels).mean(axis=1)

        if sample_rate != 16000:
            target_length = int(len(audio_float) * 16000 / sample_rate)
            indices = np.linspace(0, len(audio_float) - 1, target_length)
            audio_float = np.interp(indices, np.arange(len(audio_float)), audio_float)

        result = _run_inference(audio_float, language, use_itn_bool)

        Path(temp_path).unlink(missing_ok=True)

        return {"results": [result]}

    except Exception as e:
        logger.error(f"ASR /api/v1/asr error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------ #
# WebSocket 端点：/ws/asr/stream（流式 ASR，兼容 CX-O-SERVER VAD 链路）
# ------------------------------------------------------------------ #
@app.websocket("/ws/asr/stream")
async def ws_asr_stream(websocket: WebSocket):
    """流式 ASR WebSocket 端点。

    客户端发送：
      - 二进制帧：PCM 16kHz mono int16 LE 音频块
      - 文本帧 {"action": "final"}：语音结束信号

    服务端发送：
      - {"text": "...", "is_final": false, ...}  部分结果
      - {"text": "...", "is_final": true,  ...}  最终结果
    """
    await websocket.accept()
    logger.info("[WS-ASR] Client connected")

    pcm_buffer = bytearray()
    # 双流式模式由 ASR Partial 驱动 LLM Prefill，partial 越早出，端到端延迟越低。
    # VAD 门控下语音段常被切到 1~2s，原 48000(1.5s)/32000(1s) 阈值导致短句
    # 全程无 partial、pipeline 饥饿（2026-08-05 实测复现，详见
    # .trae/documents/20260805_模块0_修复短语音无Partial致流水线饥饿.md）。
    PARTIAL_THRESHOLD = 16000  # 首次 partial：~0.5s at 16kHz int16
    PARTIAL_STEP = 9600        # 后续 partial 步进：每新增 ~0.3s 触发一次
    MAX_BUFFER = 960000        # 缓冲上限 ~30s，防 VAD 漏检时无界增长
    TRIM_TO = 128000           # 超限后保留尾部 ~4s
    # 单飞推理标志：任一时刻至多 1 个 partial 推理在飞。
    # 严禁每帧都提交全缓冲推理——帧速 16.7/s 下默认线程池会排入数十个
    # 推理任务，GIL 挤占导致 uvicorn loop 无法应答 WS ping，客户端
    # keepalive 超时断连、推理结果全部丢失（2026-08-05 实测复现）。
    inference_running = False
    last_partial_len = 0

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"] is not None:
                pcm_buffer.extend(message["bytes"])

                # 缓冲安全上限：裁剪保留尾部，防止无界增长
                if len(pcm_buffer) > MAX_BUFFER:
                    del pcm_buffer[:-TRIM_TO]
                    last_partial_len = min(last_partial_len, len(pcm_buffer))

                # 步进触发 + 单飞：在飞期间音频继续入缓冲，
                # 下一触发点自然携带最新数据，不丢信息
                if (not inference_running
                        and len(pcm_buffer) >= PARTIAL_THRESHOLD
                        and len(pcm_buffer) - last_partial_len >= PARTIAL_STEP):
                    inference_running = True
                    last_partial_len = len(pcm_buffer)
                    audio_snapshot = _pcm_bytes_to_float(bytes(pcm_buffer))

                    async def _do_partial():
                        nonlocal inference_running
                        try:
                            result = await asyncio.get_event_loop().run_in_executor(
                                None, _run_inference, audio_snapshot, "auto", True
                            )
                            if result["text"]:
                                await websocket.send_text(json.dumps({
                                    "text": result["text"],
                                    "is_final": False,
                                    "language": result.get("language", ""),
                                    "emotion": result.get("emotion", ""),
                                }))
                        except Exception as e:
                            logger.error(f"[WS-ASR] Partial inference error: {e}")
                        finally:
                            inference_running = False

                    asyncio.create_task(_do_partial())

            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("action") == "final":
                    if len(pcm_buffer) > 0:
                        audio_float = _pcm_bytes_to_float(bytes(pcm_buffer))
                        try:
                            result = await asyncio.get_event_loop().run_in_executor(
                                None, _run_inference, audio_float, "auto", True
                            )
                            await websocket.send_text(json.dumps({
                                "text": result["text"],
                                "is_final": True,
                                "language": result.get("language", ""),
                                "emotion": result.get("emotion", ""),
                            }))
                        except Exception as e:
                            logger.error(f"[WS-ASR] Final inference error: {e}")
                            await websocket.send_text(json.dumps({
                                "text": "", "is_final": True, "language": "", "emotion": "",
                            }))
                    else:
                        await websocket.send_text(json.dumps({
                            "text": "", "is_final": True, "language": "", "emotion": "",
                        }))
                    # 清空 buffer 准备下一轮
                    pcm_buffer.clear()
                    # 必须重置 partial 步进锚点：否则下一轮 utterance 需
                    # buffer >= last_partial_len + PARTIAL_STEP 才出首个 partial，
                    # 相当于把首轮阈值越抬越高（次生 bug，随阈值下调一并修复）
                    last_partial_len = 0

    except WebSocketDisconnect:
        logger.info("[WS-ASR] Client disconnected")
    except Exception as e:
        logger.error(f"[WS-ASR] Error: {e}")
    finally:
        logger.info("[WS-ASR] Connection closed")


@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": _model is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
