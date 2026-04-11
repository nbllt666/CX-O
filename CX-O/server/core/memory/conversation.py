from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class ConversationType(Enum):
    CHAT = "chat"
    TASK = "task"
    QUESTION = "question"
    CREATIVE = "creative"


@dataclass
class Message:
    role: str
    content: str
    message_id: str = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict = field(default_factory=dict)


@dataclass
class ConversationContext:
    session_id: str
    conversation_type: ConversationType = ConversationType.CHAT
    topic: str = ""
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    message_count: int = 0
    summary: str = ""
    metadata: Dict = field(default_factory=dict)


class ConversationManager:
    def __init__(self, storage_path: str = "data/conversations.json"):
        self.storage_path = storage_path
        self._contexts: Dict[str, ConversationContext] = {}
        self._messages: Dict[str, List[Message]] = {}

    def create_conversation(
        self, session_id: str, conversation_type: ConversationType = ConversationType.CHAT
    ) -> ConversationContext:
        context = ConversationContext(session_id=session_id, conversation_type=conversation_type)
        self._contexts[session_id] = context
        self._messages[session_id] = []
        logger.info(f"创建会话: session_id={session_id}, type={conversation_type.value}")
        return context

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_id: str = None,
        metadata: Dict = None,
    ) -> Message:
        if session_id not in self._contexts:
            self.create_conversation(session_id)

        message = Message(
            role=role,
            content=content,
            message_id=message_id,
            metadata=metadata or {},
        )

        self._messages[session_id].append(message)
        self._contexts[session_id].message_count += 1
        self._contexts[session_id].last_updated = datetime.now().isoformat()

        return message

    def get_conversation(self, session_id: str) -> Optional[ConversationContext]:
        return self._contexts.get(session_id)

    def get_messages(self, session_id: str, limit: int = None) -> List[Message]:
        messages = self._messages.get(session_id, [])
        if limit:
            return messages[-limit:]
        return messages

    def update_summary(self, session_id: str, summary: str):
        if session_id in self._contexts:
            self._contexts[session_id].summary = summary

    def get_context_summary(self, session_id: str) -> str:
        context = self._contexts.get(session_id)
        if not context:
            return ""

        return context.summary or f"[{context.conversation_type.value}] {context.topic}"

    def delete_conversation(self, session_id: str):
        if session_id in self._contexts:
            del self._contexts[session_id]
        if session_id in self._messages:
            del self._messages[session_id]
        logger.info(f"删除会话: session_id={session_id}")