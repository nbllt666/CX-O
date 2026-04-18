import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger
from backend.models.acp import ACPGroupMember

from .manager import ACPGroupInfo, ACPManager, ACPMessageInfo

logger = get_contextual_logger(__name__)


class ACPGroupManager:
    def __init__(self, acp_manager: ACPManager):
        self.acp_manager = acp_manager

    async def create_group(
        self,
        name: str,
        description: str = "",
        creator_id: str = "",
        creator_name: str = "",
        max_members: int = 50,
        metadata: Dict = None,
    ) -> ACPGroupInfo:
        group_id = str(uuid.uuid4())

        creator = ACPGroupMember(agent_id=creator_id, agent_name=creator_name, role="admin")

        group = ACPGroupInfo(
            id=group_id,
            name=name,
            description=description,
            creator_id=creator_id,
            creator_name=creator_name,
            members=[creator.to_dict()],
            max_members=max_members,
            is_active=True,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            metadata=metadata or {},
        )

        await self.acp_manager.create_group(group)
        logger.info(f"群组已创建: id={group_id}, name={name}")

        return group

    async def get_group(self, group_id: str) -> Optional[ACPGroupInfo]:
        return await self.acp_manager.get_group(group_id)

    async def list_groups(self) -> List[Dict]:
        return await self.acp_manager.list_groups()

    async def update_group(self, group_id: str, **kwargs) -> bool:
        return await self.acp_manager.update_group(group_id, **kwargs)

    async def delete_group(self, group_id: str) -> bool:
        return await self.acp_manager.delete_group(group_id)

    async def join_group(self, group_id: str, agent_id: str, agent_name: str) -> bool:
        group = await self.acp_manager.get_group(group_id)
        if not group:
            return False

        if not group.is_active:
            return False

        if len(group.members) >= group.max_members:
            logger.warning(f"群组已满: {group_id}")
            return False

        for member in group.members:
            if member.get("agent_id") == agent_id:
                logger.info(f"Agent已在群组中: {agent_id}")
                return True

        member = ACPGroupMember(agent_id=agent_id, agent_name=agent_name, role="member")

        success = await self.acp_manager.add_group_member(group_id, member.to_dict())
        if success:
            await self._broadcast_group_event(
                group_id, "member_joined", {"agent_id": agent_id, "agent_name": agent_name}
            )

        return success

    async def leave_group(self, group_id: str, agent_id: str) -> bool:
        group = await self.acp_manager.get_group(group_id)
        if not group:
            return False

        if group.creator_id == agent_id:
            logger.warning(f"群主不能退出群组: {group_id}")
            return False

        success = await self.acp_manager.remove_group_member(group_id, agent_id)
        if success:
            agent_info = await self.acp_manager.get_agent(agent_id)
            agent_name = agent_info.name if agent_info else "Unknown"

            await self._broadcast_group_event(
                group_id, "member_left", {"agent_id": agent_id, "agent_name": agent_name}
            )

        return success

    async def invite_member(self, group_id: str, inviter_id: str, invitee_agent_id: str) -> bool:
        group = await self.acp_manager.get_group(group_id)
        if not group:
            return False

        for member in group.members:
            if member.get("agent_id") == inviter_id:
                if member.get("role") not in ["admin", "member"]:
                    return False
                break
        else:
            return False

        return True

    async def kick_member(self, group_id: str, kicker_id: str, target_id: str) -> bool:
        group = await self.acp_manager.get_group(group_id)
        if not group:
            return False

        is_admin = False
        for member in group.members:
            if member.get("agent_id") == kicker_id and member.get("role") == "admin":
                is_admin = True
                break

        if not is_admin:
            return False

        if target_id == group.creator_id:
            return False

        success = await self.acp_manager.remove_group_member(group_id, target_id)
        if success:
            agent_info = await self.acp_manager.get_agent(target_id)
            agent_name = agent_info.name if agent_info else "Unknown"

            await self._broadcast_group_event(
                group_id,
                "member_kicked",
                {"agent_id": target_id, "agent_name": agent_name, "kicked_by": kicker_id},
            )

        return success

    async def broadcast_to_group(
        self,
        group_id: str,
        from_agent_id: str,
        from_agent_name: str,
        content: Dict,
        msg_type: str = "group_message",
    ) -> ACPMessageInfo:
        group = await self.acp_manager.get_group(group_id)
        if not group or not group.is_active:
            raise ValueError(f"群组不存在或已停用: {group_id}")

        message = ACPMessageInfo(
            id=str(uuid.uuid4()),
            msg_type=msg_type,
            from_agent_id=from_agent_id,
            from_agent_name=from_agent_name,
            to_group_id=group_id,
            content=content,
            timestamp=datetime.now().isoformat(),
            is_sent=True,
        )

        await self.acp_manager.send_message(message)
        logger.info(f"群消息已发送: group_id={group_id}, from={from_agent_name}")

        return message

    async def get_group_messages(self, group_id: str, limit: int = 50) -> List[Dict]:
        return await self.acp_manager.get_messages(group_id, group_id=group_id, limit=limit)

    async def get_member_groups(self, agent_id: str) -> List[Dict]:
        all_groups = await self.acp_manager.list_groups()
        member_groups = []

        for group_data in all_groups:
            members = group_data.get("members", [])
            for member in members:
                if member.get("agent_id") == agent_id:
                    member_groups.append(group_data)
                    break

        return member_groups

    async def _broadcast_group_event(self, group_id: str, event_type: str, event_data: Dict):
        message = ACPMessageInfo(
            id=str(uuid.uuid4()),
            msg_type="control",
            from_agent_id="system",
            from_agent_name="System",
            to_group_id=group_id,
            content={"event": event_type, "data": event_data},
            timestamp=datetime.now().isoformat(),
            is_sent=True,
        )

        await self.acp_manager.send_message(message)

    def get_status(self) -> Dict:
        return {"enabled": True, "max_groups_per_agent": 10}
