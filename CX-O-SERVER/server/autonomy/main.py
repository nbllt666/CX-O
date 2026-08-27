"""CX-O-Autonomy 自主系统 embedded CXFC 插件装配入口。

setup_autonomy 加载配置并按 enabled 决定是否装配完整 P1 组件（感知/规划/行动/
反思/安全）与 AutonomyEngine 主循环，注册为 embedded CXFC 插件（plugin_id 前缀
embedded_）并 start 引擎。所有异常被捕获并记录日志，不影响主服务启动（异常隔离）。
import 本模块不依赖任何"实现模块"（post / live 等 P2/P3 能力），缺失时不会崩溃。
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from server.autonomy.config import load_config
from server.autonomy.manager import AutonomyDisabledError, AutonomyError, AutonomyManager

logger = logging.getLogger(__name__)

AUTONOMY_PLUGIN_ID = "cxo-autonomy"
AUTONOMY_PLUGIN_NAME = "CX-O-Autonomy"
AUTONOMY_CAPABILITIES = ["autonomy", "search", "memory", "post", "live"]

# 模块级单例（get_autonomy_manager 读取）
_autonomy_manager: Optional[AutonomyManager] = None
# P1 组件单例（由 setup_autonomy 装配，供 get_handlers 的真实 handler 使用）
_autonomy_engine: Optional[Any] = None
_rss_fetcher: Optional[Any] = None
_memory_actions: Optional[Any] = None
_diary_generator: Optional[Any] = None
_search_monitor: Optional[Any] = None
_audit_store: Optional[Any] = None
# P2-T3：发帖器单例（由 setup_autonomy 装配，供 get_handlers 的 write_post handler 使用）
_poster: Optional[Any] = None
# P3-T2：经历整合器单例（由 setup_autonomy 装配，注入真实蒸馏服务 provider）
_consolidator: Optional[Any] = None
# P3-T1：直播器单例（由 setup_autonomy 装配，供 get_handlers 的 start_live/stop_live handler 使用）
_streamer: Optional[Any] = None
# Dream 梦境引擎单例（由 setup_autonomy 在 dream.enabled 时装配，供 dream 工具 handler 使用）
_dream_engine: Optional[Any] = None


def get_autonomy_manager() -> Optional[AutonomyManager]:
    """返回模块级单例 AutonomyManager（未装配返回 None）。"""
    return _autonomy_manager


def get_audit_store() -> Optional[Any]:
    """返回模块级单例 AuditStore（未装配返回 None）。

    供 REST 路由（server/api/routers/autonomy.py）注入审计日志存储。
    """
    return _audit_store


# ---------------------------------------------------------------------------
# 工具描述（注册进 embedded CXFC 插件 ToolRegistry，参数为 JSON Schema object）
# 参数契约对齐 public/interface_stub/cxo_autonomy.pyi 各工具签名。
# ---------------------------------------------------------------------------
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "autonomy_get_status",
        "description": (
            "返回 CX-O-Autonomy 自主系统状态快照（状态/动机/预算/最近行动），"
            "对齐 autonomy_state.schema.json。未启用抛 AutonomyDisabledError。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "autonomy_read_news",
        "description": "读取 RSS 新闻摘要。返回 [{title, link, summary, published}]。",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5, "minimum": 1}},
        },
    },
    {
        "name": "autonomy_search",
        "description": (
            "经 MCP 搜索（free-search-mcp）检索信息，搜索不可用时降级 RSS。"
            "返回 [{title, link, snippet}]。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "default": 5, "minimum": 1},
            },
            "required": ["query"],
        },
    },
    {
        "name": "autonomy_write_memory",
        "description": "写入自主经历到记忆库（直调 memory manager）。返回 memory_id。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "记忆内容"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "type": {"type": "string", "default": "long_term"},
                "permanent": {"type": "boolean", "default": False},
                "importance": {"type": "integer", "default": 3, "minimum": 0},
                "metadata": {"type": "object"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "autonomy_retrieve_memory",
        "description": "检索自主系统记忆（人设/经历）。返回记忆列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索查询"},
                "limit": {"type": "integer", "default": 5, "minimum": 1},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        },
    },
    {
        "name": "autonomy_write_post",
        "description": (
            "生成并发布帖子：文本→内容闸门→限速→经电脑控制浏览器自动化发布。"
            "返回 {platform, status, post_id?}。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "目标平台（weibo/x/bilibili/xiaohongshu 等）"},
                "draft": {"type": "string", "description": "帖子草稿文本"},
            },
            "required": ["platform", "draft"],
        },
    },
    {
        "name": "autonomy_start_live",
        "description": (
            "半自动开播：生成直播脚本等待用户确认后经 OBS/电脑控制执行。"
            "返回 {status, confirmation_required}。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"script": {"type": "string", "description": "直播脚本"}},
        },
    },
    {
        "name": "autonomy_stop_live",
        "description": "下播并生成直播回忆写入记忆。返回 {status, summary_memory_id}。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "autonomy_write_diary",
        "description": "生成每日第一人称日记并写记忆（permanent）。返回 {diary, memory_id}。",
        "parameters": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Dream 工具描述（dream.enabled 时并入 cxo-autonomy 插件 ToolRegistry，参数为 JSON Schema object）
# ---------------------------------------------------------------------------
DREAM_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "dream_get_status",
        "description": (
            "返回 CX-O-Dream 梦境引擎运行状态快照（status/enabled/last_session_at/stats）。"
            "未启用返回 {\"status\": \"disabled\"}，不抛错。"
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "dream_trigger",
        "description": (
            "手动触发一轮梦境会话（采集边缘记忆→summary 模型低温联想生成→D7 确定性闸门"
            "过滤→缓冲隔离）。返回 {status, last_session_at, result} 统计；未启用不抛错。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "default": "default", "description": "Agent ID"},
            },
        },
    },
    {
        "name": "dream_list",
        "description": (
            "分页列出梦境候选缓冲（按 decision 过滤：pending/approved/rejected，缺省全部）。"
            "返回缓冲候选列表；未启用返回空列表。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "description": "过滤决策（pending/approved/rejected），缺省全部"},
                "limit": {"type": "integer", "default": 50, "minimum": 1},
                "offset": {"type": "integer", "default": 0, "minimum": 0},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# 技能描述（注册进 SkillRegistry）
# ---------------------------------------------------------------------------
SKILL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "autonomy_loop",
        "description": (
            "CX-O-Autonomy 自主循环：按动机/预算/日程周期性地执行 读新闻→搜索→写记忆→"
            "发帖→直播→写日记 等自主行动序列，并记录审计日志。"
        ),
        "prompt_template": "",
        "trigger_keywords": ["自主循环", "自主行动", "autonomy_loop", "自动生活", "agent 生活"],
        "trigger_events": [],
        "auto_inject": False,
    }
]


# ---------------------------------------------------------------------------
# 工具 handlers
# ---------------------------------------------------------------------------
def _autonomy_get_status() -> Dict[str, Any]:
    """真实实现：返回自主系统状态快照（未启用抛 AutonomyDisabledError）。"""
    mgr = get_autonomy_manager()
    if mgr is None:
        raise AutonomyDisabledError("自主系统未启用")
    return mgr.get_status()


def _today_local_date() -> str:
    """返回本地（系统时区）今日日期 YYYY-MM-DD。

    H12: 与引擎审计时间戳基准统一——审计条目已改为
    datetime.now().astimezone() 本地带偏移时间戳，此处日期来源同步改为
    astimezone()，避免硬编码 UTC+8 与机器时区漂移时错位。
    """
    return datetime.now().astimezone().date().isoformat()


def _entry_in_local_day(entry: Dict[str, Any], day_prefix: str) -> bool:
    """判断审计条目时间戳是否属于本地指定日（H12 跨时区归一）。

    - 带 tz 的 ISO 时间戳（含历史 UTC 条目）：先转本地时区再比较日期，
      保证本地 00:00–07:59 生成的条目按本地日归档不再丢失；
    - 无 tz 的朴素时间戳：按其自身日期判定（与旧日期前缀语义等价）；
    - 无法解析的条目回退日期前缀匹配。
    """
    ts = str(entry.get("timestamp", "") or "")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return ts.startswith(day_prefix)
    if dt.tzinfo is None:
        return dt.date().isoformat() == day_prefix
    return dt.astimezone().date().isoformat() == day_prefix


def _today_daily_log() -> List[Dict[str, Any]]:
    """从审计存储取今日全部条目（供日记生成器使用）。"""
    store = _audit_store
    if store is None:
        return []
    try:
        page = store.list(limit=None)
    except Exception as e:
        logger.warning("读取审计日志失败: %s", e)
        return []
    items = page.get("items", []) if isinstance(page, dict) else []
    if not isinstance(items, list):
        return []
    day = _today_local_date()
    return [entry for entry in items if isinstance(entry, dict) and _entry_in_local_day(entry, day)]


async def _autonomy_read_news(limit: int = 5) -> List[Dict[str, Any]]:
    """真实实现：经 RssFetcher 读取 RSS 新闻摘要。"""
    fetcher = _rss_fetcher
    if fetcher is None:
        return []
    try:
        items = await fetcher.fetch()
    except Exception as e:
        logger.warning("读取 RSS 新闻失败: %s", e)
        return []
    n = max(int(limit or 5), 1)
    return (items or [])[:n]


async def _autonomy_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """真实实现：经 HotspotMonitor 搜索；不可用/无结果时降级 RSS（fallback_rss）。"""
    n = max(int(limit or 5), 1)
    monitor = _search_monitor
    if monitor is not None:
        try:
            results = await monitor.get_hotspots([str(query)], limit=n)
            if results:
                return results[:n]
        except Exception as e:
            logger.warning("搜索失败，降级 RSS: %s", e)
    return await _autonomy_read_news(limit=n)


async def _autonomy_write_memory(
    content: str,
    tags: Optional[List[str]] = None,
    type: str = "long_term",
    permanent: bool = False,
    importance: int = 3,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """真实实现：经 MemoryActions 写入记忆，返回 memory_id。"""
    actions = _memory_actions
    if actions is None:
        raise AutonomyError("记忆组件未装配", error_code="AUTONOMY_PERSIST_ERROR")
    result = await actions.write_memory(
        content=content,
        tags=tags,
        type=type,
        permanent=permanent,
        importance=importance,
        metadata=metadata,
    )
    if isinstance(result, dict):
        raise AutonomyError(
            str(result.get("error") or "memory_write_failed"),
            error_code="AUTONOMY_PERSIST_ERROR",
        )
    return str(result)


async def _autonomy_retrieve_memory(
    query: str,
    limit: int = 5,
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """真实实现：经 MemoryActions 检索记忆。"""
    actions = _memory_actions
    if actions is None:
        return []
    result = await actions.retrieve_memory(
        query=query, limit=max(int(limit or 5), 1), tags=tags
    )
    return result if isinstance(result, list) else []


async def _autonomy_write_diary() -> Dict[str, Any]:
    """真实实现：经 DiaryGenerator 生成今日日记并写记忆（permanent）。"""
    gen = _diary_generator
    if gen is None:
        return {"diary": "", "memory_id": None, "error": "diary_generator 未装配"}
    daily_log = _today_daily_log()
    try:
        return await gen.generate_diary(daily_log, date=_today_local_date())
    except Exception as e:
        logger.warning("日记生成失败: %s", e)
        return {"diary": "", "memory_id": None, "error": str(e)}


# ---------------------------------------------------------------------------
# P2-T3: 发帖行动（autonomy_write_post 真实 handler + 电脑控制调用器装配）
# ---------------------------------------------------------------------------
# 电脑控制插件稳定工具名（对齐 public/schema/computer_control_plugin.schema.json）
_COMPUTER_CONTROL_TOOLS = {"computer_keyboard_control", "computer_run_command"}


def _build_computer_control(cxfc_manager: Any) -> Optional[Callable]:
    """查找已注册的电脑控制插件并构造电脑控制调用器（P2-T3）。

    识别方式：插件 tools 同时含 computer_keyboard_control 与 computer_run_command
    （电脑控制契约三稳定工具之二）即视为电脑控制插件；未找到返回 None，发帖走
    prepared 未执行态（等待执行器接入）。

    返回的调用器签名 computer_control(script) -> dict，可同步/异步：逐步骤调
    cxfc_manager.call_tool(plugin_id, tool, arguments)，返回
    {"plugin_id": ..., "steps": [{"tool", "result"}]}。
    """
    if cxfc_manager is None:
        return None
    plugin = None
    for p in cxfc_manager.get_plugins():
        tools = getattr(p, "tools", None) or []
        names = {str(t.get("name", "")) for t in tools if isinstance(t, dict)}
        if _COMPUTER_CONTROL_TOOLS <= names:
            plugin = p
            break
    if plugin is None:
        logger.info("未找到电脑控制插件，发帖将返回 prepared 未执行态")
        return None
    plugin_id = plugin.plugin_id

    async def _computer_control(script: List[Dict[str, Any]]) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        for step in script or []:
            tool = str(step.get("tool", "") or "") if isinstance(step, dict) else ""
            if tool not in _COMPUTER_CONTROL_TOOLS:
                continue
            arguments = step.get("arguments") if isinstance(step, dict) else None
            result = await cxfc_manager.call_tool(plugin_id, tool, arguments or {})
            steps.append({"tool": tool, "result": result})
        return {"plugin_id": plugin_id, "steps": steps}

    return _computer_control


async def _autonomy_write_post(
    platform: str,
    draft: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """真实实现：经 Poster 生成并发布帖子（白名单→生成→闸门→限速→电脑控制）。

    异常（不吞，由调用方/引擎捕获记审计）：AutonomyPlatformNotWhitelistedError /
    AutonomyContentRejectedError / AutonomyRateLimitedError；发帖器未装配抛
    AutonomyDisabledError。
    """
    poster = _poster
    if poster is None:
        raise AutonomyDisabledError("自主系统未启用或发帖器未装配")
    return await poster.post(platform=platform, draft=draft, context=context)


async def _autonomy_start_live(script: str = "") -> Dict[str, Any]:
    """真实实现：经 Streamer 半自动开播（生成脚本→确认门→OBS 开播）。

    script 为空时先按人设生成直播脚本再进确认门；异常（不吞）由调用方/引擎
    捕获记审计；直播器未装配抛 AutonomyDisabledError。
    """
    streamer = _streamer
    if streamer is None:
        raise AutonomyDisabledError("自主系统未启用或直播器未装配")
    if script and str(script).strip():
        script_obj: Dict[str, Any] = {"script": str(script)}
    else:
        script_obj = await streamer.prepare_script()
    return await streamer.start_live(script=script_obj)


async def _autonomy_stop_live() -> Dict[str, Any]:
    """真实实现：经 Streamer 下播并写入直播回忆记忆。"""
    streamer = _streamer
    if streamer is None:
        raise AutonomyDisabledError("自主系统未启用或直播器未装配")
    return await streamer.stop_live()


def _build_dream_ws_sender(ws_manager: Any) -> Optional[Callable]:
    """构造梦境主动提起推送回调（DreamConsolidator.ws_sender）。

    经 ws_manager.broadcast 推送完整 WS 消息（type=dream.surface 等，对齐
    server/protocol/actions.py 的 DreamActions 约定）；ws_manager 缺失或无
    broadcast 方法时返回 None（surface 仅记日志，不阻断）。
    """
    if ws_manager is None:
        return None
    broadcast = getattr(ws_manager, "broadcast", None)
    if not callable(broadcast):
        return None

    async def _sender(message: Dict[str, Any]) -> None:
        await broadcast(message)

    return _sender


# ---------------------------------------------------------------------------
# Dream 工具 handlers（并入 cxo-autonomy 插件；未启用时优雅返回 disabled，不抛错）
# ---------------------------------------------------------------------------
def _dream_get_status() -> Dict[str, Any]:
    """真实实现：返回梦境引擎状态快照（未启用返回 disabled，不抛错）。"""
    engine = _dream_engine
    if engine is None:
        return {
            "status": "disabled",
            "enabled": False,
            "last_session_at": None,
            "stats": {},
        }
    return engine.get_status()


async def _dream_trigger(agent_id: str = "default") -> Dict[str, Any]:
    """真实实现：手动触发一轮梦境会话（采集→联想生成→D7 闸门过滤→缓冲隔离）。"""
    engine = _dream_engine
    if engine is None:
        return {"status": "disabled", "detail": "梦境引擎未启用"}
    result = await engine.run_session(agent_id=agent_id or "default")
    status = engine.get_status()
    return {
        "status": status.get("status", "idle"),
        "last_session_at": status.get("last_session_at"),
        "result": result,
    }


def _dream_list(
    decision: Optional[str] = None, limit: int = 50, offset: int = 0
) -> List[Dict[str, Any]]:
    """真实实现：读取梦境候选缓冲（未启用返回空列表，不抛错）。"""
    engine = _dream_engine
    if engine is None:
        return []
    buffer = getattr(engine, "_buffer", None)
    if buffer is None:
        return []
    try:
        return buffer.list(
            agent_id="default",
            decision=decision,
            limit=max(int(limit or 50), 1),
            offset=max(int(offset or 0), 0),
        )
    except Exception as e:
        logger.warning("梦境候选缓冲读取失败: %s", e)
        return []


def get_handlers() -> Dict[str, Callable]:
    """返回 {工具名: handler} 映射。

    P1 已接线：autonomy_get_status / autonomy_read_news / autonomy_search /
    autonomy_write_memory / autonomy_retrieve_memory / autonomy_write_diary；
    P2-T3 已接线：autonomy_write_post（经 Poster 发帖）；
    P3-T1 已接线：autonomy_start_live / autonomy_stop_live（经 Streamer 半自动直播）；
    Dream（dream.enabled 时）已接线：dream_get_status / dream_trigger / dream_list。
    """
    handlers: Dict[str, Callable] = {
        "autonomy_get_status": _autonomy_get_status,
        "autonomy_read_news": _autonomy_read_news,
        "autonomy_search": _autonomy_search,
        "autonomy_write_memory": _autonomy_write_memory,
        "autonomy_retrieve_memory": _autonomy_retrieve_memory,
        "autonomy_write_diary": _autonomy_write_diary,
        "autonomy_write_post": _autonomy_write_post,
        "autonomy_start_live": _autonomy_start_live,
        "autonomy_stop_live": _autonomy_stop_live,
    }
    # Dream 引擎启用时合并 dream 工具 handler（dream disabled 零侵入）
    if _dream_engine is not None:
        handlers["dream_get_status"] = _dream_get_status
        handlers["dream_trigger"] = _dream_trigger
        handlers["dream_list"] = _dream_list
    return handlers


# ---------------------------------------------------------------------------
# P2-T1: MCP 搜索 provider（配置驱动的 MCP 工具接入自主搜索）
# ---------------------------------------------------------------------------
def _tool_attr(tool: Any, field: str) -> str:
    """从 Tool 对象或 dict 中读取字段（兼容两种表示），缺失返回空串。"""
    if isinstance(tool, dict):
        return str(tool.get(field) or "")
    return str(getattr(tool, field, None) or "")


def _find_mcp_search_tool(registry: Any) -> Optional[str]:
    """从工具注册表查找 mcp 类搜索工具名。

    条件：category=="mcp" 且工具名（小写）含 "search"（如 free-search-mcp 提供
    的 web_search）。未找到返回 None。
    """
    if registry is None:
        return None
    try:
        tools = registry.list_tools(enabled_only=True, include_builtin=False)
    except Exception as e:
        logger.warning("读取工具注册表失败: %s", e)
        return None
    for tool in tools or []:
        name = _tool_attr(tool, "name").lower()
        category = _tool_attr(tool, "category").lower()
        if category == "mcp" and "search" in name:
            return _tool_attr(tool, "name")
    return None


def _normalize_search_results(raw: Any) -> Optional[List[Dict[str, str]]]:
    """将 MCP 搜索工具原始返回归一化为 [{title, link, snippet}]；无法归一化返回 None。

    兼容 dict（取 results/data/items/result 键）与 list 两种返回形态。
    """
    items = raw
    if isinstance(raw, dict):
        for key in ("results", "data", "items", "result"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                break
    if not isinstance(items, list):
        return None
    normalized: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": str(item.get("title") or item.get("name") or ""),
                "link": str(item.get("link") or item.get("url") or item.get("href") or ""),
                "snippet": str(
                    item.get("snippet")
                    or item.get("summary")
                    or item.get("description")
                    or ""
                ),
            }
        )
    return normalized or None


def _build_mcp_search_provider(registry: Any, mcp_manager: Any = None) -> Optional[Callable]:
    """构造 MCP 搜索 provider。

    注册表存在 mcp 类搜索工具时返回 provider（入参 query）。执行路径：
    优先经 MCPManager.call_tool(server_name, tool_name, {"query": query}) 走真实
    MCP 服务端点（MCP 工具注册于 ToolRegistry 时 function=None，无法经
    tool_registry.call_tool 执行）；mcp_manager 缺失时回退 registry.call_tool
    （测试/降级用）。结果归一化为 [{title, link, snippet}]；不存在/调用失败/
    无结果时返回 None，触发 HotspotMonitor 降级 RSS。
    """
    tool_name = _find_mcp_search_tool(registry)
    if tool_name is None:
        return None
    logger.info("CX-O-Autonomy 注入 MCP 搜索工具: %s", tool_name)

    # 从注册表工具 tags 推断归属 MCP server 名（_sync_tools 以 tags=[server_name] 注册）
    server_name: Optional[str] = None
    if mcp_manager is not None:
        try:
            for tool in registry.list_tools(enabled_only=True, include_builtin=False) or []:
                if _tool_attr(tool, "name") == tool_name:
                    # tags 是 list（Tool dataclass 字段），不能经 _tool_attr（会 str 化）
                    tags = tool.get("tags") if isinstance(tool, dict) else getattr(tool, "tags", None)
                    if isinstance(tags, list) and tags:
                        server_name = tags[0]
                    break
        except Exception as e:
            logger.warning("解析 MCP 搜索工具归属 server 失败: %s", e)

    async def _provider(query: str) -> Optional[List[Dict[str, str]]]:
        try:
            if mcp_manager is not None and server_name:
                result = await mcp_manager.call_tool(server_name, tool_name, {"query": query})
            else:
                # 回退路径：优先 call_tool_async（支持 async handler；缺失时回退同步 call_tool）
                _call_async = getattr(registry, "call_tool_async", None)
                if _call_async is not None:
                    result = await _call_async(tool_name, {"query": query})
                else:
                    result = registry.call_tool(tool_name, {"query": query})
        except Exception as e:
            logger.warning("MCP 搜索调用失败 %s: %s", tool_name, e)
            return None
        if not isinstance(result, dict) or not result.get("success"):
            logger.warning("MCP 搜索调用未成功: %s", tool_name)
            return None
        return _normalize_search_results(result.get("result"))

    return _provider


async def _safe_stop_after_assembly_error(dream_engine: Any, engine: Any) -> None:
    """装配异常时尽力停止已启动的引擎（防泄漏），并避免二次异常遮蔽原始异常。

    - 对 awaitable/sync 的 stop 均兼容（AutonomyEngine.stop 为 async，DreamEngine.stop 为 sync）；
    - 每个对象独立 try/except 包裹，单个 stop 失败不影响其余；
    - 对未启动对象幂等（stop 内部对 None task 安全），None 与无可调用 stop 者跳过。
    """
    for obj in (dream_engine, engine):
        if obj is None:
            continue
        stop = getattr(obj, "stop", None)
        if not callable(stop):
            continue
        try:
            result = stop()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("装配异常后的引擎停止也失败（已隔离，不再遮蔽原始异常）")


async def setup_autonomy(services: Any, store_path: str = "") -> Optional[AutonomyManager]:
    """装配 CX-O-Autonomy 自主系统（embedded CXFC 插件 + P1 主循环引擎）。

    加载配置；enabled=False 返回 None；否则基于 services 提供 model_router
    get_client("main")、memory manager、firewall 等真实服务，装配完整 P1 组件与
    AutonomyEngine，注册 embedded 插件并 start 引擎。任何异常被捕获记录日志并
    返回 None（异常隔离，不影响主服务启动）。P1 组件 import 均在函数内延迟执行，
    避免循环 import。
    """
    global _autonomy_manager, _autonomy_engine, _rss_fetcher, _memory_actions
    global _diary_generator, _search_monitor, _audit_store, _poster, _streamer
    global _consolidator, _dream_engine
    _autonomy_manager = None
    _autonomy_engine = None
    _rss_fetcher = None
    _memory_actions = None
    _diary_generator = None
    _search_monitor = None
    _audit_store = None
    _poster = None
    _streamer = None
    _consolidator = None
    _dream_engine = None
    try:
        config = load_config(store_path=store_path)
        if not config.enabled:
            logger.info("CX-O-Autonomy 未启用（config.enabled=False），跳过装配")
            return None

        cxfc = getattr(services, "cxfc_manager", None)
        if cxfc is None:
            logger.warning("services.cxfc_manager 不可用，CX-O-Autonomy 装配跳过")
            return None

        # ---- 延迟 import P1 组件（避免循环 import） ----
        from server.autonomy.action.content.memory_actions import MemoryActions
        from server.autonomy.config import resolve_store_dir
        from server.autonomy.core.loop.autonomy_engine import AutonomyEngine
        from server.autonomy.core.motivation.state import MotivationState
        from server.autonomy.core.planner.action_planner import ActionPlanner
        from server.autonomy.core.scheduler.circadian import CircadianScheduler
        from server.autonomy.perception.env.context_sensor import ContextSensor
        from server.autonomy.perception.news.rss_fetcher import RssFetcher
        from server.autonomy.perception.social.hotspot_monitor import HotspotMonitor
        from server.autonomy.reflection.consolidator import Consolidator
        from server.autonomy.reflection.diary.generator import DiaryGenerator
        from server.autonomy.reflection.feedback.evaluator import (
            FeedbackEvaluator,
            make_tuner_provider,
        )
        from server.autonomy.safety.audit import AuditStore
        from server.autonomy.safety.budget.token_ledger import TokenLedger
        from server.autonomy.safety.gate.content_gate import ContentGate
        from server.autonomy.safety.killswitch import KillSwitch
        from server.autonomy.safety.ratelimit.limiter import RateLimiter
        from server.core.websocket.manager import get_websocket_manager

        store_dir = store_path or resolve_store_dir()

        # ---- 基于 services 解析真实服务依赖 ----
        llm_client = None
        model_router = getattr(services, "model_router", None)
        if model_router is not None and hasattr(model_router, "get_client"):
            try:
                llm_client = model_router.get_client("main")
            except Exception as e:
                logger.warning("获取主模型客户端失败: %s", e)
        memory_manager = getattr(services, "memory_manager", None)

        firewall = None
        try:
            from server.services.firewall import get_firewall_service

            firewall = get_firewall_service()
        except Exception as e:
            logger.warning("获取防火墙服务失败: %s", e)

        # ---- 组装 P1 组件（模块级单例供 get_handlers 使用） ----
        _rss_fetcher = RssFetcher(urls=list(config.rss_sources))
        _memory_actions = MemoryActions(
            memory_manager=memory_manager, agent_id=config.agent_id
        )
        persona: Dict[str, Any] = {
            "system_prompt": (
                "你是一个温柔细腻、富有好奇心的自主数字生命（CX-O 自主体），"
                "热爱学习、观察与表达，以第一人称记录生活与思考。"
            ),
            "description": "CX-O 自主体",
        }

        async def _memory_provider(context: Dict[str, Any]) -> str:
            """规划器记忆注入 provider：检索最近相关记忆摘要（失败静默降级空串）。"""
            try:
                memories = await _memory_actions.retrieve_memory(
                    query=str((context or {}).get("phase", "")), limit=3
                )
                if memories:
                    return json.dumps(memories, ensure_ascii=False, default=str)
            except Exception as e:
                logger.warning("规划器记忆注入失败: %s", e)
            return ""

        planner = ActionPlanner(
            llm_client=llm_client,
            persona=persona,
            allowed_actions=list(config.permissions.allowed_actions),
            blocked_actions=list(config.permissions.blocked_actions),
            memory_provider=_memory_provider,
        )
        _diary_generator = DiaryGenerator(
            llm_client=llm_client, memory_actions=_memory_actions, persona=persona
        )
        # P2-T1: 注入 MCP 搜索 provider（services.tool_registry 优先，缺失回退全局
        # tool_registry；services.mcp_manager 提供真实执行路径，缺失回退 registry）。
        # 存在 mcp 类搜索工具时 search_provider 经 MCPManager 调用归一化返回；不存在/
        # 调用失败时 search_provider=None，HotspotMonitor 返回 [] → _autonomy_search
        # handler 降级 RSS。
        search_registry = getattr(services, "tool_registry", None)
        if search_registry is None:
            try:
                from server.core.tools.registry import tool_registry as _global_tool_registry

                search_registry = _global_tool_registry
            except Exception as e:
                logger.warning("加载全局工具注册表失败: %s", e)
                search_registry = None
        search_mcp_manager = getattr(services, "mcp_manager", None)
        _search_monitor = HotspotMonitor(
            search_provider=_build_mcp_search_provider(search_registry, search_mcp_manager),
            fallback=None,
        )

        _audit_store = AuditStore(path=str(Path(store_dir) / "audit_logs.jsonl"))
        token_ledger = TokenLedger(
            daily_token_limit=config.budget.daily_token_limit,
            daily_llm_calls_limit=config.budget.daily_llm_calls_limit,
            cost_alert_threshold=config.budget.cost_alert_threshold,
            overspend_mode=config.budget.overspend_mode,
            store_path=str(Path(store_dir) / "token_ledger.json"),
        ).load()
        content_gate = ContentGate(
            firewall=firewall, enabled=config.safety.content_gate_enabled
        )
        rate_limiter = RateLimiter(limit_per_hour=config.safety.post_rate_per_hour)

        # P2-T3：装配发帖器（白名单/人设/闸门/限速 + 电脑控制调用器），供
        # get_handlers 的 autonomy_write_post handler 使用。电脑控制插件未注册时
        # computer_control=None，发帖返回 prepared 未执行态（等待执行器接入）。
        from server.autonomy.action.social.poster import Poster

        _poster = Poster(
            llm_client=llm_client,
            content_gate=content_gate,
            rate_limiter=rate_limiter,
            platforms=list(config.platforms),
            computer_control=_build_computer_control(cxfc),
            persona=persona,
        )

        # P3-T1：装配直播器（半自动直播：生成脚本→确认门→OBS 开播→下播写回忆）。
        # confirmation_callback 缺省 None=半自动等待用户在前端确认（P4 前端接线）；
        # computer_control 复用 _build_computer_control（电脑控制插件未注册时为 None，
        # 开播/下播走 prepared/stopped 未执行态）。
        from server.autonomy.action.live.streamer import Streamer

        _streamer = Streamer(
            llm_client=llm_client,
            memory_actions=_memory_actions,
            computer_control=_build_computer_control(cxfc),
            persona=persona,
        )

        # P3-T2：装配经历整合器（注入真实蒸馏服务实例，经 services.distillation_service
        # 注入；未注入时蒸馏 provider 为 None，consolidate 走占位统计路径）。
        distillation_service = getattr(services, "distillation_service", None)
        _consolidator = Consolidator(distillation_service=distillation_service)
        if distillation_service is not None:
            logger.info("CX-O-Autonomy 注入真实蒸馏服务 provider")
        else:
            logger.info("CX-O-Autonomy 未注入蒸馏服务（占位整合路径）")

        killswitch = KillSwitch(
            store_path=str(Path(store_dir) / "killswitch.json")
        ).load()
        sensor = ContextSensor()
        circadian = CircadianScheduler(config.schedule.model_dump())
        manager = AutonomyManager(config)

        # ---- CX-O-Dream 梦境引擎（并入 cxo-autonomy 插件；dream.enabled=false 零侵入） ----
        # 加载独立 DreamConfig（不并入 UnifiedConfig / config_hot_reload，见 spec Frozen
        # Decision 2）；enabled 时延迟 import dream 模块，构建引擎组件并挂载模块级单例
        # 供 dream 工具 handler 使用。任何异常被捕获隔离，不影响 autonomy 插件装配。
        dream_config = None
        dream_engine = None
        physio_runtime = None
        try:
            from server.autonomy.dream.config import load_config as _dream_load_config

            dream_config = _dream_load_config(store_path=store_path)
        except Exception as e:
            logger.warning("Dream 配置加载失败，梦境引擎跳过（不影响 autonomy 装配）: %s", e)
            dream_config = None
        # 休眠前确认仲裁器：默认 None，仅 dream 启用时装配；在外层作用域初始化，
        # 保证 dream 分支未进入时下方 `services.confirmation_arbiter` 也能安全引用（None）。
        confirmation_arbiter = None
        if dream_config is not None and dream_config.enabled:
            try:
                from server.autonomy.dream.buffer import DreamBuffer
                from server.autonomy.dream.collector import DreamMaterialCollector
                from server.autonomy.dream.consolidator import DreamConsolidator
                from server.autonomy.dream.engine import DreamEngine
                from server.autonomy.dream.filter import DreamFilter
                from server.autonomy.dream.generator import DreamGenerator
                from server.autonomy.dream.purge import DreamPurgeJob

                ws_manager = getattr(services, "ws_manager", None) or get_websocket_manager()
                dream_buffer = DreamBuffer(config=dream_config)

                # ---- Physio 生理信号组件（Task 4：SleepSensor + 估计器 + 运行时容器） ----
                # 装配 physio 组件并注入 DreamEngine（sleep_sensor 确认入睡触发）；任何
                # physio 异常被捕获隔离，不影响 autonomy/dream 装配（引擎保持纯时间窗口）。
                sleep_sensor = None
                sleep_sensor_refresh = None
                physio_runtime = None
                try:
                    from server.autonomy.dream.physio.estimator import (
                        HeartRateSleepEstimator,
                    )
                    from server.autonomy.dream.physio.runtime import PhysioRuntime
                    from server.autonomy.dream.physio.store import PhysioSignalStore
                    from server.autonomy.dream.sleep_sensor import (
                        SleepSensor,
                        wire_sleep_sensor,
                    )

                    physio_store = PhysioSignalStore()
                    physio_estimator = HeartRateSleepEstimator(
                        config=dream_config.physio, store=physio_store
                    )
                    sleep_sensor = SleepSensor()
                    # 初始接线：S7 时间先验 + S9 心率（估计器窗口有真实样本时刷新）
                    wire_sleep_sensor(
                        sensor=sleep_sensor,
                        circadian=circadian,
                        estimator=physio_estimator,
                    )

                    def _refresh_sleep_sensor(_now: Optional[datetime] = None) -> None:
                        """每轮刷新 SleepSensor：S9 心率置信度 + S7 时间先验（异常隔离）。"""
                        _now = _now or datetime.now()
                        if physio_estimator is not None:
                            try:
                                est = physio_estimator.get_state()
                                if est.get("window_size", 0) > 0:
                                    sleep_sensor.set_hr_confidence(
                                        est.get("hr_sleep_confidence", 0.0)
                                    )
                            except Exception as e:
                                logger.warning("心率置信度刷新失败（S9 降级）: %s", e)
                        if circadian is not None:
                            try:
                                sleep_sensor.set_time_prior(_now, circadian)
                            except Exception as e:
                                logger.warning("时间先验刷新失败（S7 降级）: %s", e)

                    sleep_sensor_refresh = _refresh_sleep_sensor
                    physio_runtime = PhysioRuntime(
                        estimator=physio_estimator,
                        store=physio_store,
                        sleep_sensor=sleep_sensor,
                        dream_config=dream_config,
                    )
                    logger.info(
                        "CX-O-Dream 生理信号组件已装配（physio.enabled=%s）",
                        dream_config.physio.enabled,
                    )
                except Exception as e:
                    logger.exception(
                        "CX-O-Dream 生理信号组件装配失败，已隔离（梦境引擎保持纯时间窗口）: %s",
                        e,
                    )
                    sleep_sensor = None
                    sleep_sensor_refresh = None
                    physio_runtime = None

                # ---- 休眠前 LLM 确认仲裁器（入睡意图二次仲裁），异常隔离不影响睡眠体系 ----
                # 注入 services.llm_client（chat(...) 返回带 .content 的对象）；未装配时
                # approve_sleep 按 fail-open 放行。config 读 DreamConfig.sleep_confirmation。
                confirmation_arbiter = None
                try:
                    from server.autonomy.dream.confirmation import (
                        SleepConfirmationArbiter,
                    )

                    confirmation_arbiter = SleepConfirmationArbiter(
                        llm_client=getattr(services, "llm_client", None) or None,
                        config=dream_config.sleep_confirmation,
                    )
                    logger.info(
                        "休眠前确认仲裁器已装配（enabled=%s, model=%s）",
                        dream_config.sleep_confirmation.enabled,
                        dream_config.sleep_confirmation.model,
                    )
                except Exception as e:
                    logger.warning(
                        "休眠前确认仲裁器装配失败，已隔离（approve_sleep 将 fail-open）: %s",
                        e,
                    )
                    confirmation_arbiter = None

                # ---- 入睡首步自动摘要（休眠确认通过后第一步固化；装配失败不影响主链路） ----
                auto_summarizer = None
                try:
                    from server.autonomy.dream.summarizer import (
                        SleepAutoSummarizer,
                    )

                    auto_summarizer = SleepAutoSummarizer(
                        context_manager=getattr(services, "context_manager", None) or None,
                        memory_manager=memory_manager,
                        llm_client=getattr(services, "llm_client", None) or None,
                        config=dream_config,
                    )
                    logger.info("入睡首步自动摘要组件已装配")
                except Exception as e:
                    logger.warning(
                        "入睡首步自动摘要装配失败，已隔离（入睡直接进，零回归）: %s",
                        e,
                    )
                    auto_summarizer = None

                dream_engine = DreamEngine(
                    collector=DreamMaterialCollector(
                        memory_manager=memory_manager,
                        graph_repo=getattr(services, "graph_repo", None),
                        config=dream_config,
                    ),
                    generator=DreamGenerator(
                        model_router=model_router, config=dream_config
                    ),
                    dream_filter=DreamFilter(),
                    buffer=dream_buffer,
                    consolidator=DreamConsolidator(
                        buffer=dream_buffer,
                        memory_manager=memory_manager,
                        config=dream_config,
                        ws_sender=_build_dream_ws_sender(ws_manager),
                    ),
                    purge_job=DreamPurgeJob(
                        memory_manager=memory_manager,
                        buffer=dream_buffer,
                        config=dream_config,
                        ws_manager=ws_manager,
                    ),
                    config=dream_config,
                    ws_manager=ws_manager,
                    sleep_sensor=sleep_sensor,
                    sleep_sensor_refresh=sleep_sensor_refresh,
                    sleep_confirm_arbiter=confirmation_arbiter,
                    auto_summarizer=auto_summarizer,
                )
                _dream_engine = dream_engine
                logger.info(
                    "CX-O-Dream 梦境引擎组件已装配（enabled=True，将并入 cxo-autonomy 插件）"
                )
            except Exception as e:
                logger.exception(
                    "CX-O-Dream 梦境引擎装配失败，已隔离（不影响 autonomy 装配）: %s", e
                )
                dream_engine = None
                _dream_engine = None

        engine = AutonomyEngine(
            manager=manager,
            motivation=MotivationState(),
            circadian=circadian,
            sensor=sensor,
            rss=_rss_fetcher,
            hotspot=_search_monitor,
            memory_actions=_memory_actions,
            planner=planner,
            diary=_diary_generator,
            evaluator=FeedbackEvaluator(tuner_provider=make_tuner_provider()),
            token_ledger=token_ledger,
            content_gate=content_gate,
            rate_limiter=rate_limiter,
            killswitch=killswitch,
            audit=_audit_store,
            handlers=get_handlers(),
            persona=persona,
            ws_manager=get_websocket_manager(),
            loop_interval_minutes=config.loop_interval_minutes,
        )

        # ---- Dream 工具/能力/处理器并入 cxo-autonomy 插件（dream.enabled 时追加） ----
        plugin_tools: List[Dict[str, Any]] = TOOL_SPECS
        plugin_capabilities: List[str] = AUTONOMY_CAPABILITIES
        if dream_config is not None and dream_config.enabled:
            plugin_tools = TOOL_SPECS + DREAM_TOOL_SPECS
            plugin_capabilities = AUTONOMY_CAPABILITIES + ["dream"]

        await cxfc.register_embedded_plugin(
            plugin_id=AUTONOMY_PLUGIN_ID,
            name=AUTONOMY_PLUGIN_NAME,
            tools=plugin_tools,
            skills=SKILL_SPECS,
            capabilities=plugin_capabilities,
            handlers=get_handlers(),
        )
        manager.enable()
        _autonomy_manager = manager
        _autonomy_engine = engine
        manager.engine = engine  # 运行时附加，便于停止（不改 manager.py）
        services.autonomy_manager = manager
        services.autonomy_engine = engine
        # Dream 引擎启动与挂载（dream.enabled 时；start() 为同步创建后台昼夜循环任务）
        if dream_engine is not None:
            dream_engine.start()
            services.dream_engine = dream_engine
            logger.info("CX-O-Dream 梦境引擎已挂载为 embedded 插件能力并启动后台循环")
        # Physio 生理信号运行时容器挂载（供 /api/physio/* 路由注入；未装配时 None 降级）
        services.physio_runtime = physio_runtime
        # 休眠前确认仲裁器 + sleep_sensor 挂载到 services（供聊天唤醒检测等消费）
        services.confirmation_arbiter = confirmation_arbiter
        if physio_runtime is not None and getattr(physio_runtime, "sleep_sensor", None) is not None:
            services.sleep_sensor = physio_runtime.sleep_sensor
        await engine.start()
        logger.info(
            "CX-O-Autonomy 已装配为 embedded CXFC 插件（%s）并启动主循环",
            f"embedded_{AUTONOMY_PLUGIN_ID}",
        )
        return manager
    except Exception as e:
        # 装配中途异常：先尽力停止已启动的后台引擎（防泄漏），再记日志返回 None。
        # 清理本身用 try/except 包裹，避免二次异常遮蔽原始异常。
        try:
            await _safe_stop_after_assembly_error(dream_engine, engine)
        except Exception:
            logger.exception("装配异常后的引擎清理失败")
        logger.exception("CX-O-Autonomy 装配失败，已隔离（不影响主服务启动）: %s", e)
        return None
