import os
import re
import time
import uuid
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from typing import List, Optional, Dict, Any
from enum import Enum
import torchaudio
from pydantic import BaseModel
from model import SenseVoiceSmall
from funasr.utils.postprocess_utils import rich_transcription_postprocess
from io import BytesIO
import httpx
import base64
from concurrent.futures import ThreadPoolExecutor

from config import settings, DEFAULT_ASR_CONFIG, ASRConfig

TARGET_FS = 16000

logging.basicConfig(
    level=getattr(logging, settings.log_level.value),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=settings.workers)

regex = r"<\|.*\|>"


class Language(str, Enum):
    auto = "auto"
    zh = "zh"
    en = "en"
    yue = "yue"
    ja = "ja"
    ko = "ko"
    nospeech = "nospeech"


class TaskType(str, Enum):
    asr = "asr"
    rich = "rich"


class AudioInput(BaseModel):
    url: Optional[str] = None
    audio_base64: Optional[str] = None


class ASRRequest(BaseModel):
    audio: AudioInput
    language: str = "auto"
    use_itn: bool = True
    task: TaskType = TaskType.rich


class BatchRequest(BaseModel):
    audios: List[AudioInput]
    language: str = "auto"
    use_itn: bool = True


class ASRResponse(BaseModel):
    task_id: str
    results: List[Dict[str, Any]]
    timestamp: str
    model_info: Dict[str, str]


class BatchResponse(BaseModel):
    task_id: str
    total_files: int
    successful: int
    failed: int
    results: List[Dict[str, Any]]
    timestamp: str


class ServiceStatus(BaseModel):
    status: str
    device: str
    model_dir: str
    version: str
    uptime_seconds: float


model_instance = None
model_kwargs = {}
start_time = None


def load_model():
    global model_instance, model_kwargs, start_time
    if model_instance is None:
        logger.info(f"Loading model: {settings.model_dir} on device: {settings.device}")
        start_time = time.time()
        model_instance, model_kwargs = SenseVoiceSmall.from_pretrained(
            model=settings.model_dir,
            device=settings.device
        )
        model_instance.eval()
        logger.info("Model loaded successfully")
    return model_instance, model_kwargs


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield
    executor.shutdown(wait=False)


app = FastAPI(
    title="SenseVoice API",
    description="Multilingual Speech Recognition API with SenseVoice",
    version="1.0.0",
    lifespan=lifespan
)

if settings.enable_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = []
    for error in exc.errors():
        errors.append({
            "loc": list(error.get("loc", [])),
            "msg": error.get("msg", ""),
            "type": error.get("type", "")
        })
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation error", "errors": errors}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "message": str(exc)}
    )


def process_audio(file_io: BytesIO) -> tuple:
    try:
        import torch
        import torchaudio
        import numpy as np
        from scipy.io import wavfile
        from scipy import signal
        import tempfile
        
        # 尝试使用 scipy 加载音频
        file_io.seek(0)
        
        # 保存到临时文件因为 scipy 需要文件路径
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(file_io.read())
            tmp_path = tmp.name
        
        try:
            sr, data = wavfile.read(tmp_path)
            # 转换为 float32
            if data.dtype == np.int16:
                audio_data = data.astype(np.float32) / 32768.0
            else:
                audio_data = data.astype(np.float32)
            
            # 转为 1D
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)
            
            # 重采样
            if sr != TARGET_FS:
                # 使用 scipy 进行重采样
                num_samples = int(len(audio_data) * TARGET_FS / sr)
                audio_data = signal.resample(audio_data, num_samples)
            
            return torch.from_numpy(audio_data), True
        finally:
            import os
            os.unlink(tmp_path)
            
    except Exception as e:
        logger.error(f"Error processing audio with scipy: {str(e)}")
        
        # 回退到 torchaudio
        try:
            import torch
            import torchaudio
            file_io.seek(0)
            data_or_path_or_list, audio_fs = torchaudio.load(file_io)
            
            if audio_fs != TARGET_FS:
                resampler = torchaudio.transforms.Resample(orig_freq=audio_fs, new_freq=TARGET_FS)
                data_or_path_or_list = resampler(data_or_path_or_list)
            
            if data_or_path_or_list.dim() > 1:
                data_or_path_or_list = data_or_path_or_list.mean(0)
            
            return data_or_path_or_list, True
        except Exception as e2:
            logger.error(f"Error processing audio with torchaudio: {str(e2)}")
            return None, False


def run_inference(audios: List, lang: str, asr_config: ASRConfig) -> List[Dict[str, Any]]:
    model, kwargs = load_model()
    
    if lang == "":
        lang = "auto"
    
    key = [f"audio_{i}" for i in range(len(audios))]
    
    res = model.inference(
        data_in=audios,
        language=lang,
        use_itn=asr_config.use_itn,
        ban_emo_unk=asr_config.ban_emo_unk,
        key=key,
        fs=TARGET_FS,
        **kwargs,
    )
    
    processed_results = []
    if len(res) > 0:
        for item in res[0]:
            processed_item = {
                "key": item.get("key", ""),
                "raw_text": item.get("text", ""),
                "text": "",
                "language": "",
                "emotion": "",
                "event": ""
            }
            
            raw_text = item.get("text", "")
            processed_item["clean_text"] = re.sub(regex, "", raw_text, 0, re.MULTILINE)
            
            if asr_config.use_itn:
                processed_item["text"] = rich_transcription_postprocess(raw_text)
            else:
                processed_item["text"] = processed_item["clean_text"]
            
            lang_match = re.search(r"<\|(\w+)\|>", raw_text)
            if lang_match:
                processed_item["language"] = lang_match.group(1)
            
            emo_match = re.search(r"<\|(HAPPY|SAD|ANGRY|NEUTRAL|FEARFUL|DISGUSTED|SURPRISED)\|>", raw_text)
            if emo_match:
                processed_item["emotion"] = emo_match.group(1)
            
            event_match = re.search(r"<\|(BGM|Speech|Applause|Laughter|Cry|Sneeze|Breath|Cough|Sing|Speech_Noise)\|>", raw_text)
            if event_match:
                processed_item["event"] = event_match.group(1)
            
            processed_results.append(processed_item)
    
    return processed_results


async def download_audio(url: str) -> Optional[BytesIO]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            return BytesIO(response.content)
    except Exception as e:
        logger.error(f"Error downloading audio from {url}: {str(e)}")
        return None


def decode_base64_audio(audio_base64: str) -> Optional[BytesIO]:
    try:
        audio_data = base64.b64decode(audio_base64)
        return BytesIO(audio_data)
    except Exception as e:
        logger.error(f"Error decoding base64 audio: {str(e)}")
        return None


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset=utf-8>
            <title>SenseVoice API</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                .info { background: #f0f0f0; padding: 20px; border-radius: 5px; }
                a { color: #0066cc; }
            </style>
        </head>
        <body>
            <h1>🎤 SenseVoice API Service</h1>
            <div class="info">
                <p><strong>Version:</strong> 1.0.0</p>
                <p><strong>Model:</strong> iic/SenseVoiceSmall</p>
                <p><strong>API Docs:</strong> <a href="./docs">Swagger UI</a></p>
                <p><strong>Health:</strong> <a href="./health">Health Check</a></p>
            </div>
        </body>
    </html>
    """


@app.get("/health", response_model=ServiceStatus)
async def health_check():
    uptime = time.time() - start_time if start_time else 0
    try:
        load_model()
        return ServiceStatus(
            status="healthy",
            device=settings.device,
            model_dir=settings.model_dir,
            version="1.0.0",
            uptime_seconds=uptime
        )
    except Exception as e:
        return ServiceStatus(
            status="unhealthy",
            device=settings.device,
            model_dir=settings.model_dir,
            version="1.0.0",
            uptime_seconds=uptime
        )


@app.post("/api/v1/asr", response_model=ASRResponse)
async def audio_to_text(
    file: UploadFile = File(description="Audio file (wav, mp3, etc.)"),
    language: str = Form(default="auto", description="Language: auto, zh, en, yue, ja, ko, nospeech"),
    use_itn: bool = Form(default=True, description="Use inverse text normalization"),
    task: TaskType = Form(default=TaskType.rich, description="Task type: asr or rich"),
):
    task_id = str(uuid.uuid4())
    logger.info(f"Processing ASR request: {task_id}, filename: {file.filename}")
    
    start_time_task = time.time()
    
    try:
        file_io = BytesIO(await file.read())
        audio_data, success = process_audio(file_io)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to process audio file")
        
        audios = [audio_data]
        
        asr_config = ASRConfig(
            language=language,
            use_itn=use_itn
        )
        
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            executor,
            run_inference,
            audios,
            language,
            asr_config
        )
        
        processing_time = time.time() - start_time_task
        logger.info(f"Request {task_id} completed in {processing_time:.2f}s")
        
        return ASRResponse(
            task_id=task_id,
            results=results,
            timestamp=datetime.utcnow().isoformat(),
            model_info={
                "model": settings.model_dir,
                "device": settings.device
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing request {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


@app.post("/api/v1/asr/json", response_model=ASRResponse)
async def audio_to_text_json(request: ASRRequest):
    task_id = str(uuid.uuid4())
    logger.info(f"Processing ASR JSON request: {task_id}")
    
    start_time_task = time.time()
    
    try:
        if request.audio.url:
            file_io = await download_audio(request.audio.url)
            if file_io is None:
                raise HTTPException(status_code=400, detail="Failed to download audio from URL")
        elif request.audio.audio_base64:
            file_io = decode_base64_audio(request.audio.audio_base64)
            if file_io is None:
                raise HTTPException(status_code=400, detail="Failed to decode base64 audio")
        else:
            raise HTTPException(status_code=400, detail="No audio input provided")
        
        audio_data, success = process_audio(file_io)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to process audio file")
        
        audios = [audio_data]
        
        asr_config = ASRConfig(
            language=request.language,
            use_itn=request.use_itn
        )
        
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            executor,
            run_inference,
            audios,
            request.language,
            asr_config
        )
        
        processing_time = time.time() - start_time_task
        logger.info(f"Request {task_id} completed in {processing_time:.2f}s")
        
        return ASRResponse(
            task_id=task_id,
            results=results,
            timestamp=datetime.utcnow().isoformat(),
            model_info={
                "model": settings.model_dir,
                "device": settings.device
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing request {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


@app.post("/api/v1/batch", response_model=BatchResponse)
async def batch_audio_to_text(
    files: List[UploadFile] = File(description="Multiple audio files"),
    language: str = Form(default="auto", description="Language for all files"),
    use_itn: bool = Form(default=True, description="Use inverse text normalization"),
):
    task_id = str(uuid.uuid4())
    total_files = len(files)
    logger.info(f"Processing batch request: {task_id}, files: {total_files}")
    
    start_time_task = time.time()
    
    successful = 0
    failed = 0
    results = []
    
    try:
        audios = []
        
        for i, file in enumerate(files):
            try:
                file_io = BytesIO(await file.read())
                audio_data, success_flag = process_audio(file_io)
                
                if success_flag and audio_data is not None:
                    audios.append(audio_data)
                    successful += 1
                else:
                    failed += 1
                    results.append({
                        "key": file.filename,
                        "error": "Failed to process audio file"
                    })
            except Exception as e:
                failed += 1
                results.append({
                    "key": file.filename,
                    "error": str(e)
                })
        
        if not audios:
            raise HTTPException(status_code=400, detail="No valid audio files processed")
        
        asr_config = ASRConfig(
            language=language,
            use_itn=use_itn
        )
        
        loop = asyncio.get_event_loop()
        batch_results = await loop.run_in_executor(
            executor,
            run_inference,
            audios,
            language,
            asr_config
        )
        
        results.extend(batch_results)
        
        processing_time = time.time() - start_time_task
        logger.info(f"Batch request {task_id} completed: {successful}/{total_files} in {processing_time:.2f}s")
        
        return BatchResponse(
            task_id=task_id,
            total_files=total_files,
            successful=successful,
            failed=failed,
            results=results,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing batch request {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")


@app.get("/api/v1/languages")
async def get_supported_languages():
    return {
        "languages": [
            {"code": "auto", "name": "Auto Detect"},
            {"code": "zh", "name": "Chinese (Mandarin)"},
            {"code": "en", "name": "English"},
            {"code": "yue", "name": "Cantonese"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ko", "name": "Korean"},
            {"code": "nospeech", "name": "No Speech"}
        ]
    }


@app.get("/api/v1/tasks")
async def get_supported_tasks():
    return {
        "tasks": [
            {"code": "asr", "name": "Speech Recognition"},
            {"code": "rich", "name": "Rich Transcription (ASR + SER + AED)"}
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        log_level=settings.log_level.value.lower()
    )
