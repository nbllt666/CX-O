"""模块三 · TurnArbiter —— 发言权仲裁（整个协调器的灵魂）。

决定"用户这句话谁该接、什么时候接"——它决定了会议是"优雅茶话会"还是"混乱菜市场"。

设计基准：《CX-O 多 Agent 语音会议协调器》§6。

- 意图解析 ``parse_intent``：可注入独立小模型解释器 ``interpret``（缺省为启发式）。
- 四种分发 ``arbitrate``：点名直给 / 主持人（默认） / 相关性竞争 / 轮询。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from server.core.meeting.models import (
    DEFAULT_MODE,
    AgentMember,
    IntentType,
    IntentionResult,
    TurnDecision,
    VALID_MODES,
)

# 注入意图解释器：async/sync (utterance: str, agents: List[AgentMember]) -> IntentionResult | dict
InterpretFunc = Callable[[str, List[AgentMember]], Any]

# 点名触发词：出现即视为用户点名该 agent
_ADDR_SIGNAL = ("你说", "你来说", "你的看法", "你回答", "你来讲", "你呢", "你吧", "你来说说")
# 开放提问触发词："大家" / "谁" 等
_OPEN_SIGNALS = ("大家", "你们", "谁来说", "谁来讲", "讨论一下", "聊聊", "觉得")
# 共情触发词（陈述情绪）
_EMPATHY_PREFIXES = ("今天", "最近", "我")
_EMPATHY_WORDS = ("累", "烦", "开心", "难过", "高兴", "崩溃", "辛苦", "无聊", "兴奋", "紧张")
# 自言自语/语气词（无需回应）
_IGNORE_WORDS = ("哦", "嗯", "嗯嗯", "啊", "哈哈", "哈哈哈", "好的", "好吧", "诶")


def _coerce_intention(result: Any) -> IntentionResult:
    """把注入解释器的任意返回规整为 IntentionResult。"""
    if isinstance(result, IntentionResult):
        return result
    if isinstance(result, dict):
        raw = result.get("type") or result.get("intent") or "open_discussion"
        return IntentionResult(
            type=_parse_type(raw),
            target=result.get("target"),
            domain=result.get("domain"),
            reason=result.get("reason", ""),
        )
    if isinstance(result, str):
        return IntentionResult(type=_parse_type(result))
    raise TypeError(f"无法解析意图结果: {result!r}")


def _parse_type(value: Any) -> IntentType:
    """将枚举/字符串规整为 IntentType（未知值默认开放提问）。"""
    if isinstance(value, IntentType):
        return value
    try:
        return IntentType(str(value))
    except ValueError:
        try:
            return IntentType[str(str(value).upper())]
        except (ValueError, KeyError):
            return IntentType.OPEN_DISCUSSION


class TurnArbiter:
    """发言权仲裁器。

    Args:
        interpret: 可注入的意图解释器；缺省用启发式 ``_default_interpret``。
        default_mode: 默认发言模式（moderator/relevance/round_robin）。
    """

    def __init__(
        self,
        interpret: Optional[InterpretFunc] = None,
        default_mode: str = DEFAULT_MODE,
    ):
        self._interpret: Optional[InterpretFunc] = interpret
        self.default_mode: str = default_mode if default_mode in VALID_MODES else DEFAULT_MODE
        # 轮询游标：room_id -> 下一个发言 agent 索引
        self._rr_index: Dict[str, int] = {}

    # ---------------------------------------------------------------- 意图解析
    async def parse_intent(
        self, user_utterance: str, agents: Optional[List[AgentMember]] = None
    ) -> IntentionResult:
        """解析用户话语意图。

        优先使用注入的独立小模型解释器；缺省回退启发式。
        """
        members = list(agents or [])
        if self._interpret is not None:
            raw = self._interpret(user_utterance, members)
            if asyncio.iscoroutine(raw) or hasattr(raw, "__await__"):
                raw = await raw
            return _coerce_intention(raw)
        return await asyncio.to_thread(self._default_interpret, user_utterance, members)

    def _default_interpret(
        self, user_utterance: str, agents: List[AgentMember]
    ) -> IntentionResult:
        """启发式意图解析兜底（无小模型/未注入时）。

        覆盖点名（agent 名 + 点名信号）、开放提问、共情、自言自语。
        """
        text = (user_utterance or "").strip()
        if not text:
            return IntentionResult(IntentType.IGNORE, reason="空白输入")

        # 1) 点名：某 agent 名字后跟点名信号
        for agent in agents:
            names = {agent.display_name, agent.name, agent.agent_id}
            hit_name = next((n for n in names if n and n in text), None)
            if hit_name:
                # 名字 + 任一信号 或 名字被单独提及→点名
                if any(sig in text for sig in _ADDR_SIGNAL):
                    return IntentionResult(
                        IntentType.ADDRESSED,
                        target=agent.agent_id,
                        reason=f"点名命中「{hit_name}」",
                    )

        # 2) 自言自语/语气词
        for w in _IGNORE_WORDS:
            if text.strip().lower() == w or text == w:
                return IntentionResult(IntentType.IGNORE, reason=f"语气词「{w}」")

        # 3) 开放提问
        if any(sig in text for sig in _OPEN_SIGNALS) or text.endswith(("吗", "呢", "?")):
            return IntentionResult(IntentType.OPEN_DISCUSSION, reason="开放提问")

        # 4) 共情陈述
        if any(w in text for w in _EMPATHY_WORDS) or text.startswith(tuple(_EMPATHY_PREFIXES)):
            return IntentionResult(IntentType.EMPATHY, reason="陈述共情")

        # 5) 无法判别的提问默认开放讨论
        return IntentionResult(IntentType.OPEN_DISCUSSION, reason="默认开放讨论")

    # ---------------------------------------------------------------- 仲裁分发
    async def arbitrate(self, user_utterance: str, room) -> TurnDecision:
        """仲裁"用户这句话谁该接"，返回裁决结果。"""
        agents = list(getattr(room, "agents", []) or [])
        if not agents:
            return TurnDecision("ignore", speaker=None, intent=IntentType.IGNORE, reason="无参会 Agent")

        intent = await self.parse_intent(user_utterance, agents)

        # 点名直给
        if intent.type == IntentType.ADDRESSED:
            target = self._resolve_target(intent.target, agents)
            return TurnDecision(
                "addressed",
                speaker=target,
                participants=[target] if target else [],
                intent=intent.type,
                reason=intent.reason or "点名直给",
            )

        # 自言自语 → 无人回应
        if intent.type == IntentType.IGNORE:
            return TurnDecision(
                "ignore",
                speaker=None,
                participants=[a.agent_id for a in agents],
                intent=intent.type,
                reason=intent.reason or "自言自语",
            )

        # 开放提问 / 领域提问 → 按默认模式分发
        if intent.type == IntentType.OPEN_DISCUSSION:
            return await self._dispatch_mode(room, intent)
        if intent.type == IntentType.DOMAIN:
            # 选"最擅长"该领域的 agent（退化为按相关度/发言欲竞争）
            return await self._relevance_competition(room, intent, mode="domain")

        # 共情陈述 → 选最共情的一个
        if intent.type == IntentType.EMPATHY:
            return self._most_empathetic(room, intent)

        # 兜底
        return await self._dispatch_mode(room, intent)

    async def _dispatch_mode(self, room, intent: IntentionResult) -> TurnDecision:
        """按默认模式分发开放讨论。"""
        mode = self.default_mode
        if mode == "round_robin":
            return self._round_robin(room, intent)
        if mode == "relevance":
            return await self._relevance_competition(room, intent)
        # moderator（主持人，默认）
        return self._moderator(room, intent)

    # ---------------------------------------------------------------- 各分发策略
    def _resolve_target(self, target: Optional[str], agents: List[AgentMember]) -> Optional[str]:
        """把目标解析为真实 agent_id（支持名/展示名匹配，找不到返回 None）。"""
        if not target:
            return None
        for a in agents:
            if a.agent_id == target or a.name == target or a.display_name == target:
                return a.agent_id
        return None

    def _moderator(self, room, intent: IntentionResult) -> TurnDecision:
        """主持人模式：小模型判定"谁最适合接"，缺省以发言欲最高者承接。"""
        agents = room.agents
        chosen = max(agents, key=lambda a: a.motivation) if agents else None
        return TurnDecision(
            "moderator",
            speaker=chosen.agent_id if chosen else None,
            participants=[a.agent_id for a in agents],
            intent=intent.type,
            reason="主持人分发：发言欲最高",
        )

    async def _relevance_competition(self, room, intent: IntentionResult, mode: str = "relevance") -> TurnDecision:
        """相关性竞争：发言欲(相关度+社交欲)最高者先说，其余排队。"""
        agents = sorted(room.agents, key=lambda a: a.motivation, reverse=True)
        chosen = agents[0] if agents else None
        return TurnDecision(
            mode,
            speaker=chosen.agent_id if chosen else None,
            participants=[a.agent_id for a in agents],
            intent=intent.type,
            reason="相关性竞争：发言欲最高",
        )

    def _round_robin(self, room, intent: IntentionResult) -> TurnDecision:
        """轮询：A→B→C 机械轮流。"""
        agents = room.agents
        if not agents:
            return TurnDecision("round_robin", speaker=None, intent=intent.type, reason="无参会 Agent")
        idx = self._rr_index.get(room.room_id, 0)
        chosen = agents[idx % len(agents)].agent_id
        self._rr_index[room.room_id] = idx + 1
        return TurnDecision(
            "round_robin",
            speaker=chosen,
            participants=[a.agent_id for a in agents],
            intent=intent.type,
            reason="轮询：机械轮流",
        )

    def _most_empathetic(self, room, intent: IntentionResult) -> TurnDecision:
        """共情：选最可能共情的 agent（发言欲最高）。"""
        agents = room.agents
        chosen = max(agents, key=lambda a: a.motivation) if agents else None
        return TurnDecision(
            "empathy",
            speaker=chosen.agent_id if chosen else None,
            participants=[a.agent_id for a in agents],
            intent=intent.type,
            reason="共情响应",
        )