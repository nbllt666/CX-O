import json
import os
from datetime import datetime
from pathlib import Path

import httpx

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

VOICE_REFS_DIR = Path("data/voice_refs")
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}


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
    description="检查 IndexTTS 服务的运行状态。",
)
async def get_index_tts_status():
    """获取 IndexTTS 状态
    
    Returns:
        dict: 包含 status 字段，表示 IndexTTS 服务状态
    """
    try:
        status = await _check_index_tts_health()
        return {"status": status}
    except Exception as e:
        logger.error(f"获取 IndexTTS 状态失败: {e}", exc_info=True)
        return {"status": "error"}


def _load_tts_config() -> dict:
    """加载 TTS 配置
    
    Returns:
        dict: TTS 配置信息
    """
    config_file = Path("config/settings.json")
    
    default_config = {
        "ref_audio_path": "",
        "ref_text": "",
        "speed": 1.0,
        "cross_fade_duration": 0.15,
        "emotion_enabled": True,
        "effects_enabled": True,
        "emotion_voices": {}
    }
    
    if not config_file.exists():
        return default_config
    
    try:
        import json
        
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        tts_config = config_data.get("tts", {})
        
        return {
            "ref_audio_path": tts_config.get("ref_audio_path", ""),
            "ref_text": tts_config.get("ref_text", ""),
            "speed": tts_config.get("speed", 1.0),
            "cross_fade_duration": tts_config.get("cross_fade_duration", 0.15),
            "emotion_enabled": tts_config.get("emotion_enabled", True),
            "effects_enabled": tts_config.get("effects_enabled", True),
            "emotion_voices": tts_config.get("emotion_voices", {})
        }
    except Exception as e:
        logger.warning(f"加载 TTS 配置失败，使用默认配置: {e}")
        return default_config


async def _check_index_tts_health() -> str:
    """检查 IndexTTS 服务健康状态
    
    Returns:
        str: 服务状态 (running/stopped/disabled/error)
    """
    config_file = Path("config/settings.json")
    
    if not config_file.exists():
        return "disabled"
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        index_tts_config = config_data.get("index_tts", {})
        
        if not index_tts_config.get("enabled", False):
            return "disabled"
        
        base_url = index_tts_config.get("url", "")
        
        if not base_url:
            return "disabled"
        
        timeout = index_tts_config.get("timeout", 10)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url.rstrip('/')}/health")
            
            if response.status_code == 200:
                return "running"
            else:
                return "error"
    except FileNotFoundError:
        return "disabled"
    except httpx.ConnectError:
        return "stopped"
    except Exception:
        return "error"
