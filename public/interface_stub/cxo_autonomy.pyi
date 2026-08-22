"""CX-O-Autonomy 自主系统接口契约（embedded CXFC 插件 + 内部 REST 端点）。

所有异常契约：调用方必须处理约定的异常。
错误码枚举（统一字符串）：AUTONOMY_DISABLED / AUTONOMY_BUDGET_EXCEEDED / AUTONOMY_ACTION_BLOCKED /
AUTONOMY_CONTENT_REJECTED / AUTONOMY_RATE_LIMITED / AUTONOMY_PLATFORM_NOT_WHITELISTED / AUTONOMY_PERSIST_ERROR
"""
import datetime
from typing import Any, Dict, List, Optional

class AutonomyError(Exception):
    """自主系统基础异常。error_code 为上述错误码之一。"""
    error_code: str
    message: str

class AutonomyDisabledError(AutonomyError):
    """自主系统未启用时调用工具/端点。error_code = AUTONOMY_DISABLED"""

class AutonomyBudgetExceededError(AutonomyError):
    """当日预算超支，降级/拒绝。error_code = AUTONOMY_BUDGET_EXCEEDED"""

class AutonomyActionBlockedError(AutonomyError):
    """行动被权限白名单/黑名单拒绝。error_code = AUTONOMY_ACTION_BLOCKED"""

class AutonomyContentRejectedError(AutonomyError):
    """对外输出未过内容闸门。error_code = AUTONOMY_CONTENT_REJECTED"""

class AutonomyRateLimitedError(AutonomyError):
    """发帖/评论限速。error_code = AUTONOMY_RATE_LIMITED"""

class AutonomyPlatformNotWhitelistedError(AutonomyError):
    """平台不在白名单。error_code = AUTONOMY_PLATFORM_NOT_WHITELISTED"""

class AutonomyPersistError(AutonomyError):
    """状态/审计/记忆持久化失败。error_code = AUTONOMY_PERSIST_ERROR"""

# ---- 动作枚举 ↔ 工具注册 映射声明（消除下游歧义） ----
# 动作枚举（autonomy_action.schema.json 的 enum，9 项）是"自主循环可执行行动"全集：
#   sleep / wait 为引擎内部原语（不注册为 LLM 工具，由 autonomy_engine 直接处理）；
#   其余 read_news / search / write_memory / write_post / start_live / stop_live / write_diary
#   对应注册为下方同名自主工具（embedded CXFC 插件 tools，Python Callable）。
# 下方工具中 autonomy_get_status / autonomy_retrieve_memory 为决策辅助工具（供规划器补充上下文），
#   不属于动作枚举，不产生独立审计 action。
# control()（REST 控制面）的 action 取值 enable/disable/pause/resume/emergency_stop，
#   与控制指令语义绑定，与自主行动枚举（autonomy_action.schema.json）是两套不同枚举，勿混用。

# ---- embedded CXFC 插件工具（register_embedded_plugin("cxo-autonomy", tools=..., handlers=...)） ----
# 每个工具以 Python Callable 注册进 ToolRegistry（category="cxfc"），同步/异步均可。

def autonomy_get_status() -> Dict[str, Any]:
    """返回自主系统状态快照（对齐 autonomy_state.schema.json）。异常：AutonomyDisabledError"""

def autonomy_read_news(limit: int = 5) -> List[Dict[str, Any]]:
    """读取 RSS 新闻摘要。参数：limit 条数。返回 [{title, link, summary, published}]。"""

def autonomy_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """经 MCP 搜索（free-search-mcp）检索，不可用降级 RSS。返回 [{title, link, snippet}]。"""

def autonomy_write_memory(content: str, tags: Optional[List[str]] = None,
                          type: str = "long_term", permanent: bool = False,
                          importance: int = 3, metadata: Optional[Dict[str, Any]] = None) -> str:
    """写入自主经历到记忆库（直调 memory manager）。返回 memory_id。"""

def autonomy_retrieve_memory(query: str, limit: int = 5,
                             tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """检索记忆（人设/经历）。返回记忆列表。"""

def autonomy_write_post(platform: str, draft: str) -> Dict[str, Any]:
    """生成并发布帖子：文本→内容闸门→限速→经电脑控制浏览器自动化发布。异常：AutonomyActionBlockedError/
    AutonomyContentRejectedError/AutonomyRateLimitedError/AutonomyPlatformNotWhitelistedError。返回 {platform, status, post_id?}"""

def autonomy_start_live(script: str) -> Dict[str, Any]:
    """半自动开播：生成直播脚本等待用户确认后经 OBS/电脑控制执行。返回 {status, confirmation_required}"""

def autonomy_stop_live() -> Dict[str, Any]:
    """下播并生成直播回忆写入记忆。返回 {status, summary_memory_id}"""

def autonomy_write_diary() -> Dict[str, Any]:
    """生成每日第一人称日记并写记忆（permanent）。返回 {diary, memory_id}"""

# ---- 内部 REST 端点（前端 Agent 生活控制页调用，挂载于主服务 /api/autonomy/*） ----

def get_status() -> Dict[str, Any]:
    """GET /api/autonomy/status —— 状态/动机/预算/最近行动。"""

def control(action: str) -> Dict[str, Any]:
    """POST /api/autonomy/control —— body {"action": "enable"|"disable"|"pause"|"resume"|"emergency_stop"}。
    非法 action 返回 400。"""

def list_audit(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """GET /api/autonomy/audit —— 审计日志分页。返回 {items, total}。"""

def get_config() -> Dict[str, Any]:
    """GET /api/autonomy/config —— 当前配置（对齐 autonomy_config.schema.json）。"""

def update_config(partial: Dict[str, Any]) -> Dict[str, Any]:
    """PUT /api/autonomy/config —— 局部更新配置并自动补齐缺失字段；非法字段返回 422。"""
