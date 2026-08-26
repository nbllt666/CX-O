"""ACP 分组管理——Agent 分组创建、加入与成员管理。"""
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from server.core.logging_config import get_contextual_logger
from server.models.acp import ACPGroupMember

from .manager import ACPGroupInfo, ACPManager, ACPMessageInfo

logger = get_contextual_logger(__name__)


class ACPGroupManager:
    """ACP 群组管理器，封装群组的创建、查询、成员加入/退出/邀请/踢出及群消息广播，委托给 ACPManager 持久化。"""

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
        """创建新群组，创建者作为管理员，返回群组信息。"""
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
        """按 ID 查询群组，不存在时返回 None。"""
        return await self.acp_manager.get_group(group_id)

    async def list_groups(self) -> List[Dict]:
        """返回全部群组的字典列表。"""
        return await self.acp_manager.list_groups()

    async def update_group(self, group_id: str, **kwargs) -> bool:
        """按关键字更新群组字段，返回是否成功。"""
        return await self.acp_manager.update_group(group_id, **kwargs)

    async def delete_group(self, group_id: str) -> bool:
        """删除指定群组，返回是否成功。"""
        return await self.acp_manager.delete_group(group_id)

    async def join_group(self, group_id: str, agent_id: str, agent_name: str) -> bool:
        """将 Agent 加入指定群组，校验群组活跃状态与成员上限，成功时广播成员加入事件。"""
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
        """Agent 退出群组，群主不可退出，成功时广播成员离开事件。"""
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
        """由群组成员发起邀请，校验邀请者身份后返回是否允许邀请。"""
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
        """管理员将成员移出群组，群主不可被移除，成功时广播成员被踢事件。"""
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
        """向指定群组广播一条消息，群组不存在或停用时报错，返回构造并已发送的消息对象。"""
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
        """获取指定群组的消息列表。

        Args:
            group_id: 群组 ID
            limit: 返回的最大消息条数

        Returns:
            List[Dict]: 消息字典列表
        """
        # #24（补充批注）: 旧实现把 group_id 同时当作 target_id 与 group_id 双参传入，
        # 语义冗余。群消息按 group 键存取，target 位置显式留空以表达「非单发」。
        return await self.acp_manager.get_messages("", group_id=group_id, limit=limit)

    async def get_member_groups(self, agent_id: str) -> List[Dict]:
        """查询指定 agent 所在的所有群组。

        Returns:
            List[Dict]: 该 agent 所在的群组字典列表
        """
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
        """向指定群组发送一条系统控制事件消息（成员加入/离开/被踢等）。"""
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
        """返回分组管理功能的状态信息。

        #25（补充批注）: 旧实现硬编码 enabled=True / max_groups=10。
        改为接 settings.config.acp 实际配置（ACPGroupConfig.max_groups 默认 10）。
        """
        try:
            from server.config import get_settings

            acp_cfg = get_settings().config.acp
            enabled = bool(acp_cfg.enabled)
            max_groups = int(getattr(acp_cfg.group, "max_groups", 10))
        except Exception:
            enabled, max_groups = True, 10
        return {"enabled": enabled, "max_groups_per_agent": max_groups}
