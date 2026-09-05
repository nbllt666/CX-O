"""管理面遥测采集模块（spec enhance-admin-telemetry 一）。

纯采集函数集合，不持状态（安全计数器状态在 auth.py AdminAuth 实例上）。
四组采集：runtime / connections / engines / security，经 collect_all 聚合；
单组（及单组内子项）异常一律降级 {"available": False, "error": str}，不拖垮整体快照。

psutil 采用可选 import 降级设计（psutil 不在 requirements；
注意 service.py L18 为顶层直接 import，不是可选先例，严禁照抄该模式）。
"""
import asyncio
import gc
import logging
import time
from typing import Any, Dict, Optional

# psutil 可选依赖：缺失时 CPU/内存字段为 None 并标注 "psutil": False
try:
    import psutil
except ImportError:  # pragma: no cover - 视运行环境而定
    psutil = None

logger = logging.getLogger(__name__)

# 遥测分组白名单（groups 过滤口径，与 GET /admin/telemetry?groups= 对齐）
TELEMETRY_GROUPS = ("runtime", "connections", "engines", "security")

# 进程启动近似基准：psutil 缺失时 uptime 降级为「自本模块导入起」的秒数
_MODULE_IMPORT_TS = time.time()

# psutil 进程句柄缓存：None=未探测 / False=不可用 / 其余为 psutil.Process 实例
_psutil_process: Any = None


def _degraded(error: Any) -> Dict[str, Any]:
    """统一降级形状：available=False + error 字符串。"""
    return {"available": False, "error": str(error)}


def _psutil_process_handle() -> Any:
    """惰性获取 psutil.Process 句柄；不可用时返回 False（缓存探测结论）。"""
    global _psutil_process
    if _psutil_process is None:
        if psutil is None:
            _psutil_process = False
        else:
            try:
                _psutil_process = psutil.Process()
            except Exception:  # pragma: no cover - 进程句柄获取失败按不可用处理
                _psutil_process = False
    return _psutil_process


def _collect_uptime() -> Dict[str, Any]:
    """进程存活秒数：优先 psutil.Process().create_time()，缺失降级模块导入基准。"""
    proc = _psutil_process_handle()
    if proc is not False:
        try:
            return {
                "uptime_sec": round(max(time.time() - proc.create_time(), 0.0), 1),
                "uptime_source": "psutil",
            }
        except Exception as e:  # pragma: no cover - create_time 失败走降级
            logger.debug(f"TELEMETRY: psutil uptime 读取失败: {e}")
    return {
        "uptime_sec": round(max(time.time() - _MODULE_IMPORT_TS, 0.0), 1),
        "uptime_source": "module_import",
    }


def _collect_io_pool() -> Dict[str, Any]:
    """IO 线程池摘要：max_workers / 活跃线程数 / 队列深度（私有属性 try-except）。"""
    from server.core.utils import get_io_executor

    ex = get_io_executor()
    max_workers = getattr(ex, "_max_workers", None)
    threads = getattr(ex, "_threads", None) or ()
    try:
        queue_depth: Optional[int] = ex._work_queue.qsize()
    except Exception:
        queue_depth = None
    return {
        "max_workers": max_workers,
        "active_threads": len(threads),
        "queue_depth": queue_depth,
    }


def _collect_gc() -> Dict[str, Any]:
    """gc 计数摘要：三代计数 + 各代回收统计合计。"""
    counts = gc.get_count()
    stats = gc.get_stats()
    totals = {"collections": 0, "collected": 0, "uncollectable": 0}
    for gen in stats:
        for key in totals:
            totals[key] += int(gen.get(key, 0))
    return {
        "counts": {"gen0": counts[0], "gen1": counts[1], "gen2": counts[2]},
        "totals": totals,
    }


def _collect_cpu_memory() -> Dict[str, Any]:
    """CPU%/内存：psutil 缺失时字段为 None 并标注 psutil=False。"""
    if psutil is None:
        return {"cpu_percent": None, "memory_percent": None, "psutil": False}
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_total_mb: Optional[float] = None
    try:
        # interval=None 非阻塞：返回自上次调用以来的占比（首次调用返回 0.0 或无意义值，
        # 属可接受的遥测口径；不做 interval 阻塞采样，避免拖慢快照）
        cpu_percent = psutil.cpu_percent(interval=None)
    except Exception as e:  # pragma: no cover
        logger.debug(f"TELEMETRY: cpu_percent 读取失败: {e}")
    try:
        vm = psutil.virtual_memory()
        memory_percent = getattr(vm, "percent", None)
        memory_used_mb = round(getattr(vm, "used", 0) / (1024 * 1024), 1)
        memory_total_mb = round(getattr(vm, "total", 0) / (1024 * 1024), 1)
    except Exception as e:  # pragma: no cover
        logger.debug(f"TELEMETRY: virtual_memory 读取失败: {e}")
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_mb": memory_used_mb,
        "memory_total_mb": memory_total_mb,
        "psutil": True,
    }


async def collect_runtime() -> Dict[str, Any]:
    """运行时资源组：uptime / 事件循环 lag / IO 线程池 / gc / CPU·内存。

    本函数为 async 版本：事件循环 lag 探针需在异步上下文 await 调用
    （schedule sleep 测实际延迟）；无运行中事件循环时 lag 降级 None。
    """
    data: Dict[str, Any] = {"available": True}
    try:
        data.update(_collect_uptime())
    except Exception as e:
        data["uptime"] = _degraded(e)
    # 事件循环 lag 探针：schedule sleep(10ms) 测实际延迟；非异步上下文降级 None
    try:
        loop = asyncio.get_running_loop()
        delay = 0.01
        t0 = loop.time()
        await asyncio.sleep(delay)
        data["event_loop_lag_ms"] = round(
            max((loop.time() - t0 - delay) * 1000.0, 0.0), 3
        )
    except RuntimeError:
        # 无运行中事件循环（同步测试直调场景）——lag 不可测，显式 None
        data["event_loop_lag_ms"] = None
    except Exception as e:
        data["event_loop_lag"] = _degraded(e)
    try:
        data["io_pool"] = _collect_io_pool()
    except Exception as e:
        data["io_pool"] = _degraded(e)
    try:
        data["gc"] = _collect_gc()
    except Exception as e:
        data["gc"] = _degraded(e)
    try:
        data["cpu_memory"] = _collect_cpu_memory()
    except Exception as e:
        data["cpu_memory"] = _degraded(e)
    return data


def _probe_ws_manager(services: Any) -> Any:
    """解析 ws_manager：优先 services.ws_manager 注入物，缺失回退全局单例。

    main.py 经 get_websocket_manager() 装配（ServiceState 不持 ws_manager 引用），
    故生产路径依赖单例回退；两者皆不可得返回 None（由调用方降级 available=False）。
    """
    ws = getattr(services, "ws_manager", None)
    if ws is not None:
        return ws
    try:
        from server.core.websocket.manager import get_websocket_manager

        return get_websocket_manager()
    except Exception:
        return None


def _collect_tts_semaphore(services: Any) -> Dict[str, Any]:
    """TTS in-flight 占用（事实锚点：tts_service 无显式 Queue，仅 _tts_sem 信号量）。"""
    tts = getattr(services, "tts_service", None) or getattr(services, "tts", None)
    sem = getattr(tts, "_tts_sem", None)
    if tts is None or sem is None:
        return {"available": False, "error": "tts_service/_tts_sem 未装配"}
    limit = getattr(tts, "_tts_limit", None)
    # asyncio.Semaphore 私有计数（_AlwaysAvailable 占位无 _value → in_flight=None）
    value = getattr(sem, "_value", None)
    in_flight: Optional[int] = None
    if isinstance(limit, int) and limit > 0 and isinstance(value, int):
        in_flight = max(0, min(limit, limit - value))
    return {
        "available": True,
        "limit": limit,
        "in_flight": in_flight,
        "locked": bool(sem.locked()),
    }


def collect_connections(services: Any) -> Dict[str, Any]:
    """连接与语音链路组：ws 统计 / ASR 流式会话 / VAD 状态 / TTS 占用 / 语音延迟。"""
    data: Dict[str, Any] = {"available": True}
    # 1) WebSocket 统计透传（ws_manager.get_stats()）
    try:
        ws = _probe_ws_manager(services)
        if ws is None:
            data["websocket"] = {"available": False, "error": "ws_manager 不可用"}
        else:
            stats = ws.get_stats()
            data["websocket"] = {"available": True, **dict(stats)}
    except Exception as e:
        data["websocket"] = _degraded(e)
    # 2) ASR 流式会话活跃数（_stream_sessions 注册表长度）
    try:
        asr = getattr(services, "asr_service", None)
        if asr is None:
            data["asr_stream_sessions"] = {
                "available": False, "error": "asr_service 未注入",
            }
        else:
            sessions = getattr(asr, "_stream_sessions", None)
            data["asr_stream_sessions"] = {
                "available": True,
                "active": len(sessions) if isinstance(sessions, dict) else 0,
            }
    except Exception as e:
        data["asr_stream_sessions"] = _degraded(e)
    # 3) VAD 活跃状态摘要（全局单例 VADProcessor）
    try:
        from server.services.vad_processor import VADProcessor

        vad = VADProcessor.get_instance()
        data["vad"] = {
            "available": True,
            "is_speaking": bool(vad.is_speaking),
            "speech_duration_ms": float(vad.speech_duration_ms),
        }
    except Exception as e:
        data["vad"] = _degraded(e)
    # 4) TTS 信号量占用（信号量口径，非队列深度）
    try:
        data["tts"] = _collect_tts_semaphore(services)
    except Exception as e:
        data["tts"] = _degraded(e)
    # 5) 语音链路延迟聚合（复用 T4 tracker）
    try:
        from server.core.metrics.voice_latency import get_voice_latency_tracker

        data["voice_latency"] = {
            "available": True,
            "summary": get_voice_latency_tracker().summary(),
        }
    except Exception as e:
        data["voice_latency"] = _degraded(e)
    return data


# 引擎名 → services 属性名映射（control_plane 各 target 的 services 取用口径一致）
_ENGINE_SERVICE_ATTRS = {
    "autonomy": ("autonomy_manager",),
    "dream": ("dream_engine",),
    "tuner": ("tuner",),
    "meeting": ("meeting_coordinator",),
    "cxfc": ("cxfc_manager",),
}


def _resolve_engine_service(services: Any, name: str) -> Any:
    for attr in _ENGINE_SERVICE_ATTRS[name]:
        svc = getattr(services, attr, None)
        if svc is not None:
            return svc
    return None


def _derive_running_from_status(status: Any) -> Optional[bool]:
    """从 status 枚举推导 running（disabled/stopped/paused/idle 视为未运行）。"""
    if not isinstance(status, str):
        return None
    return status not in ("disabled", "stopped", "paused", "error")


def _probe_autonomy(svc: Any) -> Dict[str, Any]:
    """autonomy：直接读 enabled/running 属性（get_status 未启用时会抛异常，不依赖）。"""
    detail: Dict[str, Any] = {}
    getter = getattr(svc, "get_status", None)
    if bool(getattr(svc, "enabled", False)) and callable(getter):
        try:
            st = getter()
            if isinstance(st, dict):
                detail.update(st)
        except Exception as e:
            detail["status_error"] = str(e)
    return {
        "enabled": bool(getattr(svc, "enabled", False)),
        "running": bool(getattr(svc, "running", False)),
        "detail": detail,
    }


def _probe_dream(svc: Any) -> Dict[str, Any]:
    """dream：get_status() 返回 {status, enabled, ...}；status=disabled 视为未运行。"""
    getter = getattr(svc, "get_status", None)
    if not callable(getter):
        raise AttributeError("dream_engine.get_status 不可用")
    st = getter()
    if not isinstance(st, dict):
        raise TypeError("dream_engine.get_status 返回非 dict")
    status = st.get("status")
    enabled = st.get("enabled")
    return {
        "enabled": bool(enabled),
        "running": bool(_derive_running_from_status(status)),
        "detail": st,
    }


def _probe_tuner(svc: Any) -> Dict[str, Any]:
    """tuner：通用探测（enabled/running 属性或 get_status/status 方法）。"""
    detail: Dict[str, Any] = {}
    enabled = getattr(svc, "enabled", None)
    running = getattr(svc, "running", None)
    if enabled is None or running is None:
        getter = getattr(svc, "get_status", None)
        if not callable(getter):
            getter = getattr(svc, "status", None)
        if callable(getter):
            st = getter()
            if isinstance(st, dict):
                detail.update(st)
                enabled = st.get("enabled") if enabled is None else enabled
                running = st.get("running") if running is None else running
                if running is None:
                    running = _derive_running_from_status(st.get("status"))
            else:
                detail["status_repr"] = str(st)
    if enabled is None:
        enabled = True  # 已装配即视为启用（无显式开关属性时）
    if running is None:
        running = enabled
    return {"enabled": bool(enabled), "running": bool(running), "detail": detail}


def _probe_meeting(svc: Any) -> Dict[str, Any]:
    """meeting：协调器无 status 方法，以活跃房间数推导 running。"""
    rooms = getattr(svc, "rooms", None)
    active_rooms = len(rooms) if isinstance(rooms, dict) else 0
    return {
        "enabled": True,  # 已装配即启用（未启用配置不会装配协调器）
        "running": active_rooms > 0,
        "detail": {"active_rooms": active_rooms},
    }


def _probe_cxfc(svc: Any) -> Dict[str, Any]:
    """cxfc：心跳任务存活推导 running；插件注册数为 detail。"""
    task = getattr(svc, "_heartbeat_task", None)
    running = False
    try:
        running = task is not None and not task.done()
    except Exception:
        running = False
    plugins = getattr(svc, "_plugins", None)
    return {
        "enabled": True,  # 已装配即启用（enabled 开关由装配流程决定）
        "running": bool(running),
        "detail": {"plugins": len(plugins) if isinstance(plugins, dict) else 0},
    }


_ENGINE_PROBES = {
    "autonomy": _probe_autonomy,
    "dream": _probe_dream,
    "tuner": _probe_tuner,
    "meeting": _probe_meeting,
    "cxfc": _probe_cxfc,
}


def collect_engines(services: Any) -> Dict[str, Any]:
    """引擎状态组：autonomy/dream/tuner/meeting/cxfc 五项统一形状。

    健康形状 {"available": True, "enabled": bool, "running": bool, "detail": dict}；
    未装配/探测异常降级 {"available": False, "enabled": False, "running": False, "error": str}。
    """
    data: Dict[str, Any] = {"available": True}
    for name in ("autonomy", "dream", "tuner", "meeting", "cxfc"):
        try:
            svc = _resolve_engine_service(services, name)
            if svc is None:
                data[name] = {
                    "available": False, "enabled": False, "running": False,
                    "error": f"{name} 未装配（services.{_ENGINE_SERVICE_ATTRS[name][0]} 为 None）",
                }
                continue
            result = _ENGINE_PROBES[name](svc)
            data[name] = {"available": True, **result}
        except Exception as e:
            data[name] = {
                "available": False, "enabled": False, "running": False,
                "error": str(e),
            }
    return data


def collect_security(services: Any) -> Dict[str, Any]:
    """安全遥测组：AdminAuth 计数器 + 最近 10 条审计事件摘要。

    审计读取复用 cluster_bridge._audit_read 同口径（反向块读，bounded）；
    本函数含文件 IO，collect_all 经 asyncio.to_thread 包裹调用。
    """
    data: Dict[str, Any] = {"available": True}
    # 1) 认证失败/限流/重放计数器
    auth = getattr(services, "admin_auth", None)
    if auth is None:
        data["counters"] = {"available": False, "error": "AdminAuth 未注入"}
    else:
        try:
            getter = getattr(auth, "get_security_counters", None)
            if not callable(getter):
                raise AttributeError("get_security_counters 不可用")
            data["counters"] = {"available": True, **dict(getter())}
        except Exception as e:
            data["counters"] = _degraded(e)
    # 2) 最近 10 条审计事件摘要（id/timestamp/actor/level/action/target/summary 字段裁剪）
    try:
        from server.core.admin.cluster_bridge import _audit_read

        items = _audit_read(10, 0) or []
        keys = ("id", "timestamp", "actor", "level", "action", "target", "summary")
        data["recent_audit"] = [
            {k: it.get(k) for k in keys if k in it}
            for it in items if isinstance(it, dict)
        ]
    except Exception as e:
        data["recent_audit"] = _degraded(e)
    return data


async def collect_all(services: Any, groups: Any = None) -> Dict[str, Any]:
    """聚合采集：groups 白名单过滤（None/空返回全部，非法组忽略），单组异常降级。

    Args:
        services: ServiceState 或等价鸭子类型容器（测试可注入替身）。
        groups: 逗号分隔字符串或可迭代分组名；None/空/全非法时按全量口径处理
            （groups 显式给值但全部非法 → 空结果，与「非法组忽略」语义一致）。

    Returns:
        {group: data} 字典；组顺序恒为 TELEMETRY_GROUPS 声明序。
    """
    if groups is None or groups == "":
        valid = list(TELEMETRY_GROUPS)
    else:
        if isinstance(groups, str):
            requested = [g.strip() for g in groups.split(",") if g.strip()]
        else:
            requested = [str(g).strip() for g in groups if str(g).strip()]
        valid = [g for g in TELEMETRY_GROUPS if g in requested]
        if not requested:
            valid = list(TELEMETRY_GROUPS)
    out: Dict[str, Any] = {}
    for g in valid:
        try:
            if g == "runtime":
                out[g] = await collect_runtime()
            elif g == "connections":
                out[g] = collect_connections(services)
            elif g == "engines":
                out[g] = collect_engines(services)
            elif g == "security":
                # 审计读取含文件 IO，经线程包裹避免卡事件循环
                out[g] = await asyncio.to_thread(collect_security, services)
        except Exception as e:
            out[g] = _degraded(e)
    return out
