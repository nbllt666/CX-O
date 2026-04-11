import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class ACPGroupManager:
    def __init__(self, acp_manager):
        self.acp_manager = acp_manager

    async def create_group(self, name: str, description: str = "", creator_id: str = "", creator_name: str = "", max_members: int = 50, metadata: Dict = None):
        group_id = str(uuid.uuid4())
        from .manager import ACPGroupInfo
        creator = {"agent_id": creator_id, "agent_name": creator_name, "role": "admin"}
        group = ACPGroupInfo(id=group_id, name=name, description=description, creator_id=creator_id, creator_name=creator_name,
                            members=[creator], max_members=max_members, is_active=True, metadata=metadata or {})
        await self.acp_manager.create_group(group)
        logger.info(f"群组已创建: id={group_id}, name={name}")
        return group

    async def get_group(self, group_id: str):
        return await self.acp_manager.get_group(group_id)

    async def list_groups(self) -> List[Dict]:
        return await self.acp_manager.list_groups()

    async def update_group(self, group_id: str, **kwargs) -> bool:
        return await self.acp_manager.update_group(group_id, **kwargs)

    async def delete_group(self, group_id: str) -> bool:
        return await self.acp_manager.delete_group(group_id)

    async def join_group(self, group_id: str, agent_id: str, agent_name: str) -> bool:
        group = await self.acp_manager.get_group(group_id)
        if not group or not group.is_active:
            return False
        if len(group.members) >= group.max_members:
            return False
        for member in group.members:
            if member.get("agent_id") == agent_id:
                return True
        member = {"agent_id": agent_id, "agent_name": agent_name, "role": "member"}
        return await self.acp_manager.add_group_member(group_id, member)

    async def leave_group(self, group_id: str, agent_id: str) -> bool:
        group = await self.acp_manager.get_group(group_id)
        if not group:
            return False
        if group.creator_id == agent_id:
            return False
        return await self.acp_manager.remove_group_member(group_id, agent_id)

    async def get_member_groups(self, agent_id: str) -> List[Dict]:
        all_groups = await self.acp_manager.list_groups()
        return [g for g in all_groups if any(m.get("agent_id") == agent_id for m in g.get("members", []))]