"""
ASR SenseVoice FastAPI 服务启动脚本
"""
import asyncio
import json
import os
import re
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import base64
import tempfile
import torch
import numpy as np
from pathlib import Path

from sensevoice.config import settings
from sensevoice.model import SenseVoiceSmall

app = FastAPI(title="ASR SenseVoice Service")

# 全局模型实例
_model = None
_kwargs = None

# 富文本标签正则（与 CX-O-SERVER asr_service.py L25 保持一致）
_TAGS_REGEX = re.compile(r"<\|.*\|>")


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
    # 模型路径优先从环境变量 SENSEVOICE_MODEL_DIR 读取，默认 "iic/SenseVoiceSmall"（modelscope model id）
    # 首次启动会从 modelscope 下载模型到 /root/.cache/modelscope（由 docker-compose volume 持久化）
    model_dir = settings.model_dir
    print(f"Loading SenseVoice model from: {model_dir}")

    try:
        _model, _kwargs = SenseVoiceSmall.from_pretrained(
            model=model_dir,
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        _model.eval()
        print("SenseVoice model loaded successfully")
    except Exception as e:
        print(f"Failed to load model: {e}")
        raise


def _load_audio_bytes(audio_bytes: bytes):
    """从音频字节加载为 16kHz mono numpy float32 数组。

    优先使用 soundfile（funasr 依赖），失败时回退到 scipy.io.wavfile。
    避免 torchaudio 2.11+ 在 Linux 上需要 torchcodec 的问题。
    """
    # 优先 soundfile
    try:
        import soundfile as sf
        import io
        data, sample_rate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
        # mono
        if data.ndim > 1:
            data = data.mean(axis=1)
        # resample to 16kHz
        if sample_rate != 16000:
            data = _resample_linear(data, sample_rate, 16000)
        return data, 16000
    except Exception as e:
        print(f"soundfile load failed: {e}, trying scipy...")

    # 回退 scipy
    try:
        from scipy.io import wavfile
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name
        try:
            sr, data = wavfile.read(temp_path)
            if data.dtype == np.int16:
                data = data.astype(np.float32) / 32768.0
            elif data.dtype == np.int32:
                data = data.astype(np.float32) / 2147483648.0
            elif data.dtype == np.uint8:
                data = (data.astype(np.float32) - 128) / 128.0
            else:
                data = data.astype(np.float32)
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sr != 16000:
                data = _resample_linear(data, sr, 16000)
            return data, 16000
        finally:
            Path(temp_path).unlink(missing_ok=True)
    except Exception as e2:
        raise RuntimeError(f"Failed to load audio: soundfile={e}, scipy={e2}")


def _resample_linear(data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """线性重采样（避免 scipy.signal.resample 在某些边缘情况下的差异）。"""
    if orig_sr == target_sr:
        return data
    num_samples = int(len(data) * target_sr / orig_sr)
    indices = np.linspace(0, len(data) - 1, num_samples, endpoint=False)
    return np.interp(indices, np.arange(len(data)), data).astype(np.float32)


def _load_pcm_bytes(pcm_bytes: bytes, sample_rate: int = 16000) -> np.ndarray:
    """从 raw PCM bytes 加载为 numpy float32 数组（WebSocket streaming 用）。

    假设格式：16kHz mono int16 little-endian（与 CX-O-SERVER WS 音频契约一致）。
    与 _load_audio_bytes 的区别：不解析 WAV header，直接按 int16 解析。
    """
    if len(pcm_bytes) < 2:
        return np.zeros(0, dtype=np.float32)
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def _run_inference(audio_input, language: str, use_itn: bool) -> dict:
    """统一推理入口，返回 {text, language, emotion, event}。

    被 /asr/recognize（JSON base64）和 /api/v1/asr（multipart file）共用。

    调用契约与 CX-O-SERVER asr_service.py L224-253 _run_inference 对齐：
    - data_in=[audio] (list)
    - key=[f"audio_{i}"] (list)
    - fs=16000
    - 返回 res 是 list，res[0] 是 list，res[0][0] 是 dict 含 "text"
    """
    if _model is None:
        return {"text": "", "language": "", "emotion": "", "event": "", "error": "Model not loaded"}

    try:
        # 与 asr_service.py L227-235 对齐的调用方式
        key = [f"audio_0"]
        res = _model.inference(
            data_in=[audio_input],
            language=language if language != "auto" else None,
            use_itn=use_itn,
            key=key,
            fs=16000,
            **_kwargs
        )

        # 与 asr_service.py L237-240 对齐的解析方式
        if len(res) > 0 and len(res[0]) > 0:
            item = res[0][0]
            raw_text = item.get("text", "") if isinstance(item, dict) else str(item)
        else:
            raw_text = ""

        # 提取 language/emotion/event 标签（与 CX-O-SERVER asr_service.py L243-245 对齐）
        lang_match = re.search(r"<\|(\w+)\|>", raw_text)
        emo_match = re.search(
            r"<\|(HAPPY|SAD|ANGRY|NEUTRAL|FEARFUL|DISGUSTED|SURPRISED)\|>", raw_text
        )
        event_match = re.search(
            r"<\|(BGM|Speech|Applause|Laughter|Cry|Sneeze|Breath|Cough|Sing|Speech_Noise)\|>",
            raw_text,
        )

        # 清理富文本标签
        clean_text = _TAGS_REGEX.sub("", raw_text).strip()

        return {
            "text": clean_text,
            "language": lang_match.group(1) if lang_match else "",
            "emotion": emo_match.group(1) if emo_match else "",
            "event": event_match.group(1) if event_match else "",
        }
    except Exception as e:
        print(f"ASR inference error: {e}")
        return {"text": "", "language": "", "emotion": "", "event": "", "error": str(e)}


@app.post("/asr/recognize", response_model=ASRResponse)
async def recognize_audio(request: ASRRequest):
    global _model, _kwargs

    if _model is None:
        return ASRResponse(status="error", text="Model not loaded", language="")

    try:
        # 解码 base64 音频
        audio_bytes = base64.b64decode(request.audio)

        # 加载音频（统一走 soundfile + scipy 兜底，避免 torchaudio 2.11+ 的 torchcodec 依赖）
        audio_input, _ = _load_audio_bytes(audio_bytes)

        # 执行识别
        result = _run_inference(audio_input, request.language, request.use_itn)

        return ASRResponse(
            status="success" if not result.get("error") else "error",
            text=result["text"],
            language=result["language"] or request.language
        )

    except Exception as e:
        print(f"ASR error: {e}")
        return ASRResponse(status="error", text=str(e), language="")


@app.post("/api/v1/asr")
async def recognize_api_v1(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    use_itn: str = Form("true"),
    task: str = Form("transcribe"),
):
    """CX-O-SERVER asr_service._recognize_remote 期望的契约端点。

    请求：multipart/form-data
      - file: 音频文件（audio/wav）
      - language: "auto"/"zh"/"en" 等（默认 "auto"）
      - use_itn: "true"/"false" 字符串（默认 "true"）
      - task: "transcribe"/"rich" 等（默认 "transcribe"，"rich" 触发富文本后处理）

    响应：{"results": [{"text", "language", "emotion", "event"}]}
    失败：{"results": [], "error": "..."}
    """
    if _model is None:
        return {"results": [], "error": "Model not loaded"}

    try:
        # 读取上传的音频文件
        audio_bytes = await file.read()

        # 加载音频（统一走 soundfile + scipy 兜底）
        audio_input, _ = _load_audio_bytes(audio_bytes)

        # use_itn 字符串转 bool
        use_itn_bool = use_itn.lower() == "true"

        # 执行识别
        result = _run_inference(audio_input, language, use_itn_bool)

        # CX-O-SERVER asr_service.py L151-157 期望 {"results": [{...}]}
        return {"results": [result]}

    except Exception as e:
        print(f"ASR /api/v1/asr error: {e}")
        return {"results": [], "error": str(e)}


@app.websocket("/ws/asr/stream")
async def ws_asr_stream(ws: WebSocket):
    """WebSocket 流式 ASR 端点（方案B：SenseVoice 加 WS 接口）。

    协议：
    - 客户端 → 服务端：
      - 二进制消息：PCM 16kHz mono int16 LE 音频 chunk
      - 文本消息 JSON {"action": "final"}：触发 final 识别（剩余 buffer）
    - 服务端 → 客户端：
      - JSON {"text", "language", "emotion", "event", "is_final"}

    行为：
    - 客户端持续发送音频 chunk，服务端累积到 partial_threshold_ms（默认 200ms）
      就识别一次，返回 partial result（is_final=False）
    - 客户端发送 {"action":"final"} 后，服务端识别剩余 buffer，返回 final result（is_final=True）
    - 识别在 asyncio executor 中执行，避免阻塞 WS 接收
    """
    await ws.accept()

    buffer = bytearray()
    sample_rate = settings.audio_sample_rate  # 16000
    # 200ms = 3200 samples × 2 bytes = 6400 bytes
    partial_threshold_bytes = (
        settings.partial_threshold_ms * sample_rate * 2 // 1000
    )
    loop = asyncio.get_event_loop()

    try:
        while True:
            message = await ws.receive()

            if message["type"] == "websocket.disconnect":
                break

            # 二进制音频 chunk
            if "bytes" in message and message["bytes"] is not None:
                buffer.extend(message["bytes"])

                # 达到阈值，触发 partial 识别
                if len(buffer) >= partial_threshold_bytes:
                    audio_data = bytes(buffer)
                    buffer = bytearray()

                    if _model is None:
                        await ws.send_json({
                            "text": "", "language": "",
                            "emotion": "", "event": "",
                            "is_final": False,
                            "error": "Model not loaded"
                        })
                        continue

                    try:
                        audio_input = _load_pcm_bytes(audio_data, sample_rate)
                        result = await loop.run_in_executor(
                            None,
                            _run_inference,
                            audio_input,
                            "auto",
                            True
                        )
                        result["is_final"] = False
                        await ws.send_json(result)
                    except Exception as e:
                        print(f"WS partial inference error: {e}")
                        await ws.send_json({
                            "text": "", "language": "",
                            "emotion": "", "event": "",
                            "is_final": False,
                            "error": str(e)
                        })

            # 文本消息（JSON 控制）
            elif "text" in message and message["text"] is not None:
                try:
                    data = json.loads(message["text"])
                    if data.get("action") == "final":
                        # 识别剩余 buffer
                        if buffer and _model is not None:
                            audio_data = bytes(buffer)
                            buffer = bytearray()
                            try:
                                audio_input = _load_pcm_bytes(audio_data, sample_rate)
                                result = await loop.run_in_executor(
                                    None,
                                    _run_inference,
                                    audio_input,
                                    "auto",
                                    True
                                )
                                result["is_final"] = True
                                await ws.send_json(result)
                            except Exception as e:
                                print(f"WS final inference error: {e}")
                                await ws.send_json({
                                    "text": "", "language": "",
                                    "emotion": "", "event": "",
                                    "is_final": True,
                                    "error": str(e)
                                })
                        else:
                            # buffer 空 或 模型未加载
                            await ws.send_json({
                                "text": "", "language": "",
                                "emotion": "", "event": "",
                                "is_final": True
                            })
                except json.JSONDecodeError:
                    # 忽略非 JSON 文本消息
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket ASR stream error: {e}")
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": _model is not None}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)