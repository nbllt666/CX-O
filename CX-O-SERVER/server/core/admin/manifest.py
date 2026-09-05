"""CX-A 运行时自描述能力清单（对齐 cx_admin.pyi AdminManifest 契约；返回结构对齐
public/schema/admin_manifest.schema.json）。
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 本实例支持的统一控制动作集合（对齐 admin_control.schema.json action 枚举）。
CONTROL_ACTIONS = [
    "enable",
    "disable",
    "pause",
    "resume",
    "emergency_stop",
    "restart",
    "reload_config",
    "reload",
    "reset",
    "start",
    "stop",
    "shutdown",
    "create",
    "update",
    "delete",
    # prompt 域只读动作（提示词装配预览，spec enhance-cxfc-admin-and-integrate-dream 三）
    "preview",
]

ENDPOINTS = {"ws": "/ws", "health": "/api/health", "cluster": "/api/cluster"}


class AdminManifest:
    """运行时动态生成自描述能力清单（含集群块）。"""

    def __init__(self, services, admin_cfg):
        self.services = services
        self.admin_cfg = admin_cfg

    def build(self, cluster_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """组装完整 manifest。cluster_state 缺省按 \"{enabled: False}\" 处理。"""
        cluster_state = cluster_state if isinstance(cluster_state, dict) else {"enabled": False}

        node_name = ""
        if self.admin_cfg is not None:
            node_name = getattr(self.admin_cfg, "node_name", "") or getattr(
                self.admin_cfg, "name", ""
            ) or ""
        instance_id = ""
        if self.services is not None:
            candidate = getattr(self.services, "instance_id", None) or getattr(
                self.services, "node_id", None
            )
            instance_id = candidate or ""
        if not instance_id and self.admin_cfg is not None:
            instance_id = getattr(self.admin_cfg, "instance_id", "") or ""

        return {
            "instance_id": instance_id,
            "node_name": node_name or "cx-o-node",
            "version": "1.0.0",
            "capabilities": self.detect_capabilities(),
            "control_actions": list(CONTROL_ACTIONS),
            "agents": self.detect_agents(),
            "plugins": self.detect_plugins(),
            "models": self.detect_models(),
            "endpoints": dict(ENDPOINTS),
            "cluster": dict(cluster_state),
        }

    def detect_agents(self) -> list:
        """从 services.acp_manager 探测 Agent 列表；不可用返回空列表。"""
        acp = getattr(self.services, "acp_manager", None) if self.services is not None else None
        if acp is None:
            return []
        try:
            agents = getattr(acp, "agents", None)
            if isinstance(agents, dict) and agents:
                return [
                    getattr(a, "agent_id", None) or iid
                    for iid, a in agents.items()
                ]
            if isinstance(agents, (list, tuple)) and agents:
                return [getattr(a, "agent_id", None) or str(a) for a in agents]
            # agents 为空/非容器时退回 list_agents()
            list_fn = getattr(acp, "list_agents", None)
            if callable(list_fn):
                result = list_fn(online_only=False)
                if isinstance(result, list):
                    out = []
                    for a in result:
                        if isinstance(a, dict):
                            out.append(a.get("agent_id") or a.get("id") or "")
                        else:
                            out.append(getattr(a, "agent_id", None) or str(a))
                    return [x for x in out if x]
            return []
        except Exception as e:  # pragma: no cover - 探测失败降级为空
            logger.warning(f"ADMIN_MANIFEST: 探测 agents 失败: {e}")
            return []

    def detect_plugins(self) -> list:
        """从 services.cxfc_manager get_plugins() 取 plugin_id；不可用返回空列表。"""
        cxfc = getattr(self.services, "cxfc_manager", None) if self.services is not None else None
        if cxfc is None:
            return []
        try:
            getter = getattr(cxfc, "get_plugins", None)
            if not callable(getter):
                return []
            plugins = getter()
            out = []
            for p in plugins or []:
                if isinstance(p, dict):
                    out.append(p.get("plugin_id") or p.get("id") or "")
                else:
                    out.append(getattr(p, "plugin_id", None) or getattr(p, "id", None) or "")
            return [x for x in out if x]
        except Exception as e:  # pragma: no cover
            logger.warning(f"ADMIN_MANIFEST: 探测 plugins 失败: {e}")
            return []

    def detect_capabilities(self) -> Dict[str, bool]:
        """布尔探测 services 各组件是否就绪。"""
        svc = self.services
        tts = getattr(svc, "tts", None) or getattr(svc, "tts_service", None) if svc is not None else None
        audio = getattr(svc, "audio", None) if svc is not None else None
        return {
            "realtime_voice": tts is not None or audio is not None,
            "autonomy": getattr(svc, "autonomy_manager", None) is not None if svc is not None else False,
            "tuner": False,
            "live_stream": getattr(svc, "live", None) is not None if svc is not None else False,
            "computer_control": getattr(svc, "cxfc_manager", None) is not None if svc is not None else False,
            "vision": getattr(svc, "multimodal", None) is not None if svc is not None else False,
            # 管理接口增强（spec enhance-cxfc-admin-and-integrate-dream 三）：
            # prompt.preview（readonly 预览）与 model-context 读写（operator）
            # 端点随 admin 面启用即可用，不依赖 services 组件就绪
            "prompt_preview": True,
            "model_context": True,
            # 管理面遥测增强（spec enhance-admin-telemetry 一/四）：
            # telemetry 聚合查看、config-whitelist 边界回显（readonly）、
            # logging-level 热调（operator）——端点随 admin 面启用即可用
            "telemetry": True,
            "config_whitelist": True,
            "logging_level": True,
        }

    def detect_models(self) -> Dict[str, str]:
        """从 model_router 取 main/summary/memory 模型标识；不可用返回空 dict。"""
        mr = getattr(self.services, "model_router", None) if self.services is not None else None
        if mr is None:
            return {}
        result: Dict[str, str] = {}
        for slot in ("main", "summary", "memory"):
            value = None
            getter = getattr(mr, f"get_{slot}", None)
            if callable(getter):
                try:
                    value = getter()
                except Exception as e:  # pragma: no cover
                    value = None
            elif callable(getattr(mr, "get_model_info", None)):
                try:
                    info = mr.get_model_info(slot)
                    if isinstance(info, dict):
                        value = info.get("model") or info.get("name")
                    elif hasattr(info, "model"):
                        value = info.model
                except Exception:  # pragma: no cover
                    value = None
            if value:
                result[slot] = str(value)
        return result