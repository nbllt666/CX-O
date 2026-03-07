import io
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import Response
import torch
import torchaudio

from f5tts_pytorch_engine import F5TTSEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    logger.info("Initializing F5-TTS Engine...")
    _engine = F5TTSEngine(
        model_path="/models/F5TTS_Base/model_1200000.pt",
        vocab_file="/models/F5TTS_Base/vocab.txt",
        device_id=0,
    )
    logger.info("F5-TTS Engine initialized successfully")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/v2/models/f5_tts/infer")
async def infer(
    reference_wav: UploadFile = File(...),
    reference_wav_len: int = Form(...),
    reference_text: str = Form(...),
    target_text: str = Form(...),
):
    logger.info(f"Processing inference: ref_text='{reference_text[:20]}...', target='{target_text[:20]}...'")
    
    start_time = time.time()
    
    wav_bytes = await reference_wav.read()
    waveform, sample_rate = torchaudio.load(io.BytesIO(wav_bytes))
    
    audio, inference_time = _engine.infer(
        reference_wav=waveform,
        reference_wav_len=reference_wav_len,
        reference_sample_rate=sample_rate,
        reference_text=reference_text,
        target_text=target_text,
    )
    
    buffer = io.BytesIO()
    torchaudio.save(buffer, audio, sample_rate, format="wav")
    buffer.seek(0)
    
    total_time = time.time() - start_time
    logger.info(f"Inference completed in {total_time:.3f}s (model: {inference_time:.3f}s)")
    
    return Response(content=buffer.read(), media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
