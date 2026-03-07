import io
import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

import torch
import torchaudio
import jieba
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from .f5tts_engine import F5TTSEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

f5tts_engine: Optional[F5TTSEngine] = None


class Config:
    ENGINE_DIR = "/engines"
    MODEL_PATH = "/models/F5TTS_Base/model_1200000.pt"
    VOCAB_FILE = "/models/F5TTS_Base/vocab.txt"
    VOCODER_ENGINE_PATH = "/models/vocoder/vocoder.plan"
    TARGET_SAMPLE_RATE = 24000
    MAX_MEL_LEN = 2048
    DEVICE_ID = 0


class InferenceResponse(BaseModel):
    status: str
    message: str
    inference_time: Optional[float] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global f5tts_engine
    
    logger.info("Initializing F5-TTS Engine...")
    jieba.initialize()
    
    try:
        f5tts_engine = F5TTSEngine(
            engine_dir=Config.ENGINE_DIR,
            model_path=Config.MODEL_PATH,
            vocab_file=Config.VOCAB_FILE,
            vocoder_engine_path=Config.VOCODER_ENGINE_PATH,
            target_sample_rate=Config.TARGET_SAMPLE_RATE,
            max_mel_len=Config.MAX_MEL_LEN,
            device_id=Config.DEVICE_ID,
        )
        logger.info("F5-TTS Engine initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize F5-TTS Engine: {e}")
        raise
    
    yield
    
    logger.info("Shutting down F5-TTS Engine...")
    f5tts_engine = None


app = FastAPI(
    title="F5-TTS Inference Service",
    description="FastAPI inference service for F5-TTS with TensorRT acceleration",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", summary="Health Check")
async def health_check() -> dict:
    engine_status = "ready" if f5tts_engine is not None else "not_initialized"
    return {
        "status": "healthy",
        "engine": engine_status,
    }


@app.post("/v2/models/f5_tts/infer", summary="TTS Inference")
async def infer(
    request: Request,
    reference_wav: UploadFile = File(..., description="Reference audio file"),
    reference_wav_len: int = Form(..., description="Length of reference audio in samples"),
    reference_text: str = Form(..., description="Transcription of reference audio"),
    target_text: str = Form(..., description="Text to synthesize"),
) -> Response:
    if f5tts_engine is None:
        raise HTTPException(status_code=503, detail="F5-TTS Engine not initialized")
    
    ttfb_start = time.time()
    
    try:
        audio_bytes = await reference_wav.read()
        buffer = io.BytesIO(audio_bytes)
        waveform, sample_rate = torchaudio.load(buffer)
        
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        
        logger.info(f"Processing inference: ref_text='{reference_text[:30]}...', target='{target_text[:30]}...'")
        
        audio, inference_time = f5tts_engine.infer(
            reference_wav=waveform,
            reference_wav_len=reference_wav_len,
            reference_sample_rate=sample_rate,
            reference_text=reference_text,
            target_text=target_text,
        )
        
        audio_np = audio.squeeze().cpu().numpy().astype("float32")
        ttfb = time.time() - ttfb_start
        
        logger.info(f"Inference completed in {inference_time:.3f}s, TTFB: {ttfb:.3f}s, audio length: {len(audio_np)} samples")
        
        return Response(
            content=audio_np.tobytes(),
            media_type="application/octet-stream",
            headers={
                "X-Inference-Time": str(inference_time),
                "X-TTFB": str(ttfb),
                "X-Audio-Sample-Rate": str(Config.TARGET_SAMPLE_RATE),
                "X-Audio-Samples": str(len(audio_np)),
            },
        )
        
    except Exception as e:
        import traceback
        logger.error(f"Inference failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v2/models/f5_tts/infer_wav", summary="TTS Inference with WAV output")
async def infer_wav(
    reference_wav: UploadFile = File(..., description="Reference audio file"),
    reference_text: str = Form(..., description="Transcription of reference audio"),
    target_text: str = Form(..., description="Text to synthesize"),
) -> Response:
    if f5tts_engine is None:
        raise HTTPException(status_code=503, detail="F5-TTS Engine not initialized")
    
    try:
        audio_bytes = await reference_wav.read()
        buffer = io.BytesIO(audio_bytes)
        waveform, sample_rate = torchaudio.load(buffer)
        
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        
        reference_wav_len = waveform.shape[1]
        
        logger.info(f"Processing inference: ref_text='{reference_text[:30]}...', target='{target_text[:30]}...'")
        
        audio, inference_time = f5tts_engine.infer(
            reference_wav=waveform,
            reference_wav_len=reference_wav_len,
            reference_sample_rate=sample_rate,
            reference_text=reference_text,
            target_text=target_text,
        )
        
        output_buffer = io.BytesIO()
        torchaudio.save(
            output_buffer,
            audio.cpu(),
            Config.TARGET_SAMPLE_RATE,
            format="wav",
        )
        output_buffer.seek(0)
        
        logger.info(f"Inference completed in {inference_time:.3f}s")
        
        return Response(
            content=output_buffer.read(),
            media_type="audio/wav",
            headers={
                "X-Inference-Time": str(inference_time),
            },
        )
        
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class InferenceRequest(BaseModel):
    reference_text: str
    target_text: str


@app.post("/v2/models/f5_tts/infer_base64", summary="TTS Inference with Base64 Audio")
async def infer_base64(
    request: InferenceRequest,
    reference_wav_base64: str = Form(..., description="Base64 encoded reference audio"),
    reference_sample_rate: int = Form(16000, description="Sample rate of reference audio"),
) -> dict:
    import base64
    
    if f5tts_engine is None:
        raise HTTPException(status_code=503, detail="F5-TTS Engine not initialized")
    
    try:
        audio_bytes = base64.b64decode(reference_wav_base64)
        buffer = io.BytesIO(audio_bytes)
        waveform, sample_rate = torchaudio.load(buffer)
        
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        
        reference_wav_len = waveform.shape[1]
        
        audio, inference_time = f5tts_engine.infer(
            reference_wav=waveform,
            reference_wav_len=reference_wav_len,
            reference_sample_rate=sample_rate,
            reference_text=request.reference_text,
            target_text=request.target_text,
        )
        
        output_buffer = io.BytesIO()
        torchaudio.save(
            output_buffer,
            audio.cpu(),
            Config.TARGET_SAMPLE_RATE,
            format="wav",
        )
        output_buffer.seek(0)
        
        output_base64 = base64.b64encode(output_buffer.read()).decode("utf-8")
        
        return {
            "status": "success",
            "audio_base64": output_base64,
            "sample_rate": Config.TARGET_SAMPLE_RATE,
            "inference_time": inference_time,
        }
        
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "inference_service.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
