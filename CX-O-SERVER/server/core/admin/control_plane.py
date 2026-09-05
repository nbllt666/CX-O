"""CX-A 统一控制入口（对齐 cx_admin.pyi AdminControlPlane 契约）。

认证/防重放/限流/权限由路由层完成；本类负责 action/target 合法性校验与分域分发。
返回结构对齐 public/schema/admin_control.schema.json。
"""
import inspect
import logging
from typing import Any, Dict

from server.core.admin.auth import AdminUnknownActionError

logger = logging.getLogger(__name__)


class AdminControlError(Exception):
    """管理面控制错误（400 语义）：白名单外字段/未知字段/参数非法/Agent 不存在等。

    与 AdminUnknownActionError（未知 target/action 枚举）区分：本类承载域内
    校验失败，消息统一携带 ADMIN_* 错误码前缀，路由层捕获后映射 HTTP 400。
    """

# 合法 target 域（对齐 admin_control.schema.json target 枚举；prompt 为提示词装配只读域）
VALID_TARGETS = frozenset(
    {"autonomy", "voice", "live", "config", "agent", "tuner", "instance", "cluster", "prompt"}
)
# 合法 action 集合（对齐 admin_control.schema.json action 枚举）
VALID_ACTIONS = frozenset(
    {
        "enable", "disable", "pause", "resume", "emergency_stop", "restart",
        "reload_config", "reload", "reset", "start", "stop", "shutdown",
        "create", "update", "delete", "preview", "topology", "state",
        "trigger_failover", "set_role", "add_peer", "remove_peer", "sync_status",
    }
)


# ---------------------------------------------------------------------------
# config.update 白名单（spec enhance-cxfc-admin-and-integrate-dream 三）：
# 仅允许 llm.{provider,model,host,port,max_tokens,temperature} 与
# models.{main,summary,memory}.{model,max_tokens,temperature,host,port}。
# 说明：llm.port 保留在白名单内与契约口径一致，但 LLMConfig 无 port 字段，
# 落点时经字段存在性校验拒绝（ADMIN_CONFIG_FIELD_UNKNOWN），保证白名单语义
# 与配置模型实际结构一致。
# ---------------------------------------------------------------------------
_CONFIG_UPDATE_WHITELIST = frozenset(
    {f"llm.{f}" for f in ("provider", "model", "host", "port", "max_tokens", "temperature")}
    | {
        f"models.{slot}.{f}"
        for slot in ("main", "summary", "memory")
        for f in ("model", "max_tokens", "temperature", "host", "port")
    }
)
# 字段轻量类型约束：数值字段（bool 是 int 子类，显式排除布尔冒充）；字符串字段
_CONFIG_NUMERIC_FIELDS = frozenset({"max_tokens", "port", "temperature"})
_CONFIG_STRING_FIELDS = frozenset({"provider", "model", "host"})


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
            if action == "update":
                # spec 三：config.update（operator 级）——白名单路径修改 llm/models 并落盘
                return self._config_update(params)
            raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: config/{action}")

        if target == "prompt":
            # spec 三：提示词装配只读域。preview 内联实现（不走 _invoke_method——
            # 预览不映射服务方法，而是委托零副作用的 build_preview_messages）。
            if action == "preview":
                from server.core.admin.prompt_preview import build_preview_messages

                return build_preview_messages(
                    agent_id=params.get("agent_id") or agent_id or "default",
                    user_message=params.get("user_message", ""),
                    history=params.get("history"),
                    is_realtime_voice=bool(params.get("is_realtime_voice", False)),
                    acp_context=params.get("acp_context"),
                    include_hidden_prompts=bool(params.get("include_hidden_prompts", True)),
                )
            raise AdminUnknownActionError(f"ADMIN_UNKNOWN_ACTION: prompt/{action}")

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

    def _config_update(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """config.update：按白名单路径修改 llm/models 配置并落盘 + 缓存失效 + 热更新判定。

        - params 为 {path: value} 扁平映射（如 {"llm.model": "qwen3",
          "models.main.max_tokens": 4096}）
        - 白名单外路径抛 AdminControlError（路由层映射 400）
        - 应用后 get_settings().save_config() 原子落盘（内部持 _CONFIG_SAVE_LOCK），
          并失效 agent_config_cache 与 prompt_builder._get_hidden_prompts lru_cache
          （spec 三：缓存失效）
        - requires_restart 按 config_hot_reload.REQUIRES_RESTART 逐节判定
          （llm=False 可热更；models 无 apply_section 热应用分支，保守登记需重启）
        """
        if not isinstance(params, dict) or not params:
            raise AdminControlError("ADMIN_CONFIG_UPDATE_EMPTY: params 需为非空 {path: value} 映射")

        from server.config import get_settings

        cfg = get_settings().config
        touched_sections = set()
        for path, value in params.items():
            if path not in _CONFIG_UPDATE_WHITELIST:
                raise AdminControlError(f"ADMIN_CONFIG_FIELD_NOT_ALLOWED: {path}（白名单外字段）")
            # 轻量类型校验：数值字段拒绝布尔冒充，字符串字段拒绝非字符串
            field = path.rsplit(".", 1)[-1]
            if field in _CONFIG_NUMERIC_FIELDS and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise AdminControlError(
                    f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为数值（temperature 可为浮点，其余为整数）"
                )
            if field in _CONFIG_STRING_FIELDS and not isinstance(value, str):
                raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为字符串")

            # 定位落点对象：llm.<field> 或 models.<slot>.<field>
            if path.startswith("llm."):
                obj = cfg.llm
            else:
                slot = path.split(".", 2)[1]
                obj = getattr(cfg.models, slot, None)
                if obj is None:
                    raise AdminControlError(f"ADMIN_CONFIG_FIELD_UNKNOWN: {path}（模型槽位不存在）")
            # 字段存在性校验：llm.port 等白名单内但配置模型无该字段的路径在此拒绝
            if not hasattr(obj, field):
                raise AdminControlError(f"ADMIN_CONFIG_FIELD_UNKNOWN: {path}（字段不存在）")
            setattr(obj, field, value)
            touched_sections.add("llm" if path.startswith("llm.") else "models")

        # 原子落盘（save_config 内部持 _CONFIG_SAVE_LOCK，同步写）
        try:
            get_settings().save_config()
        except Exception as e:
            raise AdminControlError(f"ADMIN_CONFIG_SAVE_FAILED: {e}")

        # 缓存失效 1/2：agent_config_cache（agents.json 的 all_agents 读缓存）
        try:
            from server.core.cache import agent_config_cache

            agent_config_cache.delete("all_agents")
        except Exception as e:
            logger.warning(f"ADMIN_CONTROL: agent_config_cache 失效失败: {e}")
        # 缓存失效 2/2：隐藏提示词 lru_cache（运行期视为静态，此处防御性清空）
        try:
            from server.prompt_builder import _get_hidden_prompts

            _get_hidden_prompts.cache_clear()
        except Exception as e:
            logger.warning(f"ADMIN_CONTROL: _get_hidden_prompts 缓存失效失败: {e}")

        # 热更新判定（llm=False 可热更；models 保守需重启，见 REQUIRES_RESTART 表）
        requires_restart: Dict[str, bool] = {}
        try:
            from server.config_hot_reload import REQUIRES_RESTART

            requires_restart = {
                s: bool(REQUIRES_RESTART.get(s, False)) for s in sorted(touched_sections)
            }
        except Exception as e:
            logger.warning(f"ADMIN_CONTROL: 热更新判定失败: {e}")

        return {"updated": sorted(params.keys()), "requires_restart": requires_restart}

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