"""模块七 · MeetingCoordinator —— 圆桌导演（总控）。

装配六个模块，串起"用户说话→仲裁→令牌→TTS→转录"主流程，管理房间生命周期与
状态广播回调（供 WebSocketManager / 前端订阅）。

设计基准：《CX-O 多 Agent 语音会议协调器》§10 完整流程走读。
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from server.core.meeting.audio_router import AudioRouter
from server.core.meeting.danmaku_connector import DanmakuConnector, create_connector
from server.core.meeting.interrupt_coord import InterruptCoordinator
from server.core.meeting.models import AgentMember, RoomState
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
# 弹幕回复事件回调：async (payload: danmaku_reply dict) -> None
DanmakuReplyCB = Callable[[Dict[str, Any]], Awaitable[None]]


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
        speech_rate: float = 0.3,  # Agent 自发插话率 0-1（群聊式多态回应配置，T2 消费）
        agent_speech_prompt: str = "",  # 插话判断 prompt 模板，空用内置（T2 消费）
        interpret: Optional[Callable] = None,
        model_router: Any = None,
        context_manager: Any = None,
        responder: Optional[Responder] = None,
        state_broadcast: Optional[BroadcastCB] = None,
        danmaku_source: Optional[dict] = None,  # 观众弹幕源配置（T3，dict 或 None）
    ):
        self.max_agents = max_agents
        self.relay_pause_sec = relay_pause_sec
        self.model_router = model_router
        self.context_manager = context_manager
        self._responder = responder
        self.speech_rate = speech_rate
        self.agent_speech_prompt = agent_speech_prompt

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

        # 弹幕回复事件回调集合（T3，danmaku_reply 广播通道）
        self._danmaku_reply_cbs: List[DanmakuReplyCB] = []
        # 弹幕源配置 + 房间级连接器表（room_id -> connector，T3）
        self._danmaku_source: dict = danmaku_source or {}
        self._connector: Dict[str, Optional[DanmakuConnector]] = {}

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

    def register_danmaku_reply(self, cb: DanmakuReplyCB) -> None:
        """注册弹幕回复事件回调（供 WebSocket/前端订阅 danmaku_reply，T3）。"""
        if cb not in self._danmaku_reply_cbs:
            self._danmaku_reply_cbs.append(cb)

    def unregister_danmaku_reply(self, cb: DanmakuReplyCB) -> None:
        """注销弹幕回复事件回调。"""
        self._danmaku_reply_cbs = [c for c in self._danmaku_reply_cbs if c is not cb]

    async def _broadcast(self, room: MeetingRoom) -> None:
        """向所有订阅者广播房间状态快照。"""
        snapshot = room.to_dict()
        for cb in list(self._broadcast_cbs):
            try:
                await cb(room)
            except Exception as e:  # 单订阅者失败不阻断其他
                logger.warning("会议状态广播失败: %s", e)
        logger.debug("会议 %s 状态广播: %s", room.room_id, snapshot.get("state"))

    async def _emit_danmaku_replies(self, room_id: str, turns: List[dict], username: str) -> None:
        """向弹幕回复订阅者发射 danmaku_reply 事件（逐 turn 发，T3）。"""
        for turn in turns:
            payload = {
                "type": "danmaku_reply",
                "room_id": room_id,
                "agent_id": turn.get("speaker", ""),
                "text": turn.get("text", ""),
                "username": username or "",
            }
            for cb in list(self._danmaku_reply_cbs):
                try:
                    result = cb(payload)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as e:  # 单订阅者失败不阻断其他
                    logger.warning("弹幕回复广播失败: %s", e)

    # ================================================================ 房间管理
    def _new_room(self, room_id: str, user: str, agents: List[AgentMember], max_agents: int, audience_enabled: bool = False) -> MeetingRoom:
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
            audience_enabled=audience_enabled,
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
        audience_enabled: bool = False,
    ) -> MeetingRoom:
        """开启新会议并启动。

        Args:
            user: 用户标识（房间主角）。
            agents: Agent 成员（AgentMember 实例或 {agent_id, name, ...} dict）。
            room_id: 可选显式房间号（缺省自动生成）。
            max_agents: 覆盖默认单房间上限。
            audience_enabled: 是否开启观众席（互动空间，默认关）。

        Returns:
            已启动的 MeetingRoom。
        """
        members = [self._to_member(a) for a in agents]
        cap = max_agents or self.max_agents
        if len(members) > cap:
            raise ValueError(f"参会 agent 数 {len(members)} 超过单房间上限 {cap}")
        rid = room_id or _gen_room_id()
        room = self._new_room(rid, user, members, cap, audience_enabled=audience_enabled)
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
    async def process_user_speech(self, room_id: str, utterance: str, meta: Optional[Dict[str, Any]] = None) -> dict:
        """兼容包装：用户发言入口（role="user"）。

        meta 可选携带 speaker_label（注册说话人标签）；缺省保持 "user"。
        """
        return await self.process_message(room_id, utterance, role="user", meta=meta)

    async def process_audience_message(
        self, text: str, userid: str = "", username: str = ""
    ) -> Optional[dict]:
        """观众弹幕便捷入口：找到第一个进行中且开启观众席的房间并进入消息流。

        供 live_client 转发 / 外部手动弹幕调用。无匹配房间（含未开启观众席）
        时静默返回 None，不抛错。
        """
        for room in self.rooms.values():
            if room.state == RoomState.IN_MEETING and room.audience_enabled:
                return await self.process_message(
                    room.room_id,
                    text,
                    role="audience",
                    meta={"userid": userid or "", "username": username or ""},
                )
        return None

    async def process_message(
        self, room_id: str, text: str, role: str = "user", meta: Optional[Dict[str, Any]] = None
    ) -> dict:
        """统一消息入口：用户/观众消息进入互动空间消息流。

        流程：
        1) 追加转录（user → speaker="user"；audience → speaker="audience:<名>"）
        2) 仲裁选主答（arbiter.arbitrate → TurnDecision）
        3) 打断所有 agent（interrupt）+ 复位令牌重新调度
        4) 主答 acquire → _drive_turn → release
        5) 插话循环：在场其他 Agent 按 _should_interject 依次接话（连续 agent-agent 对话）
        6) _ingest_context + _broadcast

        Args:
            room_id: 房间号。
            text: 消息内容（user/audience 的原始话语）。
            role: 消息角色（"user"=用户/主播，"audience"=观众弹幕）。
            meta: 可选补充信息 dict，支持 {userid, username, mention, speaker_label}。
                speaker_label 为注册说话人标签（Task 7.2），user 追加转录时使用，
                缺省保持 "user"。

        Returns:
            结构化的回合结果 dict:
            {"decision", "turns", "transcript_turns"}。
        """
        room = self._require_room(room_id)
        text = (text or "").strip()
        meta = meta or {}

        # 1) 追加转录
        if role == "audience":
            username = meta.get("username") or meta.get("userid") or "guest"
            room.transcript.append(f"audience:{username}", "audience", text)
        else:
            # Task 7.2：user 转录支持可选说话人标签（注册名），缺省保持 "user"。
            # 现状：会议室 user 输入为 REST 纯文本（/meeting/{room}/speak），
            # 不流经流式 ASR，故业务入口当前不传 speaker_label（传空即默认 user）。
            speaker_label = meta.get("speaker_label") or "user"
            room.transcript.append(speaker_label, "user", text)

        # 2) 仲裁（先算谁做主答）
        decision = await self.arbiter.arbitrate(text, room)

        # 3) 用户/观众开口 = 最高优先级打断：收回令牌 + 复位以便重新授权
        await self.interrupt.on_user_speech(room)
        await room.token.reset()

        responder = self._responder
        turns: List[dict] = []
        chosen = decision.speaker

        if chosen:
            granted = await room.token.acquire(chosen)
            if granted:
                # try/finally 保证 _drive_turn 任意异常下令牌必然释放；
                # finally 只释放、不吞异常，原异常照常向上抛
                try:
                    await self._drive_turn(room, chosen, text, responder, turns)
                finally:
                    await room.token.release(chosen)
            # 4) 插话：在场其他 Agent 按插话判定依次接话（连续 agent-agent 对话）
            await self._run_interjections(room, text, chosen, turns, responder)

        # 观众弹幕：对产出的 agent 回复发射 danmaku_reply 事件（供前端弹幕房展示，T3）
        if role == "audience" and turns:
            username = meta.get("username") or meta.get("userid") or "guest"
            await self._emit_danmaku_replies(room_id, turns, username)

        # 5) 转录有界化：条目超阈值即压缩更早历史，避免 transcript.entries 无界膨胀
        self._maybe_summarize_older(room)

        # 6) 写回上下文（复用 ContextManager，可选）+ 广播
        await self._ingest_context(room)

        await self._broadcast(room)
        return {
            "decision": decision.to_dict(),
            "turns": turns,
            "transcript_turns": len(room.transcript),
        }

    async def _run_interjections(
        self,
        room: MeetingRoom,
        trigger_text: str,
        main_speaker: str,
        turns: List[dict],
        responder: Optional[Responder],
    ) -> None:
        """让按 _should_interject 命中的在场 Agent 依次插话（连续 agent-agent 对话）。

        每次只驱动一个命中候选，经令牌互斥 + relay_pause_sec 串行接话；已讲过的
        agent 不再重复，直到无新命中或达上限（避免无限自发对话）。用户/观众新消息
        会经 token.reset() 清空一切排队，从而强制打断回到人为主导。
        """
        spoke = {main_speaker}
        guard = 0
        while guard < 5:  # 连续对话上限（防自说自话失控）
            guard += 1
            hit = None
            for a in room.agents:
                if a.agent_id in spoke:
                    continue
                if self._should_interject(room, a.agent_id, trigger_text):
                    hit = a.agent_id
                    break
            if hit is None:
                break
            granted = await room.token.acquire(hit)
            if granted:
                # try/finally 保证本回合任意异常下令牌必然释放；finally 只释放不吞异常
                try:
                    await asyncio.sleep(self.relay_pause_sec)
                    reply = await self._drive_turn(room, hit, trigger_text, responder, turns)
                    if reply:
                        spoke.add(hit)
                finally:
                    await room.token.release(hit)

    def _should_interject(self, room: MeetingRoom, agent_id: str, last_text: str) -> bool:
        """插话判定：是否允许某 agent 就该消息发言。

        判定规则（最小实现）：
        - 点名不抢话：若 last_text 点名/提及了其他 agent，则本 agent 不插话；
        - 关键词/主题重叠：last_text 与 agent.name/persona 关键词做包含/重叠检查；
        - 随机门控：random.random() < speech_rate（AgentMember 尚未扩展 speech_rate
          字段，统一使用全局 speech_rate）。
        """
        agent = room.get_agent(agent_id)
        if agent is None:
            return False
        # 点名不抢话（若文本点名了其他 agent，本 agent 尊重被点名者优先级）
        if self._text_addresses_other(agent_id, last_text, room):
            return False
        # 关键词/主题重叠（最小实现）
        if not self._keyword_overlap(agent, last_text):
            return False
        # 随机门控
        return random.random() < self.speech_rate

    def _text_addresses_other(self, agent_id: str, text: str, room: MeetingRoom) -> bool:
        """判断 text 是否点名/提及了本 agent 之外的某个 agent。"""
        addressed = self.arbiter.find_addressed_agent(text, list(room.agents))
        return addressed is not None and addressed != agent_id

    def _keyword_overlap(self, agent: AgentMember, last_text: str) -> bool:
        """关键词/主题重叠（最小实现）：name 或 persona 关键词出现在 last_text 中。"""
        if agent.name and agent.name in last_text:
            return True
        if agent.persona:
            if agent.persona in last_text:
                return True
            tokens = [
                t
                for t in agent.persona.replace(",", " ").replace("，", " ").split()
                if t
            ]
            if any(t in last_text for t in tokens if len(t) >= 2):
                return True
        return False

    async def toggle_audience(self, room_id: str, enabled: bool) -> MeetingRoom:
        """开启/关闭观众席（互动空间），并联动弹幕连接器启停。

        启用时按 ``danmaku_source`` 创建并启动连接器；停用/换源时停止并清理。
        """
        room = self._require_room(room_id)
        room.audience_enabled = bool(enabled)
        if room.audience_enabled:
            await self._start_danmaku(room_id)
        else:
            await self._stop_danmaku(room_id)
        logger.info("会议 %s 观众席启用=%s", room.room_id, room.audience_enabled)
        await self._broadcast(room)
        return room

    # ================================================================ 弹幕连接器
    async def _start_danmaku(self, room_id: str) -> None:
        """创建并启动弹幕连接器（type=none 时无副作用）。"""
        # 已在运行的同房间连接器先停止，避免重复装配
        if self._connector.get(room_id) is not None:
            await self._stop_danmaku(room_id)
        connector = create_connector(
            self._danmaku_source, on_danmaku=self._make_danmaku_cb(room_id)
        )
        if connector is None:
            logger.info("会议 %s 弹幕源 type=none，不创建连接器", room_id)
            return
        self._connector[room_id] = connector
        await connector.start()
        logger.info("会议 %s 弹幕连接器启动: %s", room_id, type(connector).__name__)

    async def _stop_danmaku(self, room_id: str) -> None:
        """停止并清理房间的弹幕连接器（不存在则静默跳过）。"""
        connector = self._connector.pop(room_id, None)
        if connector is None:
            return
        try:
            await connector.stop()
        except Exception as e:  # 停止失败不影响观众席状态切换
            logger.warning("会议 %s 弹幕连接器停止异常: %s", room_id, e)

    def _make_danmaku_cb(self, room_id: str) -> Callable:
        """构造绑定当前房间的弹幕回调（async (userid, username, text)）。"""

        async def _on_danmaku(userid: str, username: str, text: str) -> None:
            await self.process_message(
                room_id,
                text,
                role="audience",
                meta={"userid": userid, "username": username},
            )

        return _on_danmaku

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

    def _maybe_summarize_older(self, room: MeetingRoom) -> None:
        """转录条目超阈值时，把更早历史压缩进 older_summary，保证 entries 有界。

        阈值取 max_turns 的 2 倍：压缩后仅保留最近窗口（render_context 用），
        更早条目收敛为一段摘要，避免 transcript.entries 随会议进程无界增长。
        达阈值才触发，避免每轮都做 O(n) 前缀重算与频繁压缩。
        """
        if not room.transcript.summary_enabled:
            return
        if len(room.transcript) >= self._transcript_max_turns * 2:
            room.transcript.summarize_older(max_turns=self._transcript_max_turns)

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
