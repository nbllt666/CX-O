import base64
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

VOICE_REFS_DIR = Path("data/voice_refs")
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}


class TransitionRequest(BaseModel):
    from_emotion: str
    to_emotion: str
    ref_audio_path: Optional[str] = None


class PregenerateRequest(BaseModel):
    base_audio_path: str
    sample_text: str = "这是参考音频样本。"
    transition_text: str = "嗯，"


class PregenerateProgress(BaseModel):
    current: int
    total: int
    message: str
    status: str = "in_progress"


class TTSSynthesizeRequest(BaseModel):
    text: str
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    ref_audio: Optional[str] = None
    ref_text: Optional[str] = None


_pregenerate_status: dict = {
    "is_running": False,
    "progress": None,
    "result": None,
    "error": None
}


def _ensure_voice_refs_dir():
    """确保语音参考目录存在"""
    VOICE_REFS_DIR.mkdir(parents=True, exist_ok=True)


@router.get(
    "/audio/config",
    summary="获取音频配置",
    description="获取 TTS 音频配置，包括参考音频路径、语速、情感语音等。",
)
async def get_audio_config():
    """获取音频配置
    
    Returns:
        dict: 包含 TTS 配置信息（参考音频路径、语速、情感语音等）
    """
    try:
        config = _load_tts_config()
        return config
    except Exception as e:
        logger.error(f"获取音频配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/audio/files",
    summary="获取音频文件列表",
    description="获取 voice_refs 目录下的所有音频文件列表。",
)
async def get_audio_files():
    """获取音频文件列表
    
    Returns:
        dict: 包含 files 列表，每个文件包含 name, size, modified 字段
    """
    try:
        _ensure_voice_refs_dir()
        
        files = []
        for f in VOICE_REFS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS:
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return {"files": files}
    except Exception as e:
        logger.error(f"获取音频文件列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/audio/files/{filename}",
    summary="获取音频文件",
    description="根据文件名获取音频文件内容。",
)
async def get_audio_file(filename: str):
    """获取音频文件
    
    Args:
        filename: 音频文件名
        
    Returns:
        FileResponse: 音频文件内容
    """
    try:
        _ensure_voice_refs_dir()
        
        file_path = VOICE_REFS_DIR / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件 '{filename}' 不存在")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"'{filename}' 不是有效文件")
        
        media_type = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"
        
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取音频文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete(
    "/audio/files/{filename}",
    summary="删除音频文件",
    description="根据文件名删除指定的音频文件。",
)
async def delete_audio_file(filename: str):
    """删除音频文件
    
    Args:
        filename: 要删除的音频文件名
    """
    try:
        _ensure_voice_refs_dir()
        
        file_path = VOICE_REFS_DIR / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件 '{filename}' 不存在")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"'{filename}' 不是有效文件")
        
        file_path.unlink()
        
        logger.info(f"已删除音频文件: {filename}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除音频文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/audio/index-tts/status",
    summary="获取 IndexTTS 状态",
    description="检查 IndexTTS 服务的运行状态（已废弃，请使用 /audio/cosyvoice/status）。",
    deprecated=True,
)
async def get_index_tts_status():
    """获取 IndexTTS 状态（已废弃）
    
    Returns:
        dict: 包含 status 字段，表示 IndexTTS 服务状态
    """
    return await get_cosyvoice_status()


@router.get(
    "/audio/cosyvoice/status",
    summary="获取 CosyVoice 状态",
    description="检查 CosyVoice 服务的运行状态。",
)
async def get_cosyvoice_status():
    """获取 CosyVoice 状态
    
    Returns:
        dict: 包含 status 字段，表示 CosyVoice 服务状态
    """
    try:
        status = await _check_cosyvoice_health()
        return {"status": status, "engine": "cosyvoice"}
    except Exception as e:
        logger.error(f"获取 CosyVoice 状态失败: {e}", exc_info=True)
        return {"status": "error", "engine": "cosyvoice"}


@router.post(
    "/audio/cosyvoice/transition",
    summary="生成过渡音频",
    description="生成情感切换时的过渡音频。",
)
async def generate_transition_audio(request: TransitionRequest):
    """生成过渡音频
    
    Args:
        request: 包含 from_emotion, to_emotion, ref_audio_path 的请求体
        
    Returns:
        Response: 过渡音频数据 (audio/wav)
    """
    try:
        config = _load_tts_config()
        cosyvoice_url = config.get("cosyvoice", {}).get("url", "http://127.0.0.1:50000")
        
        from backend.services.cosyvoice_client import get_cosyvoice_client
        client = get_cosyvoice_client(base_url=cosyvoice_url)
        
        ref_audio_path = request.ref_audio_path or config.get("ref_audio_path", "")
        if not ref_audio_path:
            raise HTTPException(status_code=400, detail="需要提供参考音频路径")
        
        ref_audio_path = Path(ref_audio_path)
        if not ref_audio_path.exists():
            raise HTTPException(status_code=404, detail=f"参考音频文件不存在: {ref_audio_path}")
        
        with open(ref_audio_path, "rb") as f:
            ref_audio_data = f.read()
        
        transition_audio = await client.generate_transition_audio(
            from_emotion=request.from_emotion,
            to_emotion=request.to_emotion,
            ref_audio=ref_audio_data
        )
        
        return Response(
            content=transition_audio,
            media_type="audio/wav",
            headers={
                "X-From-Emotion": request.from_emotion,
                "X-To-Emotion": request.to_emotion
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成过渡音频失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成过渡音频失败: {str(e)}")


@router.post(
    "/audio/cosyvoice/pregenerate-refs",
    summary="预生成参考音频",
    description="使用 CosyVoice 预生成 64 个情感和过渡参考音频。",
)
async def pregenerate_refs(request: PregenerateRequest):
    """预生成参考音频

    Args:
        request: 包含 base_audio_path, sample_text, transition_text 的请求体

    Returns:
        dict: 生成结果
    """
    global _pregenerate_status

    if _pregenerate_status["is_running"]:
        raise HTTPException(status_code=409, detail="预生成任务正在进行中")

    try:
        _pregenerate_status["is_running"] = True
        _pregenerate_status["progress"] = None
        _pregenerate_status["result"] = None
        _pregenerate_status["error"] = None

        base_audio_path = Path(request.base_audio_path)
        if not base_audio_path.exists():
            raise HTTPException(status_code=404, detail=f"基础参考音频文件不存在: {request.base_audio_path}")

        config = _load_tts_config()
        cosyvoice_url = config.get("cosyvoice", {}).get("url", "http://127.0.0.1:50000")

        from backend.services.cosyvoice_client import CosyVoiceClient
        client = CosyVoiceClient(base_url=cosyvoice_url)

        try:
            if not await client.health_check():
                raise HTTPException(status_code=503, detail=f"CosyVoice 服务不可用: {cosyvoice_url}")

            emotions_dir = VOICE_REFS_DIR / "emotions"
            transitions_dir = VOICE_REFS_DIR / "transitions"

            def progress_callback(current: int, total: int, message: str):
                _pregenerate_status["progress"] = {
                    "current": current,
                    "total": total,
                    "message": message
                }

            results = await client.generate_all_refs(
                ref_audio=base_audio_path,
                emotions_dir=emotions_dir,
                transitions_dir=transitions_dir,
                sample_text=request.sample_text,
                transition_text=request.transition_text,
                progress_callback=progress_callback
            )

            _pregenerate_status["result"] = {
                "emotions_count": len(results["emotions"]),
                "transitions_count": len(results["transitions"]),
                "total": results["total"]
            }

            return {
                "status": "success",
                "emotions_count": len(results["emotions"]),
                "transitions_count": len(results["transitions"]),
                "total": results["total"],
                "emotions_dir": str(emotions_dir),
                "transitions_dir": str(transitions_dir)
            }

        finally:
            await client.close()

    except HTTPException:
        raise
    except Exception as e:
        _pregenerate_status["error"] = str(e)
        logger.error(f"预生成参考音频失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预生成参考音频失败: {str(e)}")
    finally:
        _pregenerate_status["is_running"] = False


@router.get(
    "/audio/cosyvoice/refs-status",
    summary="获取参考音频状态",
    description="检查预生成参考音频的状态和数量。",
)
async def get_refs_status():
    """获取参考音频状态

    Returns:
        dict: 包含预生成状态和已生成文件数量
    """
    emotions_dir = VOICE_REFS_DIR / "emotions"
    transitions_dir = VOICE_REFS_DIR / "transitions"

    emotions_count = len(list(emotions_dir.glob("*.wav"))) if emotions_dir.exists() else 0
    transitions_count = len(list(transitions_dir.glob("*.wav"))) if transitions_dir.exists() else 0

    return {
        "pregenerate_status": _pregenerate_status,
        "emotions_count": emotions_count,
        "transitions_count": transitions_count,
        "total_count": emotions_count + transitions_count,
        "expected_total": 64,
        "is_complete": emotions_count == 8 and transitions_count == 56,
        "emotions_dir": str(emotions_dir),
        "transitions_dir": str(transitions_dir)
    }


@router.get("/audio/emotions/list", summary="列出情绪配置")
async def list_emotion_configs():
    try:
        from backend.services.emotion_parser import get_supported_emotions
        from backend.services.index_tts_client import get_emotion_text

        config = _load_tts_config()
        emotion_voices = config.get("emotion_voices", {})

        emotions = get_supported_emotions()
        result = []
        for emotion in emotions:
            voice_config = emotion_voices.get(emotion, {})
            result.append({
                "emotion": emotion,
                "default_text": get_emotion_text(emotion),
                "ref_audio": voice_config.get("ref_audio", ""),
                "ref_text": voice_config.get("ref_text", "")
            })

        return {"status": "success", "emotions": result}
    except Exception as e:
        logger.error(f"获取情绪配置列表失败: {e}", exc_info=True)
        return {"status": "error", "message": "获取情绪配置列表失败"}


@router.post("/tts/synthesize", summary="TTS合成")
async def tts_synthesize(request: TTSSynthesizeRequest):
    try:
        if not request.text:
            return {"status": "error", "message": "缺少文本内容"}

        config = _load_tts_config()
        engine = config.get("engine", "cosyvoice")

        if engine == "cosyvoice":
            tts_url = config.get("cosyvoice", {}).get("url", "http://127.0.0.1:50000")
            timeout = config.get("cosyvoice", {}).get("timeout", 120)
            cosyvoice_url = tts_url
        else:
            f5_config = config.get("f5_tts", {})
            tts_url = f5_config.get("url", "http://127.0.0.1:5000")
            timeout = f5_config.get("timeout", 120)
            cosyvoice_url = config.get("cosyvoice", {}).get("url")

        from backend.services.tts_client import TTSClient
        client = TTSClient(
            base_url=tts_url,
            ref_audio_path=config.get("ref_audio_path", ""),
            ref_text=config.get("ref_text", ""),
            timeout=timeout,
            emotion_voices=config.get("emotion_voices", {}),
            voice_refs_dir=str(VOICE_REFS_DIR),
            engine=engine,
            cosyvoice_url=cosyvoice_url,
            transition_enabled=config.get("transition", {}).get("enabled", True),
            transition_text=config.get("transition", {}).get("transition_text", "嗯，")
        )

        try:
            kwargs = {
                "speed": request.speed if request.speed != 1.0 else config.get("speed", 1.0),
                "cross_fade_duration": request.cross_fade_duration if request.cross_fade_duration != 0.15 else config.get("cross_fade_duration", 0.15),
            }
            if request.ref_audio:
                kwargs["ref_audio"] = request.ref_audio
            if request.ref_text:
                kwargs["ref_text"] = request.ref_text

            audio_bytes = await client.synthesize(request.text, **kwargs)

            return {
                "status": "success",
                "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
                "format": "wav"
            }
        finally:
            await client.close()

    except Exception as e:
        logger.error(f"TTS合成失败: {e}", exc_info=True)
        return {"status": "error", "message": "TTS合成失败"}


@router.post("/tts/synthesize-stream", summary="TTS流式合成")
async def tts_synthesize_stream(request: Request):
    try:
        data = await request.json()
        text = data.get("text", "")

        if not text:
            async def error_stream():
                yield f"data: {json.dumps({'type': 'error', 'message': '缺少文本内容'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(error_stream(), media_type="text/event-stream")

        config = _load_tts_config()
        engine = config.get("engine", "cosyvoice")

        if engine == "cosyvoice":
            tts_url = config.get("cosyvoice", {}).get("url", "http://127.0.0.1:50000")
            timeout = config.get("cosyvoice", {}).get("timeout", 120)
            cosyvoice_url = tts_url
        else:
            f5_config = config.get("f5_tts", {})
            tts_url = f5_config.get("url", "http://127.0.0.1:5000")
            timeout = f5_config.get("timeout", 120)
            cosyvoice_url = config.get("cosyvoice", {}).get("url")

        from backend.services.tts_client import TTSClient
        client = TTSClient(
            base_url=tts_url,
            ref_audio_path=config.get("ref_audio_path", ""),
            ref_text=config.get("ref_text", ""),
            timeout=timeout,
            emotion_voices=config.get("emotion_voices", {}),
            voice_refs_dir=str(VOICE_REFS_DIR),
            engine=engine,
            cosyvoice_url=cosyvoice_url,
            transition_enabled=config.get("transition", {}).get("enabled", True),
            transition_text=config.get("transition", {}).get("transition_text", "嗯，")
        )

        kwargs = {
            "speed": data.get("speed", config.get("speed", 1.0)),
            "cross_fade_duration": data.get("cross_fade_duration", config.get("cross_fade_duration", 0.15)),
        }

        async def stream_generator():
            try:
                async for chunk in client.synthesize_stream(text, **kwargs):
                    audio_base64 = None
                    if chunk.get("audio_data"):
                        audio_base64 = base64.b64encode(chunk["audio_data"]).decode("utf-8")
                    chunk_data = json.dumps({
                        "type": "chunk",
                        "text_segment": chunk.get("text_segment", ""),
                        "audio_data": audio_base64,
                        "chunk_index": chunk.get("chunk_index", 0),
                        "is_final": chunk.get("is_final", False)
                    }, ensure_ascii=False)
                    yield f"data: {chunk_data}\n\n"
            except Exception as e:
                logger.error(f"TTS流式合成错误: {e}", exc_info=True)
                error_data = json.dumps({"type": "error", "message": f"TTS流式合成失败: {str(e)}"}, ensure_ascii=False)
                yield f"data: {error_data}\n\n"
            finally:
                await client.close()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    except Exception as e:
        logger.error(f"TTS流式合成初始化失败: {e}", exc_info=True)

        async def error_stream():
            err_data = json.dumps({"type": "error", "message": "TTS流式合成初始化失败"}, ensure_ascii=False)
            yield f"data: {err_data}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")


@router.post("/asr/speech-to-text", summary="ASR语音识别")
async def asr_speech_to_text(request: Request):
    temp_path = None
    try:
        content_type = request.headers.get("content-type", "")
        language = "auto"

        if "multipart/form-data" in content_type:
            form = await request.form()
            audio_file = form.get("file")
            language = form.get("language", "auto")
            if not audio_file:
                return {"status": "error", "message": "未提供音频文件"}
            audio_data = await audio_file.read()
        else:
            data = await request.json()
            audio_base64 = data.get("audio", "")
            language = data.get("language", "auto")
            if not audio_base64:
                return {"status": "error", "message": "未提供音频数据"}
            audio_bytes = base64.b64decode(audio_base64)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name
            with open(temp_path, "rb") as f:
                audio_data = f.read()

        asr_config = _load_asr_config()

        from backend.services.asr_client import ASRClient
        client = ASRClient(base_url=asr_config["url"], timeout=asr_config.get("timeout", 60))
        try:
            result = await client.recognize(audio_data, language)

            return {
                "status": "success",
                "text": result.get("text", ""),
                "language": result.get("language", "")
            }
        finally:
            await client.close()
    except Exception as e:
        logger.error(f"ASR语音识别失败: {e}", exc_info=True)
        return {"status": "error", "message": "语音识别失败"}
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


@router.post("/audio/generate-emotions", summary="生成情绪音频")
async def generate_emotion_audios(request: Request):
    try:
        from backend.services.index_tts_client import get_emotion_text, EMOTION_TEMPLATES, IndexTTSClient
        from backend.services.index_tts_manager import get_indextts_manager

        index_tts_config = _load_index_tts_config()
        if not index_tts_config.get("enabled", False):
            return {"status": "error", "message": "IndexTTS 服务未启用"}

        manager = get_indextts_manager(
            base_url=index_tts_config["url"],
            start_command=index_tts_config.get("start_command", ""),
            working_dir=index_tts_config.get("working_dir", "IndexTTS"),
            auto_stop_delay=index_tts_config.get("auto_stop_delay", 300),
            startup_timeout=index_tts_config.get("startup_timeout", 180),
            root_dir=Path(__file__).resolve().parents[3]
        )

        is_running = await manager.ensure_running()
        if not is_running:
            return {"status": "error", "message": "IndexTTS 服务启动失败"}

        data = await request.json()
        ref_audio = data.get("ref_audio", "")
        ref_text = data.get("ref_text", "")

        if not ref_audio:
            return {"status": "error", "message": "需要提供参考音频"}

        _ensure_voice_refs_dir()
        audio_path = VOICE_REFS_DIR / ref_audio
        if not audio_path.exists():
            return {"status": "error", "message": f"参考音频文件不存在: {ref_audio}"}

        client = IndexTTSClient(
            base_url=index_tts_config["url"],
            timeout=index_tts_config.get("timeout", 180)
        )

        try:
            emotions_to_generate: list[tuple[str, float]] = []

            if data.get("auto_full", False):
                emotions_to_generate = [
                    (e, i)
                    for e in ["happy", "sad", "angry", "surprised", "tender", "fearful", "disgusted", "normal"]
                    for i in [0.2, 0.4, 0.6, 0.8, 1.0]
                ]
            elif data.get("template"):
                template_name = data.get("template")
                if template_name not in EMOTION_TEMPLATES:
                    return {"status": "error", "message": f"未知模板: {template_name}"}
                emotions_to_generate = EMOTION_TEMPLATES[template_name]
            elif data.get("emotions"):
                for item in data.get("emotions", []):
                    if isinstance(item, dict):
                        emotions_to_generate.append((item.get("type", "neutral"), item.get("intensity", 0.5)))
                    else:
                        emotions_to_generate.append((item, 0.5))

            generated: dict[str, str] = {}
            errors: dict[str, str] = {}

            for emotion, intensity in emotions_to_generate:
                try:
                    audio_bytes = await client.generate_emotion_audio(
                        emotion=emotion, intensity=intensity,
                        ref_audio=str(audio_path), ref_text=ref_text
                    )
                    base_name = Path(ref_audio).stem
                    output_name = f"{base_name}_{emotion}.wav" if intensity == 0.5 else f"{base_name}_{emotion}_{intensity}.wav"
                    output_path = VOICE_REFS_DIR / output_name
                    IndexTTSClient.save_audio(audio_bytes, output_path)
                    key = f"{emotion}_{intensity}" if intensity != 0.5 else emotion
                    generated[key] = output_name
                except Exception as e:
                    logger.error(f"生成情绪音频失败 {emotion}@{intensity}: {e}", exc_info=True)
                    errors[f"{emotion}_{intensity}"] = str(e)

            if generated:
                config = _load_tts_config()
                emotion_voices = config.get("emotion_voices", {})
                for key, filename in generated.items():
                    parts = key.rsplit("_", 1)
                    emotion = parts[0]
                    emotion_text = get_emotion_text(emotion)
                    emotion_voices[emotion] = {"ref_audio": filename, "ref_text": emotion_text}
                _save_tts_emotion_voices(emotion_voices)

            return {"status": "success", "generated": generated, "errors": errors, "config_updated": len(generated) > 0}
        finally:
            await client.close()
            await manager.stop()
    except Exception as e:
        logger.error(f"生成情绪音频失败: {e}", exc_info=True)
        return {"status": "error", "message": "生成情绪音频失败"}


@router.post("/index-tts/synthesize", summary="IndexTTS合成")
async def index_tts_synthesize(request: Request):
    try:
        index_tts_config = _load_index_tts_config()
        if not index_tts_config.get("enabled", False):
            return {"status": "error", "message": "IndexTTS 服务未启用"}

        from backend.services.index_tts_manager import get_indextts_manager
        manager = get_indextts_manager(
            base_url=index_tts_config["url"],
            start_command=index_tts_config.get("start_command", ""),
            working_dir=index_tts_config.get("working_dir", "IndexTTS"),
            auto_stop_delay=index_tts_config.get("auto_stop_delay", 300),
            startup_timeout=index_tts_config.get("startup_timeout", 180),
            root_dir=Path(__file__).resolve().parents[3]
        )

        is_running = await manager.ensure_running()
        if not is_running:
            return {"status": "error", "message": "IndexTTS 服务启动失败"}

        data = await request.json()
        text = data.get("text", "")
        if not text:
            return {"status": "error", "message": "缺少文本内容"}

        from backend.services.index_tts_client import IndexTTSClient
        client = IndexTTSClient(base_url=index_tts_config["url"], timeout=index_tts_config.get("timeout", 180))

        try:
            kwargs = {
                "emotion": data.get("emotion", "neutral"),
                "emotion_intensity": data.get("emotion_intensity", 0.5),
                "speed": data.get("speed", 1.0),
                "pitch": data.get("pitch", 0.0),
            }

            ref_audio = data.get("ref_audio")
            ref_text = data.get("ref_text", "")
            if ref_audio:
                _ensure_voice_refs_dir()
                audio_path = VOICE_REFS_DIR / ref_audio
                if not audio_path.exists():
                    return {"status": "error", "message": f"参考音频文件不存在: {ref_audio}"}
                kwargs["timbre_ref"] = str(audio_path)
                kwargs["ref_text"] = ref_text

            audio_bytes = await client.synthesize(text, **kwargs)
            manager.reset_auto_stop_timer()

            return {
                "status": "success",
                "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
                "format": "wav"
            }
        finally:
            await client.close()
    except Exception as e:
        logger.error(f"IndexTTS合成失败: {e}", exc_info=True)
        return {"status": "error", "message": "IndexTTS合成失败"}


def _load_tts_config() -> dict:
    """加载 TTS 配置
    
    Returns:
        dict: TTS 配置信息
    """
    config_file = Path("config/settings.json")
    
    default_config = {
        "engine": "cosyvoice",
        "ref_audio_path": "",
        "ref_text": "",
        "speed": 1.0,
        "cross_fade_duration": 0.15,
        "emotion_enabled": True,
        "effects_enabled": True,
        "emotion_voices": {},
        "cosyvoice": {
            "url": "http://127.0.0.1:50000",
            "model": "CosyVoice2-0.5B",
            "default_mode": "instruct2",
            "timeout": 120
        },
        "transition": {
            "enabled": True,
            "duration": 0.5,
            "intensity": 0.7
        }
    }
    
    if not config_file.exists():
        return default_config
    
    try:
        import json
        
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        tts_config = config_data.get("tts", {})
        
        return {
            "engine": tts_config.get("engine", "cosyvoice"),
            "ref_audio_path": tts_config.get("ref_audio_path", ""),
            "ref_text": tts_config.get("ref_text", ""),
            "speed": tts_config.get("speed", 1.0),
            "cross_fade_duration": tts_config.get("cross_fade_duration", 0.15),
            "emotion_enabled": tts_config.get("emotion_enabled", True),
            "effects_enabled": tts_config.get("effects_enabled", True),
            "emotion_voices": tts_config.get("emotion_voices", {}),
            "cosyvoice": tts_config.get("cosyvoice", default_config["cosyvoice"]),
            "transition": tts_config.get("transition", default_config["transition"])
        }
    except Exception as e:
        logger.warning(f"加载 TTS 配置失败，使用默认配置: {e}")
        return default_config


async def _check_cosyvoice_health() -> str:
    """检查 CosyVoice 服务健康状态
    
    Returns:
        str: 服务状态 (running/stopped/disabled/error)
    """
    config = _load_tts_config()
    
    cosyvoice_config = config.get("cosyvoice", {})
    base_url = cosyvoice_config.get("url", "")
    
    if not base_url:
        return "disabled"
    
    timeout = cosyvoice_config.get("timeout", 10)
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url.rstrip('/')}/health")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    return "running"
                elif data.get("status") == "error":
                    return f"error: {data.get('error', 'unknown')}"
                else:
                    return "starting"
            else:
                return "error"
    except httpx.ConnectError:
        return "stopped"
    except Exception as e:
        logger.error(f"CosyVoice health check error: {e}")
        return "error"


async def _check_index_tts_health() -> str:
    """检查 IndexTTS 服务健康状态（已废弃，重定向到 CosyVoice）
    
    Returns:
        str: 服务状态
    """
    return await _check_cosyvoice_health()


def _load_asr_config() -> dict:
    config_file = Path("config/settings.json")
    default_config = {"url": "http://127.0.0.1:5001", "timeout": 60}
    if not config_file.exists():
        return default_config
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        asr_config = config_data.get("asr", {})
        return {
            "url": asr_config.get("url", default_config["url"]),
            "timeout": asr_config.get("timeout", default_config["timeout"])
        }
    except Exception as e:
        logger.warning(f"加载 ASR 配置失败，使用默认配置: {e}")
        return default_config


def _load_index_tts_config() -> dict:
    config_file = Path("config/settings.json")
    default_config = {
        "enabled": False,
        "url": "http://127.0.0.1:8004",
        "start_command": "",
        "working_dir": "IndexTTS",
        "auto_stop_delay": 300,
        "startup_timeout": 180,
        "timeout": 180
    }
    if not config_file.exists():
        return default_config
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        index_tts_config = config_data.get("index_tts", {})
        return {
            "enabled": index_tts_config.get("enabled", default_config["enabled"]),
            "url": index_tts_config.get("url", default_config["url"]),
            "start_command": index_tts_config.get("start_command", default_config["start_command"]),
            "working_dir": index_tts_config.get("working_dir", default_config["working_dir"]),
            "auto_stop_delay": index_tts_config.get("auto_stop_delay", default_config["auto_stop_delay"]),
            "startup_timeout": index_tts_config.get("startup_timeout", default_config["startup_timeout"]),
            "timeout": index_tts_config.get("timeout", default_config["timeout"])
        }
    except Exception as e:
        logger.warning(f"加载 IndexTTS 配置失败，使用默认配置: {e}")
        return default_config


def _save_tts_emotion_voices(emotion_voices: dict):
    config_file = Path("config/settings.json")
    try:
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        else:
            config_data = {}
        if "tts" not in config_data:
            config_data["tts"] = {}
        config_data["tts"]["emotion_voices"] = emotion_voices
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        logger.info("情绪语音配置已保存")
    except Exception as e:
        logger.error(f"保存情绪语音配置失败: {e}", exc_info=True)
