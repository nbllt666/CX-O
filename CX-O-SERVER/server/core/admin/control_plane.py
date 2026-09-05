"""CX-A 统一控制入口（对齐 cx_admin.pyi AdminControlPlane 契约）。

认证/防重放/限流/权限由路由层完成；本类负责 action/target 合法性校验与分域分发。
返回结构对齐 public/schema/admin_control.schema.json。
"""
import inspect
import logging
import re
from typing import Any, Dict, Set, Tuple

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
# config.update 白名单（spec enhance-admin-telemetry 三："放开所有"的安全落地）。
# 结构：节 → 允许子路径集合（两级映射；子路径可含点号表达深层路径，如
# "limits.context.chat_context_limit"、"autonomy.schedule.wake_time"）。
# - llm/models：既有字段逐字保留（spec enhance-cxfc-admin-and-integrate-dream 三）
# - limits.context/limits.memory：上下文与记忆限制标量（热生效，build_messages
#   每次读 settings）
# - logging.level：特殊即时生效钩子（落盘后 logging.getLogger().setLevel，
#   响应标注 hot_applied=true）
# - system.debug：布尔调试开关
# - executor：显式 3 字段（ExecutorConfig 实有 9 字段，其余 6 字段不放开，
#   避免通配误读），数值字段设上界防超大值（GN-004 OBS-1）
# - autonomy/dream：标量节字段（列表字段与隐私红线字段不放开；引擎运行态同步
#   走既有 PUT /autonomy/config、/dream/config 专用端点，响应附提示）
# 说明：llm.port 保留在白名单内与契约口径一致，但 LLMConfig 无 port 字段，
# 落点时经字段存在性校验拒绝（ADMIN_CONFIG_FIELD_UNKNOWN），保证白名单语义
# 与配置模型实际结构一致。
# ---------------------------------------------------------------------------
ADMIN_CONFIG_UPDATE_WHITELIST: Dict[str, Set[str]] = {
    "llm": {"provider", "model", "host", "port", "max_tokens", "temperature"},
    "models": {
        f"{slot}.{f}"
        for slot in ("main", "summary", "memory")
        for f in ("model", "max_tokens", "temperature", "host", "port")
    },
    # limits：context 7 字段 + memory 16 字段（实读 ContextLimitsConfig/
    # MemoryLimitsConfig，全部标量）
    "limits": {
        "context.max_messages", "context.window_size", "context.summary_threshold",
        "context.max_history", "context.conversation_max_messages",
        "context.conversation_recent_window", "context.chat_context_limit",
        "memory.max_memories", "memory.min_score_threshold",
        "memory.hybrid_search_limit", "memory.hybrid_search_min_score",
        "memory.vector_min_score", "memory.inject_memories_count",
        "memory.rag_search_limit", "memory.entity_extract_max_content",
        "memory.max_entities", "memory.max_relationships",
        "memory.entity_candidates", "memory.search_memories_limit",
        "memory.search_similar_threshold", "memory.search_similar_limit",
        "memory.chat_history_limit", "memory.memory_logs_limit",
    },
    # logging：仅 level（file/max_bytes 等重启语义字段不在白名单，经
    # config-whitelist 拒绝说明披露；level 走 hot_applied 即时钩子）
    "logging": {"level"},
    # system：仅 debug（host/port/workers/leader_lock_path 等结构性字段不放开）
    "system": {"debug"},
    # executor：显式 3 字段（asr_infer_workers/spk_engine_workers/spk_inflight_max/
    # tts_concurrency/tts_backpressure_mode/asr_recv_queue_maxsize 不放开）
    "executor": {"io_pool_size", "danmaku_concurrency", "interrupt_concurrency"},
    # autonomy：顶层标量 5 字段（rss_sources/platforms 为列表不放开）+ 子节标量
    # 深层路径（schedule.quiet_windows 与 permissions 列表字段不放开）
    "autonomy": {
        "enabled", "auto_start", "agent_id", "loop_interval_minutes", "store_path",
        "search.mcp_server_name", "search.fallback_rss",
        "schedule.wake_time", "schedule.sleep_time", "schedule.golden_start",
        "schedule.golden_end", "schedule.diary_time",
        "budget.daily_token_limit", "budget.daily_llm_calls_limit",
        "budget.cost_alert_threshold", "budget.overspend_mode",
        "safety.content_gate_enabled", "safety.persona_check_enabled",
        "safety.post_rate_per_hour", "safety.user_online_sleep",
        "safety.leave_mode_authorize",
    },
    # dream：顶层标量 13 字段 + 子节标量深层路径；physio.store_raw_hr 为隐私
    # 红线 R6 字段刻意排除（原始心率禁止落盘）
    "dream": {
        "enabled", "model", "dream_temperature", "candidates_per_session",
        "material_window_days", "max_material_items", "min_lucidity",
        "dream_ttl_hours", "purge_threshold", "confirmed_importance",
        "surface_on_wake", "surface_probability", "max_surface_per_day",
        "schedule.wake_time", "schedule.sleep_time", "schedule.golden_start",
        "schedule.golden_end", "schedule.diary_time",
        "physio.enabled", "physio.backend", "physio.device_name_hint",
        "physio.device_fingerprint", "physio.scan_timeout_sec",
        "physio.reconnect_interval_sec", "physio.base_drop_ratio",
        "physio.base_drop_confirm_min", "physio.hr_stability_threshold",
        "physio.base_hr_learning",
        "trigger.emotion_enabled", "trigger.emotion_threshold",
        "trigger.emotion_window_hours", "trigger.emotion_min_events",
        "trigger.probability",
        "sleep_confirmation.enabled", "sleep_confirmation.model",
        "sleep_confirmation.timeout_sec", "sleep_confirmation.prompt_template",
        "sleep_confirmation.cooldown_seconds",
    },
}
# 兼容旧名：扁平 frozenset 视图（"节.子路径" 展平），既有引用语义零变更
_CONFIG_UPDATE_WHITELIST = frozenset(
    f"{section}.{sub}"
    for section, subs in ADMIN_CONFIG_UPDATE_WHITELIST.items()
    for sub in subs
)
# 字段轻量类型约束（叶子名粒度，llm/models 既有语义）：数值字段（bool 是 int
# 子类，显式排除布尔冒充）；字符串字段
_CONFIG_NUMERIC_FIELDS = frozenset({"max_tokens", "port", "temperature"})
_CONFIG_STRING_FIELDS = frozenset({"provider", "model", "host"})
# 新增节数值上界（GN-004 OBS-1）：(父路径, 字段) → (下界, 上界) 闭区间；
# 超上界/负值统一复用既有 ADMIN_CONFIG_VALUE_TYPE 错误码
_CONFIG_NUMERIC_BOUNDS: Dict[Tuple[str, str], Tuple[float, float]] = {
    # executor：线程池/信号量上界，防超大值重启后线程爆炸/内存膨胀
    ("executor", "io_pool_size"): (0, 64),
    ("executor", "danmaku_concurrency"): (0, 256),
    ("executor", "interrupt_concurrency"): (0, 256),
    # limits.context：整数计数上界
    ("limits.context", "max_messages"): (0, 100000),
    ("limits.context", "window_size"): (0, 100000),
    ("limits.context", "summary_threshold"): (0, 100000),
    ("limits.context", "max_history"): (0, 100000),
    ("limits.context", "conversation_max_messages"): (0, 100000),
    ("limits.context", "conversation_recent_window"): (0, 100000),
    ("limits.context", "chat_context_limit"): (0, 100000),
    # limits.memory：整数计数上界
    ("limits.memory", "max_memories"): (0, 100000),
    ("limits.memory", "hybrid_search_limit"): (0, 100000),
    ("limits.memory", "inject_memories_count"): (0, 100000),
    ("limits.memory", "rag_search_limit"): (0, 100000),
    ("limits.memory", "entity_extract_max_content"): (0, 1000000),
    ("limits.memory", "max_entities"): (0, 100000),
    ("limits.memory", "max_relationships"): (0, 100000),
    ("limits.memory", "entity_candidates"): (0, 100000),
    ("limits.memory", "search_memories_limit"): (0, 100000),
    ("limits.memory", "search_similar_limit"): (0, 100000),
    ("limits.memory", "chat_history_limit"): (0, 100000),
    ("limits.memory", "memory_logs_limit"): (0, 100000),
    # limits.memory：浮点阈值（0~1 比例）
    ("limits.memory", "min_score_threshold"): (0.0, 1.0),
    ("limits.memory", "hybrid_search_min_score"): (0.0, 1.0),
    ("limits.memory", "vector_min_score"): (0.0, 1.0),
    ("limits.memory", "search_similar_threshold"): (0.0, 1.0),
    # dream：比例型标量（0~1）
    ("dream", "min_lucidity"): (0.0, 1.0),
    ("dream", "purge_threshold"): (0.0, 1.0),
    ("dream", "confirmed_importance"): (0.0, 1.0),
    ("dream", "surface_probability"): (0.0, 1.0),
    ("dream.trigger", "emotion_threshold"): (0.0, 1.0),
    ("dream.trigger", "probability"): (0.0, 1.0),
    ("dream.physio", "base_drop_ratio"): (0.0, 1.0),
    # autonomy：比例型标量（0~1）
    ("autonomy.budget", "cost_alert_threshold"): (0.0, 1.0),
}
# 日志级别枚举（对齐 spec：PUT /admin/logging/level 校验口径，大小写不敏感）
_LOGGING_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
# 日程时间字段（autonomy/dream schedule 子节共有）HH:MM 格式校验，口径对齐
# config.py _AUTONOMY_HHMM_RE（本地副本，避免跨模块私有导入）
_SCHEDULE_TIME_FIELDS = frozenset(
    {"wake_time", "sleep_time", "golden_start", "golden_end", "diary_time"}
)
_SCHEDULE_HHMM_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
# overspend_mode 枚举（对齐 AutonomyBudgetSection 校验器）
_OVERSPEND_MODES = frozenset({"sleep", "low_cost"})


def _check_new_section_value(path: str, obj: Any, field: str, value: Any) -> None:
    """新增节（limits/logging/system/executor/autonomy/dream）路径感知值守卫。

    配置模型未开启 validate_assignment，setattr 不触发字段校验器，故在落点前
    显式守卫（llm/models 维持既有叶子名校验不变，不经此函数）：
    - 类型镜像：以落点字段当前值类型为契约基准（bool/数值/字符串），拒绝越型写入
    - 数值上界：_CONFIG_NUMERIC_BOUNDS 命中时校验闭区间（负值/超大值同路径拒绝）
    - 枚举/格式：logging.level 级别枚举、schedule 时间 HH:MM、overspend_mode
      枚举（对齐 config.py 各节校验器契约，防止白名单路径绕过 PUT 专用端点校验）
    当前值为 None（Optional 字段缺省，如 dream.physio.device_fingerprint）时跳过类型镜像。
    """
    prefix = path.rsplit(".", 1)[0]
    cur = getattr(obj, field, None)
    if isinstance(cur, bool):
        if not isinstance(value, bool):
            raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为布尔值")
    elif isinstance(cur, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为数值")
        bounds = _CONFIG_NUMERIC_BOUNDS.get((prefix, field))
        if bounds is not None and not (bounds[0] <= value <= bounds[1]):
            raise AdminControlError(
                f"ADMIN_CONFIG_VALUE_TYPE: {path} 超出允许范围 [{bounds[0]}, {bounds[1]}]"
            )
    elif isinstance(cur, str):
        if not isinstance(value, str):
            raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为字符串")
    # 枚举/格式约束（契约对齐校验器语义）
    if (prefix, field) == ("logging", "level") and str(value).upper() not in _LOGGING_LEVELS:
        raise AdminControlError(
            f"ADMIN_CONFIG_VALUE_TYPE: {path} 非法日志级别，可选 {'/'.join(sorted(_LOGGING_LEVELS))}"
        )
    if (
        prefix.endswith(".schedule")
        and field in _SCHEDULE_TIME_FIELDS
        and not _SCHEDULE_HHMM_RE.match(str(value))
    ):
        raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 时间必须为 HH:MM 格式")
    if (prefix, field) == ("autonomy.budget", "overspend_mode") and value not in _OVERSPEND_MODES:
        raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 可选 sleep/low_cost")


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
        """config.update：按白名单路径修改配置并落盘 + 缓存失效 + 热更新判定。

        - params 为 {path: value} 扁平映射（如 {"llm.model": "qwen3",
          "limits.context.chat_context_limit": 20}）
        - 白名单见模块级 ADMIN_CONFIG_UPDATE_WHITELIST（节 → 子路径集合）：
          llm/models 既有域 + limits.context/limits.memory + logging.level +
          system.debug + executor 显式 3 字段 + autonomy/dream 标量深层路径
          （spec enhance-admin-telemetry 三）
        - 白名单外路径抛 AdminControlError（路由层映射 400）
        - 应用后 get_settings().save_config() 原子落盘（内部持 _CONFIG_SAVE_LOCK），
          并失效 agent_config_cache 与 prompt_builder._get_hidden_prompts lru_cache
        - requires_restart 按 config_hot_reload.REQUIRES_RESTART 逐节判定
          （executor/limits 登记为 True；logging 不登记——level 走即时钩子）
        - 即时生效钩子（ADDITIVE 响应键，不改既有键 updated/requires_restart）：
          * logging.level 落盘成功后 logging.getLogger().setLevel → hot_applied: true
            （仅该字段）
          * executor 命中 → restart_required: true（线程池/信号量装配期构建）
          * autonomy/dream 命中 → note: 引擎侧同步请调 PUT /autonomy/config |
            /dream/config 专用端点
          * limits.context/limits.memory 热生效无 ADDITIVE 标注（build_messages
            每次读 settings）
        """
        if not isinstance(params, dict) or not params:
            raise AdminControlError("ADMIN_CONFIG_UPDATE_EMPTY: params 需为非空 {path: value} 映射")

        from server.config import get_settings

        cfg = get_settings().config
        touched_sections = set()
        for path, value in params.items():
            # 白名单校验：节 → 子路径两级映射（子路径可含点号表达深层路径）
            segments = path.split(".")
            section = segments[0]
            sub = ".".join(segments[1:])
            allowed = ADMIN_CONFIG_UPDATE_WHITELIST.get(section)
            if allowed is None or sub not in allowed:
                raise AdminControlError(f"ADMIN_CONFIG_FIELD_NOT_ALLOWED: {path}（白名单外字段）")
            # 轻量类型校验（叶子名粒度，llm/models 既有语义）：数值字段拒绝布尔冒充，
            # 字符串字段拒绝非字符串
            field = segments[-1]
            if field in _CONFIG_NUMERIC_FIELDS and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise AdminControlError(
                    f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为数值（temperature 可为浮点，其余为整数）"
                )
            if field in _CONFIG_STRING_FIELDS and not isinstance(value, str):
                raise AdminControlError(f"ADMIN_CONFIG_VALUE_TYPE: {path} 需为字符串")

            # 定位落点对象：逐段 getattr 走到父对象（兼容 llm.<field>、
            # models.<slot>.<field> 既有两层路径与 limits.context.<field>、
            # autonomy.schedule.<field> 等深层路径，保持向后兼容）
            obj: Any = cfg
            for seg in segments[:-1]:
                obj = getattr(obj, seg, None)
                if obj is None:
                    raise AdminControlError(
                        f"ADMIN_CONFIG_FIELD_UNKNOWN: {path}（配置节/槽位不存在）"
                    )
            # 字段存在性校验：llm.port 等白名单内但配置模型无该字段的路径在此拒绝
            if not hasattr(obj, field):
                raise AdminControlError(f"ADMIN_CONFIG_FIELD_UNKNOWN: {path}（字段不存在）")
            # 新增节路径感知守卫（类型镜像/上界/枚举格式）；llm/models 维持既有校验
            if section not in ("llm", "models"):
                _check_new_section_value(path, obj, field, value)
            setattr(obj, field, value)
            touched_sections.add(section)

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

        # 热更新判定（按 REQUIRES_RESTART 表逐节判定；executor/limits 登记为
        # True，logging 不登记默认 False——level 走下方 hot_applied 即时钩子）
        requires_restart: Dict[str, bool] = {}
        try:
            from server.config_hot_reload import REQUIRES_RESTART

            requires_restart = {
                s: bool(REQUIRES_RESTART.get(s, False)) for s in sorted(touched_sections)
            }
        except Exception as e:
            logger.warning(f"ADMIN_CONTROL: 热更新判定失败: {e}")

        result: Dict[str, Any] = {
            "updated": sorted(params.keys()),
            "requires_restart": requires_restart,
        }

        # 即时生效钩子 1：logging.level 落盘成功后即时调整 root logger 级别
        # （spec 三：hot_applied 仅标注该字段；级别枚举已在前置守卫中校验，
        # 此处 try-except 为防御性兜底，失败时如实标注 False）
        if "logging.level" in params:
            try:
                logging.getLogger().setLevel(str(params["logging.level"]).upper())
                result["hot_applied"] = True
            except (ValueError, TypeError) as e:
                logger.warning(f"ADMIN_CONTROL: logging.level 即时生效失败: {e}")
                result["hot_applied"] = False
        # 即时生效钩子 2：executor 命中 → 便捷标注重启语义（线程池/信号量装配期构建）
        if "executor" in touched_sections:
            result["restart_required"] = True
        # 即时生效钩子 3：autonomy/dream 命中 → 引擎运行态同步提示（专用端点）
        if "autonomy" in touched_sections or "dream" in touched_sections:
            result["note"] = "引擎侧同步请调 PUT /autonomy/config | /dream/config"

        return result

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