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
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request
from pydantic import BaseModel

# 导入 SenseVoice 模型
from funasr import AutoModel

# 流式引擎（fsmn-vad 分句 + paraformer 增量 + cam++ 声纹 + 在线聚类）
from asr_container.streaming_engine import (
    StreamSession,
    load_profiles,
    status_dict,
    extract_embedding,
    asr_loaded,
    spk_loaded,
)

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


def _decode_audio_bytes(audio_bytes: bytes) -> Optional[np.ndarray]:
    """wav 字节 → float32 16kHz 单声道 numpy 数组；非法音频返回 None。

    与 /asr/recognize 的 wave 解析套路一致，并重采样至 16k。
    """
    try:
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

        Path(temp_path).unlink(missing_ok=True)
        return audio_float
    except Exception as e:  # noqa: BLE001
        logger.warning(f"音频解码失败: {e}")
        return None


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
    """流式 ASR WebSocket 端点（基于流式引擎：fsmn-vad 分句 + paraformer 增量 + cam++ 声纹）。

    客户端发送：
      - 二进制帧：PCM 16kHz mono int16 LE 音频块
      - 文本帧 {"action": "final"}：语音结束信号

    服务端发送（字段固定，含 speaker 判定）：
      - {"text", "is_final": false, "language", "emotion", "speaker_id",
         "speaker_registered", "speaker_conf"}  部分结果
      - 同上但 is_final=true  最终结果（含说话人判定）
    """
    await websocket.accept()
    logger.info("[WS-ASR] Client connected")

    # 引擎不可用降级：仍返回空 final，不崩溃。日志只告警一次避免刷屏。
    session = StreamSession()
    degraded = not asr_loaded()
    degraded_warned = not degraded

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"] is not None:
                if degraded:
                    if not degraded_warned:
                        logger.warning("[WS-ASR] ASR 引擎不可用，丢弃音频并降级返回空结果")
                        degraded_warned = True
                    continue
                try:
                    results = await session.feed_pcm(message["bytes"])
                    for m in results:
                        await websocket.send_text(json.dumps(m))
                except Exception as e:
                    logger.error(f"[WS-ASR] Feed inference error: {e}")

            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                if data.get("action") == "final":
                    try:
                        if degraded:
                            await websocket.send_text(json.dumps({
                                "text": "", "is_final": True, "language": "",
                                "emotion": "", "speaker_id": "",
                                "speaker_registered": False, "speaker_conf": 0.0,
                            }))
                        else:
                            results = await session.finish()
                            for m in results:
                                await websocket.send_text(json.dumps(m))
                    except Exception as e:
                        logger.error(f"[WS-ASR] Final inference error: {e}")
                        await websocket.send_text(json.dumps({
                            "text": "", "is_final": True, "language": "",
                            "emotion": "", "speaker_id": "",
                            "speaker_registered": False, "speaker_conf": 0.0,
                        }))

    except WebSocketDisconnect:
        logger.info("[WS-ASR] Client disconnected")
    except Exception as e:
        logger.error(f"[WS-ASR] Error: {e}")
    finally:
        logger.info("[WS-ASR] Connection closed")


# ------------------------------------------------------------------ #
# REST 端点：声纹（voiceprint）status / extract / profiles/sync
# ------------------------------------------------------------------ #
@app.get("/api/v1/voiceprint/status")
async def voiceprint_status():
    """声纹引擎状态与注册画像概览。"""
    return status_dict()


@app.post("/api/v1/voiceprint/extract")
async def voiceprint_extract(
    request: Request,
    file: Optional[UploadFile] = File(default=None),
):
    """提取说话人 192 维 embedding。

    兼容两种入参：
      ① multipart/form-data：字段名 file（Optional[UploadFile]）
      ② JSON body：{"audio": "<base64 音频>"}

    返回 {"embedding": [192 float], "dim": 192}；音频非法 → 400；模型未加载 → 503。
    """
    audio_bytes: Optional[bytes] = None

    if file is not None:
        audio_bytes = await file.read()
    else:
        body = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        encoded = body.get("audio")
        if isinstance(encoded, str) and encoded:
            try:
                audio_bytes = base64.b64decode(encoded)
            except Exception:  # noqa: BLE001
                audio_bytes = None

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="no audio provided (json {audio: base64} or multipart file)")

    audio_float = await asyncio.get_event_loop().run_in_executor(
        None, _decode_audio_bytes, audio_bytes
    )
    if audio_float is None or audio_float.size == 0:
        raise HTTPException(status_code=400, detail="invalid or empty audio")

    if not spk_loaded():
        raise HTTPException(status_code=503, detail="speaker model not loaded")

    emb = await asyncio.get_event_loop().run_in_executor(None, extract_embedding, audio_float)
    if emb is None:
        raise HTTPException(status_code=503, detail="embedding extraction failed")

    return {"embedding": [float(x) for x in emb.tolist()], "dim": int(emb.shape[0])}


@app.post("/api/v1/voiceprint/profiles/sync")
async def voiceprint_profiles_sync():
    """重载声纹画像 profiles（服务端权威写入后调用刷新容器侧注册池）。"""
    count = await asyncio.get_event_loop().run_in_executor(None, load_profiles)
    return {"ok": True, "count": count}


@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": _model is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
