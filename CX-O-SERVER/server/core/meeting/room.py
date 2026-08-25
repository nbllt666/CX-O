"""模块一 · MeetingRoom —— 共享房间（共享 ASR + 圆桌容器）。

把"N 个并行 1对1"改造成"1 个共享房间 + 发言权调度"。

设计基准：《CX-O 多 Agent 语音会议协调器》§4。

职责：管理参与者（user + agents）、房间状态、生命周期，并持有唯一的
``SpeakingToken`` 与 ``MeetingTranscript``。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from server.core.meeting.models import RoomState, AgentMember as AgentMemberModel
from server.core.meeting.token import SpeakingToken
from server.core.meeting.transcript import MeetingTranscript

logger = logging.getLogger(__name__)

# 状态变更回调类型：async/sync (room, old_state, new_state) -> None
StateCallback = Callable[["MeetingRoom", RoomState, RoomState], Any]


class MeetingRoom:
    """会议房间。

    用例：

    >>> room = MeetingRoom("room-x", user="用户", agents=[AgentMember("A")])
    >>> await room.start()
    >>> await room.join("B")          # 添加第二个 agent
    >>> await room.leave("A")
    >>> await room.end()
    """

    def __init__(
        self,
        room_id: str,
        user: str,
        agents: Optional[List[AgentMemberModel]] = None,
        max_agents: int = 5,
        token: Optional[SpeakingToken] = None,
        transcript: Optional[MeetingTranscript] = None,
        audience_enabled: bool = False,
    ):
        self.room_id: str = room_id or uuid.uuid4().hex[:12]
        self.user: str = user
        self.max_agents: int = int(max_agents)
        self.agents: List[AgentMemberModel] = list(agents or [])
        self.token: SpeakingToken = token or SpeakingToken()
        self.transcript: MeetingTranscript = transcript or MeetingTranscript()
        # 观众席开关（供互动空间开/关观众弹幕通道，T3 消费）
        self.audience_enabled: bool = bool(audience_enabled)
        self.state: RoomState = RoomState.IDLE
        self._state_callbacks: List[StateCallback] = []

    # ---------------------------------------------------------------- 参与者
    def get_agent(self, agent_id: str) -> Optional[AgentMemberModel]:
        """按 agent_id 查找成员；不存在返回 None。"""
        for a in self.agents:
            if a.agent_id == agent_id:
                return a
        return None

    def add_state_callback(self, cb: StateCallback) -> None:
        """注册状态变更回调（供 WebSocketManager/前端订阅）。"""
        if cb not in self._state_callbacks:
            self._state_callbacks.append(cb)

    def to_dict(self) -> Dict[str, Any]:
        """序列化房间状态快照（供 REST 返回/广播）。"""
        return {
            "room_id": self.room_id,
            "user": self.user,
            "state": self.state.value,
            "max_agents": self.max_agents,
            "agents": [a.to_dict() for a in self.agents],
            "token_holder": self.token.who_holds(),
            "transcript_turns": len(self.transcript),
            "audience_enabled": self.audience_enabled,
            # 最近消息流摘要（供前端渲染互动空间消息流）
            "recent_messages": [
                {"role": e.role, "speaker": e.speaker, "text": e.text, "ts": e.ts}
                for e in self.transcript.recent(20)
            ],
        }

    # ---------------------------------------------------------------- 生命周期
    async def start(self) -> RoomState:
        """开启会议：初始化共享 ASR，状态置 IN_MEETING。"""
        await self._set_state(RoomState.IN_MEETING)
        await self.token.reset()
        logger.info("会议 %s 开始（user=%s, agents=%s）", self.room_id, self.user, len(self.agents))
        return self.state

    async def join(self, agent_id: str, name: str = "", **kwargs: Any) -> bool:
        """Agent 加入会议。

        Returns:
            True 加入成功；False（重复加入 / 已达 max_agents）。
        """
        if self.get_agent(agent_id) is not None:
            logger.warning("会议 %s 中 %s 已在场", self.room_id, agent_id)
            return False
        if len(self.agents) >= self.max_agents:
            logger.warning("会议 %s 已达 agent 上限 %s", self.room_id, self.max_agents)
            return False
        self.agents.append(AgentMemberModel(agent_id=agent_id, name=name or agent_id, **kwargs))
        logger.info("会议 %s 加入 agent %s（现有 %s）", self.room_id, agent_id, len(self.agents))
        return True

    async def leave(self, agent_id: str) -> bool:
        """Agent 离开会议。若是令牌持有者，离开时自动释放令牌。

        Returns:
            True 离开成功；False（不在场）。
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            return False
        self.agents = [a for a in self.agents if a.agent_id != agent_id]
        if self.token.who_holds() == agent_id:
            await self.token.release(agent_id)
        logger.info("会议 %s 离开 agent %s（剩余 %s）", self.room_id, agent_id, len(self.agents))
        return True

    async def end(self) -> str:
        """结束会议：沉淀会议记忆，状态置 IDLE。

        Returns:
            会议要点摘要（roll_up），供写回记忆。
        """
        summary = self.transcript.roll_up()
        # 清空令牌与打断状态
        await self.token.revoke()
        await self.token.reset()
        await self._set_state(RoomState.IDLE)
        logger.info("会议 %s 结束", self.room_id)
        return summary

    # ---------------------------------------------------------------- 内部
    async def _set_state(self, next_state: RoomState) -> None:
        """切换房间状态并触发状态回调广播。"""
        old = self.state
        if old == next_state:
            return
        self.state = next_state
        for cb in list(self._state_callbacks):
            try:
                result = cb(self, old, next_state)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:  # 广播失败不阻断状态切换
                logger.warning("会议状态广播回调错误: %s", e)