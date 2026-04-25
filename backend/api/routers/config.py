from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any
import json
from pathlib import Path

from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


def _get_services_config() -> Dict[str, Any]:
    """从 config/settings.json 加载服务配置"""
    config_file = Path("config/settings.json")
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_services_config(config_data: Dict[str, Any]) -> None:
    """保存服务配置到 config/settings.json"""
    config_file = Path("config/settings.json")
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


@router.get("/config")
async def get_unified_config():
    """获取统一配置 - 对应 Gateway 的 GET /api/config"""
    from backend.api.routers.audio import _load_tts_config
    from config.settings import settings

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
async def update_unified_config(request: Request):
    """更新统一配置 - 对应 Gateway 的 POST /api/config"""
    from config.settings import settings

    try:
        data = await request.json()
        section = data.get("section")
        section_data = data.get("data", {})

        if not section:
            raise HTTPException(status_code=400, detail="Missing section")

        if section == "audio":
            config_file = Path("config/settings.json")
            config_data = {}

            if config_file.exists():
                try:
                    with open(config_file, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception:
                    pass

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
async def update_config_post(request: Request):
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
async def update_sensevoice_streaming_config(request: Request):
    """更新 SenseVoice Streaming 配置"""
    try:
        data = await request.json()
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
async def update_adaptive_polling_config(request: Request):
    """更新 Adaptive Polling 配置"""
    try:
        data = await request.json()
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
