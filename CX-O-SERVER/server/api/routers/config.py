"""配置管理 REST 端点——提供前端限制、运行时配置等查询与更新接口。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Any, Dict, Optional
import json
from pathlib import Path

from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.config import get_settings, atomic_write_json
from server.core.utils import deep_merge
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


def _get_services_config() -> Dict[str, Any]:
    """从 UnifiedConfig 读取运行期服务配置（收敛自 legacy config/settings.json）。

    维持对外 ``{"services": {...}}`` 响应结构兼容。当前 UnifiedConfig 仅
    ``services.sensevoice_streaming`` 节可直接映射；danmaku/firewall/firewall_v3/vad
    等节在 UnifiedConfig 尚无专有 Pydantic 模型，缺省返回空容器并交由调用方回退
    内置默认配置（后续由 s0201 补全省级契约后落地）。

    第五轮 M9：叠加 ``_save_services_config`` 落盘的 legacy 文件中的非权威节
    （danmaku/firewall/vad 等），使 POST /config/services 保存的内容可回读
    （读写自洽）；sensevoice_streaming 始终以 UnifiedConfig 为权威。
    """
    services_data: Dict[str, Any] = {"services": {}}
    try:
        cfg = get_settings().config
        sv = cfg.services.sensevoice_streaming
        if sv is not None:
            services_data["services"]["sensevoice_streaming"] = {
                "chunk_size": sv.chunk_size,
                "hop_size": sv.hop_size,
                "look_back": sv.look_back,
            }
    except Exception:
        # UnifiedConfig 不可用或无对应节时，回退为空，由调用方回退默认配置
        pass
    try:
        saved_file = _PROJECT_ROOT / "config" / "settings.json"
        if saved_file.exists():
            saved_services = json.loads(saved_file.read_text(encoding="utf-8")).get(
                "services", {}
            )
            for key in ("danmaku", "firewall", "firewall_v3", "vad", "asr", "tts", "audio"):
                if key in saved_services:
                    services_data["services"][key] = saved_services[key]
    except Exception:
        pass
    return services_data


def _save_services_config(config_data: Dict[str, Any]) -> None:
    """保存服务配置到 config/settings.json（原子写，避免半写损坏）"""
    config_file = _PROJECT_ROOT / "config" / "settings.json"
    atomic_write_json(str(config_file), config_data)


def _get_default_sensevoice_config() -> Dict[str, Any]:
    """获取 SenseVoice Streaming 默认配置（与 UnifiedConfig.SenseVoiceStreamingConfig
    缺省值对齐，第五轮 M9：old 512/4 与运行时 800/8000 不一致导致流式行为漂移）。"""
    return {
        "chunk_size": 1024,
        "hop_size": 800,
        "look_back": 8000
    }


@router.get("/config/limits")
async def get_frontend_limits():
    """获取前端限制配置"""
    settings = get_settings()
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
        }

    services_config = _get_services_config()

    vector_config = {
        # 前端约定：weaviate 后端需区分嵌入式/独立部署，映射为复合标识
        "backend": "weaviate_embedded" if settings.config.memory.weaviate.embedded else settings.config.memory.vector_backend,
        "vector_size": settings.config.memory.weaviate.vector_size,
        "weaviate_host": settings.config.memory.weaviate.host,
        "weaviate_port": settings.config.memory.weaviate.port,
        # #33（差异审查登记）: 已移除陈旧 chroma 字面量（data/chroma_db /
        # memory_vectors）——真实后端为 weaviate，旧值会误导前端/管理端。
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
                # 各模型槽位（main/summary/memory）的完整配置，供前端设置页回显
                "models": {
                    key: {
                        "provider": getattr(mc, "provider"),
                        "model": getattr(mc, "model"),
                        "host": getattr(mc, "host"),
                        # 用户裁决（20260828_模块0_GETconfig回显apikey.md）：明文回显
                        "api_key": getattr(mc, "api_key", None) or "",
                    }
                    for key, mc in (
                        ("main", settings.config.models.main),
                        ("summary", settings.config.models.summary),
                        ("memory", settings.config.models.memory),
                    )
                },
                # 类型映射默认值（如 {"summary": "main", "memory": "main"}）
                "defaults": dict(settings.config.models.defaults),
                # 采样参数（取自主模型配置）
                "params": {
                    "temperature": settings.config.models.main.temperature,
                    "maxTokens": settings.config.models.main.max_tokens,
                    "topP": getattr(settings.config.models.main, "top_p", None),
                    "timeout": settings.config.models.main.timeout,
                },
            },
            "system": {
                "debug": settings.config.system.debug,
                "log_level": settings.config.system.log_level,
            },
            "live": services_config.get("services", {})
        }
    }


async def _apply_and_broadcast(request: Request, section: str, section_data: Dict[str, Any]) -> Dict[str, Any]:
    """配置节保存后：应用热更新并广播变更事件。

    Returns:
        {"applied": bool, "requires_restart": bool}
    """
    from server.config_hot_reload import apply_section, broadcast_config_changed

    model_router = getattr(getattr(request.app.state, "services", None), "model_router", None)
    result = await apply_section(section, section_data, model_router)
    await broadcast_config_changed(get_websocket_manager(), section, result["requires_restart"])
    return result


async def _apply_llm_section(request: Request, section_data: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 配置节核心落盘逻辑（C6：PUT /config llm 分支与 legacy POST /config/llm 共用）。

    前端提交的 models 结构（main/summary/memory）映射到 config.models，
    使 ModelRouter.reload_clients() 能按新配置重建客户端（热更新真实生效）。
    """
    from server.config import get_settings
    settings = get_settings()

    models_data = section_data.get("models")
    if isinstance(models_data, dict):
        for key in ("main", "summary", "memory"):
            entry = models_data.get(key)
            if not isinstance(entry, dict):
                continue
            model_cfg = getattr(settings.config.models, key, None)
            if model_cfg is None:
                continue
            if "provider" in entry:
                model_cfg.provider = entry["provider"]
            if "model" in entry:
                model_cfg.model = entry["model"]
            if "host" in entry:
                model_cfg.host = entry["host"]
            if "api_key" in entry:
                # 空字符串归一化为 None，避免配置文件残留空密钥
                model_cfg.api_key = entry["api_key"] or None

    # model_defaults：summary/memory 的类型映射默认值（如 {"summary": "main"}）
    model_defaults = section_data.get("model_defaults")
    if isinstance(model_defaults, dict):
        defaults = dict(settings.config.models.defaults)
        for key in ("summary", "memory"):
            if key in model_defaults:
                defaults[key] = model_defaults[key]
        settings.config.models.defaults = defaults

    # llm_params：采样参数同时落到 llm 节与 models.main，供前端与客户端共用
    llm_params = section_data.get("llm_params")
    if isinstance(llm_params, dict):
        if "temperature" in llm_params:
            settings.config.llm.temperature = llm_params["temperature"]
            settings.config.models.main.temperature = llm_params["temperature"]
        if "maxTokens" in llm_params:
            settings.config.llm.max_tokens = llm_params["maxTokens"]
            settings.config.models.main.max_tokens = llm_params["maxTokens"]
        if "topP" in llm_params:
            settings.config.models.main.top_p = llm_params["topP"]
        if "timeout" in llm_params:
            settings.config.models.main.timeout = llm_params["timeout"]

    if "provider" in section_data:
        settings.config.llm.provider = section_data["provider"]
    if "model" in section_data:
        settings.config.llm.model = section_data["model"]
    if "host" in section_data:
        settings.config.llm.host = section_data["host"]

    settings.save_config()
    logger.info("LLM配置已更新")
    return await _apply_and_broadcast(request, "llm", section_data)


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
                       'emotion_enabled', 'effects_enabled']:
                if key in section_data:
                    tts_config[key] = section_data[key]

            try:
                atomic_write_json(str(config_file), config_data)
            except Exception as e:
                logger.warning(f"保存音频配置到文件失败: {e}")

            logger.info("音频配置已更新")
            result = await _apply_and_broadcast(request, section, section_data)
            return {"status": "success", "message": "Audio config saved", **result}

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

            _save_services_config(services_data)
            logger.info("Live 配置已更新")
            result = await _apply_and_broadcast(request, section, section_data)
            return {"status": "success", "message": "Live config saved", **result}

        elif section == "vector":
            if "backend" in section_data:
                # 前端复合标识映射：weaviate_embedded 拆解为 weaviate 后端 + embedded 开关
                backend = section_data["backend"]
                if backend == "weaviate_embedded":
                    settings.config.memory.vector_backend = "weaviate"
                    settings.config.memory.weaviate.embedded = True
                else:
                    settings.config.memory.vector_backend = backend
                    if backend == "weaviate":
                        settings.config.memory.weaviate.embedded = False
            if "weaviate_host" in section_data:
                settings.config.memory.weaviate.host = section_data["weaviate_host"]
            if "weaviate_port" in section_data:
                settings.config.memory.weaviate.port = int(section_data["weaviate_port"])
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
            result = await _apply_and_broadcast(request, section, section_data)
            return {"status": "success", "message": "Vector config saved", **result}

        elif section == "llm":
            # C6: 核心落盘逻辑抽至 _apply_llm_section，与 legacy POST /config/llm 同轨
            result = await _apply_llm_section(request, section_data)
            return {"status": "success", "message": "LLM config saved", **result}

        elif section == "system":
            if "debug" in section_data:
                settings.config.system.debug = section_data["debug"]
            if "log_level" in section_data:
                settings.config.system.log_level = section_data["log_level"]

            settings.save_config()
            logger.info("系统配置已更新")
            result = await _apply_and_broadcast(request, section, section_data)
            return {"status": "success", "message": "System config saved", **result}

        elif section == "graph":
            if "graph_enabled" in section_data:
                settings.config.graph.enabled = bool(section_data["graph_enabled"])

            settings.save_config()
            logger.info("图数据库配置已更新")
            result = await _apply_and_broadcast(request, section, section_data)
            return {"status": "success", "message": "Graph config saved", **result}

        elif section == "vision_enhanced":
            if "enabled" in section_data:
                settings.config.vision_enhanced.enabled = bool(section_data["enabled"])

            settings.save_config()
            logger.info("视觉增强配置已更新")
            result = await _apply_and_broadcast(request, section, section_data)
            return {"status": "success", "message": "Vision enhanced config saved", **result}

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
async def update_sensevoice_streaming_config(
    request: SenseVoiceStreamingConfigRequest,
    _: bool = Depends(verify_admin_api_key),
):
    """更新 SenseVoice Streaming 配置（需管理员鉴权）"""
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


def _load_yaml_config(filename: str) -> Dict[str, Any]:
    """从已保存的 config/settings.json 读取对应 live 节（收敛自 legacy config/*.yaml）。

    返回该节已保存的原始 dict；从未保存过则返回 {}，由调用方深合并到内置默认之上
    （「已保存值叠加默认值」，而非恒返回默认）。文件名映射到 services 键：
    ``danmaku.yaml -> services.danmaku``、``firewall.yaml -> services.firewall`` 等。
    """
    key = filename.rsplit(".", 1)[0]  # "danmaku.yaml" -> "danmaku"
    try:
        saved_file = _PROJECT_ROOT / "config" / "settings.json"
        if saved_file.exists():
            services = json.loads(saved_file.read_text(encoding="utf-8")).get("services", {})
            value = services.get(key)
            if isinstance(value, dict):
                return value
    except Exception:
        pass
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
            "interrupt_cooldown_ms": 3000,
            "speech_end_fallback": False,
            "question_intent_required": True,
            "reply_on_final_question": True
        }
    }


@router.get("/danmaku/config")
async def get_danmaku_config():
    """获取弹幕配置（已保存值叠加默认值）"""
    config = deep_merge(
        _get_default_danmaku_config(), _load_yaml_config("danmaku.yaml")
    )
    return {"status": "success", "config": config}


@router.get("/firewall/config")
async def get_firewall_config():
    """获取防火墙配置（已保存值叠加默认值）"""
    config = deep_merge(
        _get_default_firewall_config(), _load_yaml_config("firewall.yaml")
    )
    return {"status": "success", "config": config}


@router.get("/firewall/v3/config")
async def get_firewall_v3_config():
    """获取 v3 防火墙配置（已保存值叠加默认值）"""
    config = deep_merge(
        _get_default_firewall_v3_config(), _load_yaml_config("firewall_v3.yaml")
    )
    return {"status": "success", "config": config}


@router.get("/vad/config")
async def get_vad_config():
    """获取 VAD 配置（已保存值叠加默认值）"""
    config = deep_merge(
        _get_default_vad_config(), _load_yaml_config("vad.yaml")
    )
    return {"status": "success", "config": config}


@router.get("/live/client/status")
async def get_live_client_status():
    """获取直播客户端状态

    查询 `ws_manager.connections` 中标记为 ``type == "live"`` 的真实直播 WebSocket 连接
    （由 /ws/live 端点建立），返回前端断线状态所需的 connected/client_id 字段。
    """
    ws_manager = get_websocket_manager()
    live_clients = [
        cid
        for cid, conn in ws_manager.connections.items()
        if conn.metadata.get("type") == "live"
    ]
    if live_clients:
        return {"status": "connected", "connected": True, "client_id": live_clients[0]}
    return {"status": "disconnected", "connected": False, "client_id": None}


@router.post("/live/client/{client_id}/disconnect")
async def disconnect_live_client(client_id: str, _: bool = Depends(verify_admin_api_key)):
    """断开直播客户端 WebSocket 连接（C5: 控制类端点需管理员鉴权）"""
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
                     'emotion_enabled', 'effects_enabled', 'engine']:
            if key in data:
                tts_config[key] = data[key]
        atomic_write_json(str(config_file), config_data)
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
