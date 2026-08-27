"""CX-A 统一控制入口（对齐 cx_admin.pyi AdminControlPlane 契约）。

认证/防重放/限流/权限由路由层完成；本类负责 action/target 合法性校验与分域分发。
返回结构对齐 public/schema/admin_control.schema.json。
"""
import inspect
import logging
from typing import Any, Dict

from server.core.admin.auth import AdminUnknownActionError

logger = logging.getLogger(__name__)

# 合法 target 域（对齐 admin_control.schema.json target 枚举）
VALID_TARGETS = frozenset(
    {"autonomy", "voice", "live", "config", "agent", "tuner", "instance", "cluster"}
)
# 合法 action 集合（对齐 admin_control.schema.json action 枚举）
VALID_ACTIONS = frozenset(
    {
        "enable", "disable", "pause", "resume", "emergency_stop", "restart",
        "reload_config", "reload", "reset", "start", "stop", "shutdown",
        "create", "update", "delete", "topology", "state",
        "trigger_failover", "set_role", "add_peer", "remove_peer", "sync_status",
    }
)


def _find_method(svc, *names):
    """按候选名探测可调用方法；svc 为 None 或不含候选时返回 None。"""
    if svc is None:
        return None
    for n in names:
        m = getattr(svc, n, None)
        if callable(m):
            return m
    return None


def _accepts_agent_id(method) -> bool:
    """用 inspect.signature 判定目标方法是否接受 agent_id 参数。

    显式 ``agent_id`` 形参（任意位置类型）或 ``**kwargs``（VAR_KEYWORD 兜底）
    均视为接受；签名不可获取时不注入，保守直接调用。
    """
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD or p.name == "agent_id":
            return True
    return False


def _invoke_method(svc, *names, agent_id: str = "default", params: Dict[str, Any] = None):
    """探测并调用服务方法，返回 (found, result) 字典。

    找不到方法返回 {"unsupported": True}；svc 为空返回 {"available": False}。
    调用形态由 inspect.signature 静态判定（不接受 agent_id 时干脆不注入），
    不再用 TypeError 试错两遍——那种重试会把同一管理动作执行两次。
    """
    method = _find_method(svc, *names)
    if method is None:
        return {"available": False if svc is None else True, "unsupported": True}
    kwargs = dict(params or {})
    if agent_id and agent_id != "default" and _accepts_agent_id(method):
        kwargs.setdefault("agent_id", agent_id)
    try:
        result = method(**kwargs) if kwargs else method()
    except Exception as e:
        return {"available": True, "result": None, "error": str(e)}
    if inspect.iscoroutine(result):
        return {"available": True, "pending": True, "result": result}
    return {"available": True, "result": result}


async def resolve_invoke_result(result: Any) -> Any:
    """H1: 管理面返回体可能内嵌裸协程（_invoke_method 对 async 服务方法
    返回 {"pending": True, "result": <coroutine>}）。路由层此前对顶层判
    iscoroutine 恒 False，裸协程从未被 await → 'coroutine was never awaited'
    且无法 JSON 序列化（500）。统一在此 await 后替换，保证返回体可序列化。
    """
    if inspect.isawaitable(result):
        return await result
    if isinstance(result, dict) and inspect.iscoroutine(result.get("result")):
        resolved = await result["result"]
        result = dict(result)
        result["result"] = resolved
    return result


class AdminControlPlane:
    """统一控制入口。构造(services, auth, cluster_bridge)；auth 由路由层持有使用。"""

    def __init__(self, services, auth, cluster_bridge):
        self.services = services
        self.auth = auth
        self.cluster_bridge = cluster_bridge

    def dispatch(self, action: str, target: str, request_id: str, agent_id: str = "default", params: Dict[str, Any] = None) -> Dict[str, Any]:
        """校验 action/target 合法性后分发；未知则抛 AdminUnknownActionError。

        注：认证/权限/防重放已由路由层通过 auth.check_* 完成，本方法不再重复校验。
        """
        params = params or {}
        if target not in VALID_TARGETS or action not in VALID_ACTIONS:
            raise AdminUnknownActionError(
                f"ADMIN_UNKNOWN_ACTION: target={target}, action={action}"
            )
        try:
            result = self._execute(target, action, agent_id=agent_id, params=params)
        except AdminUnknownActionError:
            raise
        return {"action": action, "target": target, "ok": True, "result": result}

    def _execute(self, target: str, action: str, **kw) -> Dict[str, Any]:
        """按 target 分发到对应域执行器，返回域结果字典。"""
        agent_id = kw.get("agent_id", "default")
        params = kw.get("params", {}) or {}
        services = self.services

        if target == "autonomy":
            auto = getattr(services, "autonomy_manager", None) if services is not None else None
            # action 即 autonomy_manager 上的方法名（enable/disable/pause/resume/
            # emergency_stop/start/stop 等）
            return _invoke_method(auto, action, agent_id=agent_id, params=params)

        if target == "voice":
            tts = getattr(services, "tts", None) if services is not None else None
            audio = getattr(services, "audio", None) if services is not None else None
            svc = tts or audio
            return _invoke_method(svc, action, agent_id=agent_id, params=params)

        if target == "live":
            live = getattr(services, "live", None) if services is not None else None
            return _invoke_method(live, action, agent_id=agent_id, params=params)

        if target == "config":
            if action in ("reload", "reload_config", "reset"):
                try:
                    from server.config import get_settings

                    get_settings().reload_config()
                    return {"result": "config_reloaded"}
                except Exception as e:
                    logger.error(f"ADMIN_CONTROL: 配置重载失败: {e}")
                    return {"result": f"config_reload_error: {e}", "error": str(e)}
            raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: config/{action}")

        if target == "agent":
            acp = getattr(services, "acp_manager", None) if services is not None else None
            mapping = {
                "create": ("create_agent", "register_agent", "add_agent", "create"),
                "update": ("update_agent", "update"),
                "delete": ("delete_agent", "remove_agent", "unregister_agent", "delete"),
                "restart": ("restart_agent", "restart"),
            }.get(action)
            if mapping is None:
                raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: agent/{action}")
            return _invoke_method(acp, *mapping, agent_id=agent_id, params=params)

        if target == "tuner":
            tuner = getattr(services, "tuner", None) if services is not None else None
            if action not in ("start", "stop"):
                raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: tuner/{action}")
            return _invoke_method(tuner, action, agent_id=agent_id, params=params)

        if target == "instance":
            if action in ("restart", "shutdown"):
                # 实际进程级重启由路由层/进程管理承接，这里仅返回触发信号。
                return {"result": "triggered"}
            raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: instance/{action}")

        if target == "cluster":
            return self._cluster(action, params)

        raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: {target}/{action}")

    def _cluster(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """cluster 域委托 ClusterAdminBridge；未知 cluster action 抛异常。"""
        bridge = self.cluster_bridge
        if bridge is None:
            return {"result": {"status": "cluster_disabled"}}
        read_map = {
            "topology": "read_topology",
            "state": "read_state",
            "sync_status": "read_sync_status",
        }
        write_map = {
            "trigger_failover": "trigger_failover",
            "set_role": "set_role",
            "add_peer": "add_peer",
            "remove_peer": "remove_peer",
        }
        if action in read_map:
            fn = getattr(bridge, read_map[action], None)
            if not callable(fn):
                raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: cluster/{action}")
            result = fn()
            if inspect.iscoroutine(result):
                return {"result": {"pending": True, "coroutine": True}}
            return {"result": result}
        if action in write_map:
            fn = getattr(bridge, write_map[action], None)
            if not callable(fn):
                raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: cluster/{action}")
            result = fn(params)
            if inspect.iscoroutine(result):
                return {"result": {"pending": True, "coroutine": True}}
            return {"result": result}
        raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: cluster/{action}")