"""对话历史管理器（ChatHistoryManager）——管理内存态对话上下文。

L-10 消歧：本模块历史上与 server/core/context/manager.py 的 ContextManager
（SQLite 持久层，sessions.db 唯一 owner）同名不同义。本类只维护内存
LRU 消息历史（单例经 get_context_manager() 获取），被 live_client /
asr_interrupt / agent_interrupt_user 消费；持久化会话请使用 core 版。
"""
from collections import OrderedDict
from typing import List, Dict

from server.config import Settings

# 会话数上限（R8）：超出后按 LRU 淘汰最久未访问的会话，防 contexts 无界增长。
# 该服务仅在事件循环内被访问（async handler / 服务单例），无跨线程共享，故不加锁。
MAX_SESSIONS = 256


class ChatHistoryManager:
    """对话历史管理器——按会话维护内存消息历史并限制最大长度（L-10 改名，原 ContextManager）。"""

    def __init__(self, max_history: int = None):
        if max_history is None:
            max_history = Settings().config.limits.context.max_history
        self.max_history = max_history
        self.contexts: "OrderedDict[str, List[Dict]]" = OrderedDict()

    def add_message(self, session_id: str, message: Dict[str, str]):
        if session_id not in self.contexts:
            self.contexts[session_id] = []
        else:
            # LRU 触碰：写访问移到末尾（最旧淘汰侧为头部）
            self.contexts.move_to_end(session_id)

        self.contexts[session_id].append(message)

        if len(self.contexts[session_id]) > self.max_history:
            self.contexts[session_id] = self.contexts[session_id][-self.max_history:]

        # LRU 淘汰：会话数超上限时淘汰最久未访问的会话（每次至多新增 1 个会话）
        if len(self.contexts) > MAX_SESSIONS:
            self.contexts.popitem(last=False)

    def add_danmaku_message(self, session_id: str, danmaku_data: Dict) -> Dict[str, str]:
        user = danmaku_data.get("user", {})
        uid = user.get("uid", "")
        username = user.get("username", "")
        content = danmaku_data.get("content", "")

        message = {
            "role": f"直播间消息 userid:{uid} username:{username}",
            "content": content
        }

        self.add_message(session_id, message)
        return message

    def get_context(self, session_id: str) -> List[Dict]:
        context = self.contexts.get(session_id)
        if context is not None:
            # LRU 触碰：读访问移到末尾
            self.contexts.move_to_end(session_id)
            return context
        return []

    def clear_context(self, session_id: str):
        if session_id in self.contexts:
            del self.contexts[session_id]


_context_manager = ChatHistoryManager()


def get_context_manager() -> ChatHistoryManager:
    """返回全局唯一的 ChatHistoryManager 单例（函数名保留，历史调用方零改动）。"""
    return _context_manager
