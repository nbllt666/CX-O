import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
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
