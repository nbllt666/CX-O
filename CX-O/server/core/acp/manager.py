import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class ACPGroupInfo:
    id: str
    name: str
    description: str
    creator_id: str
    creator_name: str
    members: List[Dict]
    max_members: int = 50
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict = field(default_factory=dict)


@dataclass
class ACPAgentInfo:
    agent_id: str
    name: str
    status: str = "offline"
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


@dataclass
class ACPMessageInfo:
    id: str
    msg_type: str
    from_agent_id: str
    from_agent_name: str
    to_agent_id: Optional[str] = None
    to_group_id: Optional[str] = None
    content: Any = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    is_sent: bool = False


class ACPManager:
    def __init__(self, db_path: str = "data/acp.db"):
        self.db_path = db_path
        self._agents: Dict[str, ACPAgentInfo] = {}
        self._groups: Dict[str, ACPGroupInfo] = {}
        self._messages: List[ACPMessageInfo] = []
        self._pending_messages: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._group_members: Dict[str, List[str]] = defaultdict(list)

    async def register_agent(self, agent_info: ACPAgentInfo) -> bool:
        async with self._lock:
            self._agents[agent_info.agent_id] = agent_info
            logger.info(f"ACP Agent注册: id={agent_info.agent_id}, name={agent_info.name}")
            return True

    async def get_agent(self, agent_id: str) -> Optional[ACPAgentInfo]:
        return self._agents.get(agent_id)

    async def list_agents(self) -> List[Dict]:
        return [asdict(agent) for agent in self._agents.values()]

    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        async with self._lock:
            if agent_id in self._agents:
                self._agents[agent_id].status = status
                return True
            return False

    async def create_group(self, group: ACPGroupInfo) -> bool:
        async with self._lock:
            self._groups[group.id] = group
            if group.creator_id:
                self._group_members[group.id].append(group.creator_id)
            logger.info(f"ACP群组创建: id={group.id}, name={group.name}")
            return True

    async def get_group(self, group_id: str) -> Optional[ACPGroupInfo]:
        return self._groups.get(group_id)

    async def list_groups(self) -> List[Dict]:
        return [asdict(group) for group in self._groups.values()]

    async def update_group(self, group_id: str, **kwargs) -> bool:
        async with self._lock:
            if group_id not in self._groups:
                return False
            group = self._groups[group_id]
            for key, value in kwargs.items():
                if hasattr(group, key):
                    setattr(group, key, value)
            group.updated_at = datetime.now().isoformat()
            return True

    async def delete_group(self, group_id: str) -> bool:
        async with self._lock:
            if group_id in self._groups:
                del self._groups[group_id]
                if group_id in self._group_members:
                    del self._group_members[group_id]
                return True
            return False

    async def add_group_member(self, group_id: str, member: Dict) -> bool:
        async with self._lock:
            if group_id not in self._groups:
                return False
            group = self._groups[group_id]
            for m in group.members:
                if m.get("agent_id") == member.get("agent_id"):
                    return True
            group.members.append(member)
            self._group_members[group_id].append(member.get("agent_id"))
            group.updated_at = datetime.now().isoformat()
            return True

    async def remove_group_member(self, group_id: str, agent_id: str) -> bool:
        async with self._lock:
            if group_id not in self._groups:
                return False
            group = self._groups[group_id]
            group.members = [m for m in group.members if m.get("agent_id") != agent_id]
            if agent_id in self._group_members[group_id]:
                self._group_members[group_id].remove(agent_id)
            group.updated_at = datetime.now().isoformat()
            return True

    async def send_message(self, message: ACPMessageInfo) -> bool:
        self._messages.append(message)
        if message.to_agent_id and message.to_agent_id in self._pending_messages:
            await self._pending_messages[message.to_agent_id].put(message)
        logger.debug(f"ACP消息发送: from={message.from_agent_id}, to={message.to_agent_id or message.to_group_id}")
        return True

    async def get_messages(self, agent_id: str = None, group_id: str = None, limit: int = 50) -> List[Dict]:
        messages = []
        for msg in reversed(self._messages):
            if agent_id and msg.to_agent_id == agent_id:
                messages.append(asdict(msg))
            elif group_id and msg.to_group_id == group_id:
                messages.append(asdict(msg))
            if len(messages) >= limit:
                break
        return messages

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        self._pending_messages[agent_id] = queue
        return queue

    def unsubscribe(self, agent_id: str):
        if agent_id in self._pending_messages:
            del self._pending_messages[agent_id]

    async def get_statistics(self) -> Dict:
        return {
            "total_agents": len(self._agents),
            "total_groups": len(self._groups),
            "total_messages": len(self._messages),
            "online_agents": sum(1 for a in self._agents.values() if a.status == "online"),
        }