"""
ASR SenseVoice FastAPI 服务启动脚本
"""
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import base64
import tempfile
import torch
import torchaudio
from pathlib import Path

from sensevoice.model import SenseVoiceSmall

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
    print("Loading SenseVoice model...")
    
    try:
        _model, _kwargs = SenseVoiceSmall.from_pretrained(
            model="/app/sensevoice",
            device="cuda" if torch.cuda.is_available() else "cpu"
        )
        _model.eval()
        print("SenseVoice model loaded successfully")
    except Exception as e:
        print(f"Failed to load model: {e}")
        raise


@app.post("/asr/recognize", response_model=ASRResponse)
async def recognize_audio(request: ASRRequest):
    global _model, _kwargs
    
    if _model is None:
        return ASRResponse(status="error", text="Model not loaded", language="")
    
    try:
        # 解码 base64 音频
        audio_bytes = base64.b64decode(request.audio)
        
        # 保存到临时文件并加载
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name
        
        # 使用 torchaudio 加载
        waveform, sample_rate = torchaudio.load(temp_path)
        
        # 重采样到 16kHz
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
        print(f"ASR error: {e}")
        return ASRResponse(status="error", text=str(e), language="")


@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": _model is not None}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)