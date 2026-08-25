"""模块七 · MeetingCoordinator —— 圆桌导演（总控）。

装配六个模块，串起"用户说话→仲裁→令牌→TTS→转录"主流程，管理房间生命周期与
状态广播回调（供 WebSocketManager / 前端订阅）。

设计基准：《CX-O 多 Agent 语音会议协调器》§10 完整流程走读。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from server.core.meeting.audio_router import AudioRouter
from server.core.meeting.interrupt_coord import InterruptCoordinator
from server.core.meeting.models import AgentMember
from server.core.meeting.room import MeetingRoom
from server.core.meeting.transcript import MeetingTranscript
from server.core.meeting.turn_arbiter import TurnArbiter

logger = logging.getLogger(__name__)

# 发言生成器：async (room, agent_id, user_text) -> str | None
Responder = Callable[[MeetingRoom, str, str], Awaitable[Optional[str]]]
# 发言回调（TTS/音频路由挂载点）：async (room, agent_id, text) -> None
SpeakHook = Callable[[MeetingRoom, str, str], Awaitable[None]]
# 状态广播回调：async (room) -> None
BroadcastCB = Callable[[MeetingRoom], Awaitable[None]]


class MeetingCoordinator:
    """多 Agent 语音会议协调器。

    参数均可选注入，便于测试与零侵入装配：
    - ``model_router``：ModelRouter（可选，供默认发言生成）
    - ``context_manager``：上下文管理器（可选，供会话上下文接入）
    - ``responder``：发言文本生成器（可选；缺省用可用的 model_router/client 或占位）
    - ``state_broadcast``：状态广播回调（可选，对接 WebSocketManager）
    """

    def __init__(
        self,
        max_agents: int = 5,
        default_mode: str = "moderator",
        token_hold_timeout_sec: float = 30.0,
        relay_pause_sec: float = 0.4,
        backchannel_enabled: bool = False,
        backchannel_volume: float = 0.2,
        transcript_max_turns: int = 20,
        transcript_summary: bool = True,
        agent_interrupt_enabled: bool = False,
        interpret: Optional[Callable] = None,
        model_router: Any = None,
        context_manager: Any = None,
        responder: Optional[Responder] = None,
        state_broadcast: Optional[BroadcastCB] = None,
    ):
        self.max_agents = max_agents
        self.relay_pause_sec = relay_pause_sec
        self.model_router = model_router
        self.context_manager = context_manager
        self._responder = responder

        # 装配各子模块
        self.arbiter = TurnArbiter(interpret=interpret, default_mode=default_mode)
        self.token_hold_timeout_sec = token_hold_timeout_sec
        self.interrupt = InterruptCoordinator(
            agent_interrupt_enabled=agent_interrupt_enabled
        )
        self.audio_router = AudioRouter(
            backchannel_enabled=backchannel_enabled,
            backchannel_volume=backchannel_volume,
        )
        self._transcript_max_turns = transcript_max_turns
        self._transcript_summary = transcript_summary

        # 房间表
        self.rooms: Dict[str, MeetingRoom] = {}
        # 状态广播回调集合
        self._broadcast_cbs: List[BroadcastCB] = []
        if state_broadcast is not None:
            self._broadcast_cbs.append(state_broadcast)

        logger.info(
            "MeetingCoordinator 装配完成：default_mode=%s, token_hold=%.1fs, relay=%.2fs",
            default_mode,
            token_hold_timeout_sec,
            relay_pause_sec,
        )

    # ================================================================ 广播
    def register_broadcast(self, cb: BroadcastCB) -> None:
        """注册状态广播回调（供 WebSocketManager/前端订阅）。"""
        if cb not in self._broadcast_cbs:
            self._broadcast_cbs.append(cb)

    def unregister_broadcast(self, cb: BroadcastCB) -> None:
        """注销状态广播回调。"""
        self._broadcast_cbs = [c for c in self._broadcast_cbs if c is not cb]

    async def _broadcast(self, room: MeetingRoom) -> None:
        """向所有订阅者广播房间状态快照。"""
        snapshot = room.to_dict()
        for cb in list(self._broadcast_cbs):
            try:
                await cb(room)
            except Exception as e:  # 单订阅者失败不阻断其他
                logger.warning("会议状态广播失败: %s", e)
        logger.debug("会议 %s 状态广播: %s", room.room_id, snapshot.get("state"))

    # ================================================================ 房间管理
    def _new_room(self, room_id: str, user: str, agents: List[AgentMember], max_agents: int) -> MeetingRoom:
        """构造房间并装配共享 transcript/token 与状态回调。"""
        token = self._make_token()
        transcript = MeetingTranscript(
            max_turns=self._transcript_max_turns,
            summary_enabled=self._transcript_summary,
        )
        room = MeetingRoom(
            room_id=room_id,
            user=user,
            agents=agents,
            max_agents=max_agents,
            token=token,
            transcript=transcript,
        )
        room.add_state_callback(self._on_room_state_change)
        return room

    def _make_token(self):
        """按配置构造 SpeakingToken（注入令牌 revoke 通知打断）。"""
        from server.core.meeting.token import SpeakingToken

        return SpeakingToken(
            token_hold_timeout_sec=self.token_hold_timeout_sec,
            on_revoke=self._on_token_revoked,
        )

    async def _on_token_revoked(self, revoked_holder: Optional[str]) -> None:
        """令牌被强制收回：让对应 agent 打断（停 TTS）。"""
        if not revoked_holder:
            return
        for room in self.rooms.values():
            agent = room.get_agent(revoked_holder)
            if agent is not None:
                await self.interrupt._interrupt_agent(agent)
                break

    async def _on_room_state_change(self, room, old, new) -> None:
        """房间状态回调：转发广播。"""
        await self._broadcast(room)

    async def start_meeting(
        self,
        user: str,
        agents: List[Union[AgentMember, Dict[str, Any]]],
        room_id: Optional[str] = None,
        max_agents: Optional[int] = None,
    ) -> MeetingRoom:
        """开启新会议并启动。

        Args:
            user: 用户标识（房间主角）。
            agents: Agent 成员（AgentMember 实例或 {agent_id, name, ...} dict）。
            room_id: 可选显式房间号（缺省自动生成）。
            max_agents: 覆盖默认单房间上限。

        Returns:
            已启动的 MeetingRoom。
        """
        members = [self._to_member(a) for a in agents]
        cap = max_agents or self.max_agents
        if len(members) > cap:
            raise ValueError(f"参会 agent 数 {len(members)} 超过单房间上限 {cap}")
        rid = room_id or _gen_room_id()
        room = self._new_room(rid, user, members, cap)
        self.rooms[rid] = room
        await room.start()
        await self._broadcast(room)
        return room

    def _to_member(self, item: Union[AgentMember, Dict[str, Any]]) -> AgentMember:
        """规范化 agent 成员。"""
        if isinstance(item, AgentMember):
            return item
        if isinstance(item, dict):
            return AgentMember(
                agent_id=item.get("agent_id") or item.get("id", ""),
                name=item.get("name", ""),
                persona=item.get("persona", ""),
                relevance=item.get("relevance", 0.5),
                desire_to_speak=item.get("desire_to_speak", 0.5),
                voice=item.get("voice"),
            )
        raise TypeError(f"无法解析 Agent 成员: {item!r}")

    def get_room(self, room_id: str) -> Optional[MeetingRoom]:
        """按房间号查询房间。"""
        return self.rooms.get(room_id)

    async def end_meeting(self, room_id: str) -> str:
        """结束会议，返回沉淀的记忆摘要。"""
        room = self._require_room(room_id)
        summary = await room.end()
        self.rooms.pop(room_id, None)
        return summary

    async def join(self, room_id: str, agent_id: str, name: str = "", **kwargs: Any) -> bool:
        """向已有房间加入 Agent。"""
        room = self._require_room(room_id)
        added = await room.join(agent_id, name=name, **kwargs)
        await self._broadcast(room)
        return added

    async def leave(self, room_id: str, agent_id: str) -> bool:
        """从房间移除 Agent。"""
        room = self._require_room(room_id)
        left = await room.leave(agent_id)
        await self._broadcast(room)
        return left

    def room_state(self, room_id: str) -> dict:
        """返回房间状态快照。"""
        room = self._require_room(room_id)
        return room.to_dict()

    def _require_room(self, room_id: str) -> MeetingRoom:
        """按房间号取房间，不存在抛 KeyError（上游映射为 404）。"""
        room = self.rooms.get(room_id)
        if room is None:
            raise KeyError(f"会议房间不存在: {room_id}")
        return room

    # ================================================================ 主流程
    async def process_user_speech(
        self, room_id: str, utterance: str, responder: Optional[Responder] = None
    ) -> dict:
        """用户说话主流程：

        1) 记录用户发言
        2) 令牌仲裁（点名/主持人/竞争/轮询）
        3) 打断所有 agent（revoke 令牌）
        4) 复位令牌 → 授权发言者 → 生成回复 → 记录转录
        5) 队列接力（relay_pause_sec 自然停顿）

        Returns:
            结构化的回合结果 dict。
        """
        room = self._require_room(room_id)
        text = (utterance or "").strip()
        room.transcript.append("user", "user", text)

        # 仲裁（先算谁该接）
        decision = await self.arbiter.arbitrate(text, room)

        # 用户开口 = 最高优先级打断：收回令牌 + 复位以便重新授权
        await self.interrupt.on_user_speech(room)
        await room.token.reset()

        responder_fn = responder or self._responder
        turns: List[dict] = []
        chosen = decision.speaker

        if chosen:
            granted = await room.token.acquire(chosen)
            if granted:
                await self._drive_turn(room, chosen, text, responder_fn, turns)
                await room.token.release(chosen)
                # 举手队列接力
                while room.token.pending_queue:
                    await asyncio.sleep(self.relay_pause_sec)
                    nxt = await room.token.release()
                    if not nxt:
                        break
                    await self._drive_turn(room, nxt, text, responder_fn, turns)
                    await room.token.release(nxt)

        # 写回上下文（复用 ContextManager，可选）
        await self._ingest_context(room)

        await self._broadcast(room)
        return {
            "decision": decision.to_dict(),
            "turns": turns,
            "transcript_turns": len(room.transcript),
        }

    async def _drive_turn(
        self,
        room: MeetingRoom,
        agent_id: str,
        user_text: str,
        responder: Optional[Responder],
        turns: List[dict],
    ) -> Optional[str]:
        """让某 agent 完成一轮发言：生成回复→记录转录→路由允许性检查。"""
        agent = room.get_agent(agent_id)
        if agent is None:
            return None
        reply = await self._generate_reply(room, agent_id, user_text, responder)
        if not reply:
            logger.info("agent %s 无回复，跳过本轮", agent_id)
            return None
        room.transcript.append(agent_id, "agent", reply)
        allowed = self.audio_router.is_allowed(agent_id, room)
        turns.append(
            {
                "speaker": agent_id,
                "text": reply,
                "audio_allowed": allowed,
                "voice": agent.voice,
                # 真实参考音频资产 id（本 server 合成时据此选音色；上报供客户端取用）
                "ref_audio_asset_id": self._agent_ref_asset_id(agent_id),
            }
        )
        return reply

    def _agent_ref_asset_id(self, agent_id: str) -> Optional[str]:
        """返回 Agent 绑定的参考音频资产 id（无绑定返回 None）。"""
        try:
            from server import ref_audio_store

            b = ref_audio_store.get_for_agent(agent_id) or {}
            return b.get("asset_id")
        except Exception:  # noqa: BLE001 - 上报尽力而为
            return None

    async def _generate_reply(
        self,
        room: MeetingRoom,
        agent_id: str,
        user_text: str,
        responder: Optional[Responder],
    ) -> Optional[str]:
        """生成 agent 回复文本。

        优先级：注入 responder > 会话生成的 speak 能力 > model_router/client > 占位。
        """
        if responder is not None:
            reply = responder(room, agent_id, user_text)
            if hasattr(reply, "__await__"):
                reply = await reply
            return reply or None

        agent = room.get_agent(agent_id)
        session = getattr(agent, "session", None) if agent else None
        speak = getattr(session, "speak", None) if session else None
        if speak is not None:
            reply = speak(user_text)
            if hasattr(reply, "__await__"):
                reply = await reply
            return reply or None

        client = getattr(self.model_router, "get_client", lambda *_: None)("main") if self.model_router else None
        if client is not None:
            try:
                context = room.transcript.render_context(self._transcript_max_turns)
                response = await client.chat(
                    messages=[
                        {"role": "system", "content": f"你是在会议中的 agent「{agent_id}」。"},
                        {"role": "user", "content": f"会议上下文：\n{context}\n\n用户当前说：{user_text}"},
                    ],
                    stream=False,
                )
                if response and not getattr(response, "error", None):
                    return getattr(response, "content", None) or None
            except Exception as e:  # 生成失败走降级
                logger.warning("agent %s 回复生成失败: %s", agent_id, e)

        # 占位（无任何生成能力时，保证主流程可观察）
        if agent is not None:
            return f"（{agent.display_name} 发言）"
        return None

    async def _ingest_context(self, room: MeetingRoom) -> None:
        """将最近会议记录写回 ContextManager（若有装配）。"""
        cm = self.context_manager
        if cm is None:
            return
        try:
            context = room.transcript.render_context(self._transcript_max_turns)
            add = getattr(cm, "add_message", None) or getattr(cm, "append_message", None)
            if add is not None:
                add(room.room_id, "system", f"[会议记录]\n{context}")
        except Exception as e:  # 上下文回写失败不阻断主流程
            logger.warning("会议上下文回写失败: %s", e)


def _gen_room_id() -> str:
    """生成房间唯一标识。"""
    import uuid

    return f"meet-{uuid.uuid4().hex[:12]}"
