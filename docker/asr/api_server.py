"""
ASR SenseVoice API Server
基于 FunASR 的 SenseVoice 语音识别 HTTP API
"""
import base64
import io
import logging
import tempfile
import wave
from pathlib import Path
from typing import Optional

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 导入 SenseVoice 模型
from sensevoice.model import SenseVoiceSmall

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ASR SenseVoice Service")

# 全局模型实例
_model = None
_kwargs = None


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
    model_dir = Path("/app/sensevoice")
    logger.info(f"Loading SenseVoice model from {model_dir}")
    
    try:
        _model, _kwargs = SenseVoiceSmall.from_pretrained(
            model=str(model_dir),
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        _model.eval()
        logger.info("SenseVoice model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        # 尝试从 ModelScope 加载预训练模型
        try:
            from funasr import AutoModel
            _model, _kwargs = AutoModel.build_model(
                model="iic/SenseVoiceSmall",
                trust_remote_code=True
            )
            logger.info("Loaded SenseVoice from ModelScope")
        except Exception as e2:
            logger.error(f"Failed to load from ModelScope: {e2}")
            raise


@app.post("/asr/recognize", response_model=ASRResponse)
async def recognize_audio(request: ASRRequest):
    global _model, _kwargs
    
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # 解码 base64 音频
        audio_bytes = base64.b64decode(request.audio)
        
        # 保存到临时文件并加载
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name
        
        # 使用 torchaudio 加载
        waveform, sample_rate = torchaudio.load(temp_path)
        
        # 重采样到 16kHz（如果需要）
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
        
        # 转换为模型输入格式
        audio_input = waveform.squeeze(0).numpy()
        
        # 执行识别
        result = _model.inference(
            audio_input,
            language=request.language if request.language != "auto" else None,
            use_itn=request.use_itn,
            **_kwargs
        )
        
        # 解析结果
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        
        # 清理临时文件
        Path(temp_path).unlink(missing_ok=True)
        
        return ASRResponse(
            status="success",
            text=text,
            language=request.language
        )
        
    except Exception as e:
        logger.error(f"ASR error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": _model is not None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)