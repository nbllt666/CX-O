"""模块三 · TurnArbiter —— 主答选择器（互动空间）。

决定"这条消息谁做主答者"：点名指谁、开放讨论让谁先接。其余在场 Agent 由
coordinator 按 ``speech_rate`` 与人设命中自发插话（见 coordinator._should_interject）。

设计基准：《CX-O 多 Agent 会议重定位为互动空间》T2。

- 意图解析 ``parse_intent``：可注入独立小模型解释器 ``interpret``（缺省为启发式）。
- 主答选择 ``arbitrate``：点名→被点名者优先；注入 interpret 给出说话者→采用；
  否则启发式兜底取 room 中发言欲（motivation）最高者。输出统一 ``mode="primary"``，
  移除旧四模式（moderator/relevance/round_robin/empathy）机械分发。
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional

from server.core.meeting.models import (
    DEFAULT_MODE,
    VALID_MODES,
    AgentMember,
    IntentType,
    IntentionResult,
    TurnDecision,
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

# 主答选择的统一模式标识（取代旧四模式）
PRIMARY_MODE = "primary"


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
    """主答选择器。

    Args:
        interpret: 可注入的意图/主答解释器；缺省用启发式 ``_default_interpret``。
        default_mode: 兼容保留的历史默认模式字段（不再参与分发，仅校验存留）。
    """

    def __init__(
        self,
        interpret: Optional[InterpretFunc] = None,
        default_mode: str = DEFAULT_MODE,
    ):
        self._interpret: Optional[InterpretFunc] = interpret
        self.default_mode: str = default_mode if default_mode in VALID_MODES else DEFAULT_MODE

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

        覆盖点名（@agent + agent 名 + 点名信号）、开放提问、共情、自言自语。
        """
        text = (user_utterance or "").strip()
        if not text:
            return IntentionResult(IntentType.IGNORE, reason="空白输入")

        # 1) 点名：@agent 提及 或 agent 名 + 点名信号
        for agent in agents:
            names = {agent.display_name, agent.name, agent.agent_id}
            hit_name = next((n for n in names if n and n in text), None)
            if hit_name:
                at_mention = ("@" + hit_name) in text
                if at_mention or any(sig in text for sig in _ADDR_SIGNAL):
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

    # ---------------------------------------------------------------- 主答选择
    async def arbitrate(self, user_utterance: str, room) -> TurnDecision:
        """仲裁"这条消息谁做主答"，返回主答选择结果（mode="primary"）。"""
        agents = list(getattr(room, "agents", []) or [])
        if not agents:
            return TurnDecision(PRIMARY_MODE, speaker=None, intent=IntentType.IGNORE, reason="无参会 Agent")

        intent = await self.parse_intent(user_utterance, agents)

        # 点名 → 被点名者优先
        if intent.type == IntentType.ADDRESSED:
            target = self._resolve_target(intent.target, agents)
            return TurnDecision(
                PRIMARY_MODE,
                speaker=target,
                participants=[a.agent_id for a in agents],
                intent=intent.type,
                reason=intent.reason or "点名直给",
            )

        # 自言自语 → 无人回应
        if intent.type == IntentType.IGNORE:
            return TurnDecision(
                PRIMARY_MODE,
                speaker=None,
                participants=[a.agent_id for a in agents],
                intent=intent.type,
                reason=intent.reason or "自言自语",
            )

        # 其余意图：注入 interpret（LLM）可能通过 target 直接给出主答者
        speaker = self._resolve_target(intent.target, agents)
        if speaker is None:
            # 启发式兜底：发言欲（motivation）最高者
            chosen = max(agents, key=lambda a: a.motivation)
            speaker = chosen.agent_id if chosen else None
            reason = "启发式主答：发言欲最高"
        else:
            reason = "LLM 指定主答"

        return TurnDecision(
            PRIMARY_MODE,
            speaker=speaker,
            participants=[a.agent_id for a in agents],
            intent=intent.type,
            reason=reason,
        )

    def _resolve_target(self, target: Optional[str], agents: List[AgentMember]) -> Optional[str]:
        """把目标解析为真实 agent_id（支持名/展示名匹配，找不到返回 None）。"""
        if not target:
            return None
        for a in agents:
            if a.agent_id == target or a.name == target or a.display_name == target:
                return a.agent_id
        return None

    def find_addressed_agent(self, text: str, agents: List[AgentMember]) -> Optional[str]:
        """识别 text 是否点名/提及某 agent，是则返回其 agent_id，否则 None。

        供 coordinator._should_interject 判定"点名不抢话"。
        """
        for agent in agents:
            names = {agent.display_name, agent.name, agent.agent_id}
            for n in names:
                if n and n in text and (
                    ("@" + n) in text
                    or any(sig in text for sig in _ADDR_SIGNAL)
                ):
                    return agent.agent_id
        return None