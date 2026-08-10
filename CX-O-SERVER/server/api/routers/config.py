from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Any, Dict, Optional
import json
import yaml
from pathlib import Path

from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.config import Settings
from server.api.routers.admin import verify_admin_api_key
from server.core.websocket import get_websocket_manager

router = APIRouter()
logger = get_contextual_logger(__name__)

# 项目根（CX-O-SERVER），基于文件位置解析，避免依赖运行时工作目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class SenseVoiceStreamingConfigRequest(BaseModel):
    """SenseVoice Streaming 配置请求体"""

    chunk_size: Optional[int] = None
    hop_size: Optional[int] = None
    look_back: Optional[int] = None


class AdaptivePollingConfigRequest(BaseModel):
    """Adaptive Polling 配置请求体"""

    enabled: Optional[bool] = None
    offset_ms: Optional[int] = None
    window_size: Optional[int] = None
    min_interval_ms: Optional[int] = None
    max_interval_ms: Optional[int] = None


def _get_services_config() -> Dict[str, Any]:
    """从 config/settings.json 加载服务配置"""
    config_file = _PROJECT_ROOT / "config" / "settings.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取服务配置失败: {e}")
    return {}


def _save_services_config(config_data: Dict[str, Any]) -> None:
    """保存服务配置到 config/settings.json"""
    config_file = _PROJECT_ROOT / "config" / "settings.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)


def _get_default_sensevoice_config() -> Dict[str, Any]:
    """获取 SenseVoice Streaming 默认配置"""
    return {
        "chunk_size": 1024,
        "hop_size": 512,
        "look_back": 4
    }


def _get_default_adaptive_polling_config() -> Dict[str, Any]:
    """获取 Adaptive Polling 默认配置"""
    return {
        "enabled": True,
        "offset_ms": 100,
        "window_size": 5,
        "min_interval_ms": 50,
        "max_interval_ms": 500
    }


@router.get("/config/limits")
async def get_frontend_limits():
    """获取前端限制配置"""
    settings = Settings()
    return settings.config.limits.frontend.model_dump()


@router.get("/config")
async def get_unified_config():
    """获取统一配置 - 对应 Gateway 的 GET /api/config"""
    from server.api.routers.audio import _load_tts_config
    from server.config import get_settings
    settings = get_settings()

    try:
        audio_config = _load_tts_config()
    except Exception:
        audio_config = {
            "ref_audio_path": "",
            "ref_text": "",
            "speed": 1.0,
            "cross_fade_duration": 0.15,
            "emotion_enabled": True,
            "effects_enabled": True,
            "emotion_voices": {}
        }

    services_config = _get_services_config()

    vector_config = {
        "backend": settings.config.memory.vector_backend,
        "vector_size": settings.config.memory.weaviate.vector_size,
        "weaviate_host": settings.config.memory.weaviate.host,
        "weaviate_port": settings.config.memory.weaviate.port,
        "db_path": "data/chroma_db",
        "collection_name": "memory_vectors",
        "embedding_provider": settings.config.memory.embedding_provider,
        "embedding_model": settings.config.memory.embedding_model,
        "embedding_api_base": settings.config.memory.embedding_api_base,
        "embedding_api_key": settings.config.memory.embedding_api_key or "",
    }

    return {
        "status": "success",
        "config": {
            "audio": audio_config,
            "vector": vector_config,
            "llm": {
                "provider": settings.config.llm.provider,
                "model": settings.config.llm.model,
                "host": settings.config.llm.host,
            },
            "system": {
                "debug": settings.config.system.debug,
                "log_level": settings.config.system.log_level,
            },
            "live": services_config.get("services", {})
        }
    }


@router.put("/config")
async def update_unified_config(request: Request, _: bool = Depends(verify_admin_api_key)):
    """更新统一配置 - 对应 Gateway 的 POST /api/config"""
    from server.config import get_settings
    settings = get_settings()

    try:
        data = await request.json()
        section = data.get("section")
        section_data = data.get("data", {})

        if not section:
            raise HTTPException(status_code=400, detail="Missing section")

        if section == "audio":
            config_file = _PROJECT_ROOT / "config" / "settings.json"
            config_data = {}

            if config_file.exists():
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception as e:
                    logger.warning(f"读取服务配置失败: {e}")

            if "tts" not in config_data:
                config_data["tts"] = {}

            tts_config = config_data["tts"]
            for key in ['ref_audio_path', 'ref_text', 'speed', 'cross_fade_duration',
                       'emotion_enabled', 'effects_enabled', 'emotion_voices']:
                if key in section_data:
                    tts_config[key] = section_data[key]

            try:
                config_file.parent.mkdir(parents=True, exist_ok=True)
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"保存音频配置到文件失败: {e}")

            logger.info("音频配置已更新")
            return {"status": "success", "message": "Audio config saved"}

        elif section == "live":
            services_data = _get_services_config()
            if "services" not in services_data:
                services_data["services"] = {}

            services = services_data["services"]

            if 'danmaku' in section_data:
                services['danmaku'] = section_data['danmaku']

            if 'firewall' in section_data:
                services['firewall'] = section_data['firewall']

            if 'firewall_v3' in section_data:
                services['firewall_v3'] = section_data['firewall_v3']

            if 'vad' in section_data:
                services['vad'] = section_data['vad']

            if 'sensevoice_streaming' in section_data:
                sv_data = section_data['sensevoice_streaming']
                if 'sensevoice_streaming' not in services:
                    services['sensevoice_streaming'] = _get_default_sensevoice_config()
                for key in ['chunk_size', 'hop_size', 'look_back']:
                    if key in sv_data:
                        services['sensevoice_streaming'][key] = sv_data[key]

            if 'adaptive_polling' in section_data:
                ap_data = section_data['adaptive_polling']
                if 'adaptive_polling' not in services:
                    services['adaptive_polling'] = _get_default_adaptive_polling_config()
                for key in ['enabled', 'offset_ms', 'window_size', 'min_interval_ms', 'max_interval_ms']:
                    if key in ap_data:
                        services['adaptive_polling'][key] = ap_data[key]

            _save_services_config(services_data)
            logger.info("Live 配置已更新")
            return {"status": "success", "message": "Live config saved"}

        elif section == "vector":
            if "backend" in section_data:
                settings.config.memory.vector_backend = section_data["backend"]
            if "vector_size" in section_data:
                settings.config.memory.weaviate.vector_size = section_data["vector_size"]
            if "embedding_provider" in section_data:
                settings.config.memory.embedding_provider = section_data["embedding_provider"]
            if "embedding_model" in section_data:
                settings.config.memory.embedding_model = section_data["embedding_model"]
            if "embedding_api_base" in section_data:
                settings.config.memory.embedding_api_base = section_data["embedding_api_base"]
            if "embedding_api_key" in section_data:
                settings.config.memory.embedding_api_key = section_data["embedding_api_key"]

            settings.save_config()
            logger.info("向量配置已更新")
            return {"status": "success", "message": "Vector config saved, restart required"}

        elif section == "llm":
            if "provider" in section_data:
                settings.config.llm.provider = section_data["provider"]
            if "model" in section_data:
                settings.config.llm.model = section_data["model"]
            if "host" in section_data:
                settings.config.llm.host = section_data["host"]

            settings.save_config()
            logger.info("LLM配置已更新")
            return {"status": "success", "message": "LLM config saved, restart required"}

        elif section == "system":
            if "debug" in section_data:
                settings.config.system.debug = section_data["debug"]
            if "log_level" in section_data:
                settings.config.system.log_level = section_data["log_level"]

            settings.save_config()
            logger.info("系统配置已更新")
            return {"status": "success", "message": "System config saved"}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown section: {section}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config")
async def update_config_post(request: Request, _: bool = Depends(verify_admin_api_key)):
    """POST 方法的更新配置 - 兼容某些前端调用"""
    return await update_unified_config(request)


@router.get("/config/sensevoice-streaming")
async def get_sensevoice_streaming_config():
    """获取 SenseVoice Streaming 配置"""
    services = _get_services_config()
    sensevoice_config = services.get("services", {}).get("sensevoice_streaming", None)
    if sensevoice_config is None:
        sensevoice_config = _get_default_sensevoice_config()
    return {
        "status": "success",
        "config": sensevoice_config
    }


@router.post("/config/sensevoice-streaming")
async def update_sensevoice_streaming_config(request: SenseVoiceStreamingConfigRequest):
    """更新 SenseVoice Streaming 配置"""
    try:
        data = request.model_dump(exclude_none=True)
        services = _get_services_config()
        if "services" not in services:
            services["services"] = {}
        if "sensevoice_streaming" not in services["services"]:
            services["services"]["sensevoice_streaming"] = _get_default_sensevoice_config()

        sv_config = services["services"]["sensevoice_streaming"]
        for key in ['chunk_size', 'hop_size', 'look_back']:
            if key in data:
                sv_config[key] = data[key]

        _save_services_config(services)
        logger.info("SenseVoice Streaming 配置已更新")
        return {"status": "success", "message": "SenseVoice Streaming config saved"}
    except Exception as e:
        logger.error(f"更新 SenseVoice Streaming 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/adaptive-polling")
async def get_adaptive_polling_config():
    """获取 Adaptive Polling 配置"""
    services = _get_services_config()
    polling_config = services.get("services", {}).get("adaptive_polling", None)
    if polling_config is None:
        polling_config = _get_default_adaptive_polling_config()
    return {
        "status": "success",
        "config": polling_config
    }


@router.post("/config/adaptive-polling")
async def update_adaptive_polling_config(request: AdaptivePollingConfigRequest):
    """更新 Adaptive Polling 配置"""
    try:
        data = request.model_dump(exclude_none=True)
        services = _get_services_config()
        if "services" not in services:
            services["services"] = {}
        if "adaptive_polling" not in services["services"]:
            services["services"]["adaptive_polling"] = _get_default_adaptive_polling_config()

        ap_config = services["services"]["adaptive_polling"]
        for key in ['enabled', 'offset_ms', 'window_size', 'min_interval_ms', 'max_interval_ms']:
            if key in data:
                ap_config[key] = data[key]

        _save_services_config(services)
        logger.info("Adaptive Polling 配置已更新")
        return {"status": "success", "message": "Adaptive Polling config saved"}
    except Exception as e:
        logger.error(f"更新 Adaptive Polling 配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _load_yaml_config(filename: str) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    config_file = _PROJECT_ROOT / "config" / filename
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载配置文件 {filename} 失败: {e}")
    return {}


def _get_default_danmaku_config() -> Dict[str, Any]:
    """获取弹幕默认配置"""
    return {
        "websocket": {
            "endpoint": "/ws/live",
            "max_connections": 100
        },
        "sources": {
            "bilibili": {
                "enabled": True,
                "websocket_url": "ws://localhost:8080",
                "room_id": "12345678"
            },
            "rdf": {
                "enabled": True,
                "websocket_url": "ws://localhost:9898"
            }
        },
        "processing": {
            "max_queue_size": 100,
            "timeout_seconds": 30
        }
    }


def _get_default_firewall_config() -> Dict[str, Any]:
    """获取防火墙默认配置"""
    return {
        "llm": {
            "default_model": "qwen2.5:latest"
        },
        "blocking": {
            "blacklist": [],
            "blacklist_enabled": True
        },
        "decision": {
            "timeout_ms": 5000
        }
    }


def _get_default_firewall_v3_config() -> Dict[str, Any]:
    """获取 v3 防火墙默认配置"""
    return {
        "interrupt": {
            "enabled": True,
            "mode": "main_llm",
            "main_llm": {
                "enabled": True,
                "prompt": ""
            },
            "independent_llm": {
                "enabled": False,
                "model": "qwen2.5:1.5b",
                "endpoint": "http://localhost:11434",
                "polling_interval_ms": 1000,
                "timeout_ms": 5000
            },
            "rules": {
                "auto_reply_on_interrupt": True,
                "priority_users": []
            }
        }
    }


def _get_default_vad_config() -> Dict[str, Any]:
    """获取 VAD 默认配置"""
    return {
        "vad": {
            "mode": "webrtc",
            "sample_rate": 16000,
            "frame_duration_ms": 30,
            "energy_threshold": 500,
            "silence_threshold_ms": 500,
            "speech_threshold_ms": 300
        },
        "audio_stream": {
            "asr_interval_ms": 500,
            "buffer_duration_ms": 1000
        },
        "agent_interrupt": {
            "enabled": True,
            "interrupt_threshold_ms": 500,
            "min_speech_duration_ms": 1000,
            "interrupt_cooldown_ms": 3000
        }
    }


@router.get("/danmaku/config")
async def get_danmaku_config():
    """获取弹幕配置"""
    config = _load_yaml_config("danmaku.yaml")
    if not config:
        config = _get_default_danmaku_config()
    return {"status": "success", "config": config}


@router.get("/firewall/config")
async def get_firewall_config():
    """获取防火墙配置"""
    config = _load_yaml_config("firewall.yaml")
    if not config:
        config = _get_default_firewall_config()
    return {"status": "success", "config": config}


@router.get("/firewall/v3/config")
async def get_firewall_v3_config():
    """获取 v3 防火墙配置"""
    config = _load_yaml_config("firewall_v3.yaml")
    if not config:
        config = _get_default_firewall_v3_config()
    return {"status": "success", "config": config}


@router.get("/vad/config")
async def get_vad_config():
    """获取 VAD 配置"""
    config = _load_yaml_config("vad.yaml")
    if not config:
        config = _get_default_vad_config()
    return {"status": "success", "config": config}


@router.get("/live/client/status")
async def get_live_client_status():
    """获取直播客户端状态"""
    return {"status": "success", "config": {"status": "disabled"}}


@router.post("/live/client/{client_id}/disconnect")
async def disconnect_live_client(client_id: str):
    """断开直播客户端 WebSocket 连接"""
    ws_manager = get_websocket_manager()
    await ws_manager.disconnect(client_id)
    return {"status": "success", "message": f"客户端 {client_id} 已断开"}


@router.get("/config/audio")
async def get_audio_config():
    """获取音频配置 - 对应 Gateway 的 GET /api/config/audio"""
    from server.api.routers.audio import _load_tts_config
    config = _load_tts_config()
    return {"status": "success", "config": config}


@router.post("/config/audio")
async def update_audio_config(request: Request, _: bool = Depends(verify_admin_api_key)):
    """更新音频配置 - 对应 Gateway 的 POST /api/config/audio"""
    try:
        data = await request.json()
        config_file = _PROJECT_ROOT / "config" / "settings.json"
        config_data = {}
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception as e:
                logger.warning(f"读取服务配置失败: {e}")
        if "tts" not in config_data:
            config_data["tts"] = {}
        tts_config = config_data["tts"]
        for key in ['ref_audio_path', 'ref_text', 'speed', 'cross_fade_duration',
                     'emotion_enabled', 'effects_enabled', 'emotion_voices', 'engine']:
            if key in data:
                tts_config[key] = data[key]
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        logger.info("音频配置已更新")
        return {"status": "success", "message": "音频配置已保存"}
    except Exception as e:
        logger.error(f"更新音频配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新音频配置失败")


@router.get("/config/services")
async def get_services_config():
    """获取服务配置 - 对应 Gateway 的 GET /api/config/services"""
    services = _get_services_config()
    return {"status": "success", "config": services.get("services", {})}


@router.post("/config/services")
async def update_services_config(request: Request, _: bool = Depends(verify_admin_api_key)):
    """更新服务配置 - 对应 Gateway 的 POST /api/config/services"""
    try:
        data = await request.json()
        services_data = _get_services_config()
        if "services" not in services_data:
            services_data["services"] = {}
        services = services_data["services"]
        for key in ['danmaku', 'firewall', 'firewall_v3', 'vad', 'asr', 'tts', 'audio']:
            if key in data:
                services[key] = data[key]
        if 'sensevoice_streaming' in data:
            sv_data = data['sensevoice_streaming']
            if 'sensevoice_streaming' not in services:
                services['sensevoice_streaming'] = _get_default_sensevoice_config()
            for key in ['chunk_size', 'hop_size', 'look_back']:
                if key in sv_data:
                    services['sensevoice_streaming'][key] = sv_data[key]
        if 'adaptive_polling' in data:
            ap_data = data['adaptive_polling']
            if 'adaptive_polling' not in services:
                services['adaptive_polling'] = _get_default_adaptive_polling_config()
            for key in ['enabled', 'offset_ms', 'window_size', 'min_interval_ms', 'max_interval_ms']:
                if key in ap_data:
                    services['adaptive_polling'][key] = ap_data[key]
        _save_services_config(services_data)
        logger.info("服务配置已更新")
        return {"status": "success", "message": "服务配置已保存"}
    except Exception as e:
        logger.error(f"更新服务配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新服务配置失败")


@router.post("/config/llm")
async def update_llm_config(request: Request, _: bool = Depends(verify_admin_api_key)):
    """更新LLM配置 - 对应 Gateway 的 POST /api/config/llm"""
    from server.config import get_settings
    settings = get_settings()
    try:
        data = await request.json()
        if "provider" in data:
            settings.config.llm.provider = data["provider"]
        if "model" in data:
            settings.config.llm.model = data["model"]
        if "host" in data:
            settings.config.llm.host = data["host"]
        settings.save_config()
        logger.info("LLM配置已更新")
        return {"status": "success", "message": "LLM配置已保存，需要重启生效"}
    except Exception as e:
        logger.error(f"更新LLM配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新LLM配置失败")
