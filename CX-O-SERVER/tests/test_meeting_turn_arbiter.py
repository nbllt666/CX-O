"""TurnArbiter 发言权仲裁单元测试（§6）。

覆盖：点名直给 / 主持人（默认） / 相关性竞争 / 轮询 / 共情 / 忽略 六种分发。
运行：python -m pytest tests/test_meeting_turn_arbiter.py -v
"""
import pytest

from server.core.meeting.models import AgentMember, IntentType, IntentionResult
from server.core.meeting.room import MeetingRoom
from server.core.meeting.turn_arbiter import TurnArbiter


def _room(room_id="r1", *agent_specs):
    """构造带若干 agent 的房间（agent_specs 为 (id, relevance, desire) 元组）。"""
    agents = [
        AgentMember(agent_id=aid, name=aid, relevance=rel, desire_to_speak=desire)
        for aid, rel, desire in agent_specs
    ]
    return MeetingRoom(room_id=room_id, user="user", agents=agents)


@pytest.mark.asyncio
class TestTurnArbiter:
    async def test_addressed_direct_to_target(self):
        """点名直给：令牌直给被点名的 agent。"""
        room = _room("r1", ("A", 0.3, 0.3), ("小悠", 0.9, 0.9))
        arbiter = TurnArbiter(
            interpret=lambda u, a: IntentionResult(IntentType.ADDRESSED, target="小悠")
        )
        decision = await arbiter.arbitrate("小悠你说", room)
        assert decision.mode == "addressed"
        assert decision.speaker == "小悠"
        assert decision.intent == IntentType.ADDRESSED

    async def test_open_discussion_moderator_default(self):
        """开放提问默认主持人模式：发言欲最高者承接。"""
        room = _room("r2", ("A", 0.5, 0.5), ("B", 0.9, 0.9), ("C", 0.2, 0.2))
        arbiter = TurnArbiter()  # default_mode=moderator
        decision = await arbiter.arbitrate("大家觉得呢", room)
        assert decision.mode == "moderator"
        assert decision.speaker == "B"  # 发言欲最高
        assert decision.intent == IntentType.OPEN_DISCUSSION

    async def test_relevance_competition(self):
        """相关性竞争模式：按发言欲降序，最能说者先说。"""
        room = _room("r3", ("A", 0.6, 0.3), ("B", 0.8, 0.8), ("C", 0.1, 0.1))
        arbiter = TurnArbiter(default_mode="relevance")
        decision = await arbiter.arbitrate("讨论一下", room)
        assert decision.mode == "relevance"
        assert decision.speaker == "B"
        assert decision.participants[0] == "B"

    async def test_round_robin_turns(self):
        """轮询模式：A→B→C 机械轮流。"""
        room = _room("r4", ("A", 0, 0), ("B", 0, 0), ("C", 0, 0))
        arbiter = TurnArbiter(default_mode="round_robin")
        d1 = await arbiter.arbitrate("汇报一下", room)
        d2 = await arbiter.arbitrate("继续", room)
        d3 = await arbiter.arbitrate("再来一次", room)
        assert (d1.speaker, d2.speaker, d3.speaker) == ("A", "B", "C")

    async def test_empathy_picks_most_empathetic(self):
        """陈述共情：选最可能共情的 agent。"""
        room = _room("r5", ("A", 0.9, 0.3), ("B", 0.3, 0.3), ("C", 0.2, 0.2))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("今天好累", room)
        assert decision.intent == IntentType.EMPATHY
        assert decision.speaker == "A"

    async def test_ignore_no_speaker(self):
        """自言自语：无人回应。"""
        room = _room("r6", ("A", 0.5, 0.5))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("哦", room)
        assert decision.intent == IntentType.IGNORE
        assert decision.speaker is None

    async def test_default_heuristic_detects_addressing(self):
        """缺省启发式能识别"点名"。"""
        room = _room("r7", ("小悠", 0.5, 0.5))
        arbiter = TurnArbiter()  # 无注入 → 默认启发式
        decision = await arbiter.arbitrate("小悠悠，你说说看", room)
        assert decision.intent == IntentType.ADDRESSED
        assert decision.speaker == "小悠"

    async def test_open_question_marks(self):
        """带问号的默认判为开放提问。"""
        room = _room("r8", ("A", 0.7, 0.7), ("B", 0.3, 0.3))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("周末去哪玩呢？", room)
        assert decision.intent == IntentType.OPEN_DISCUSSION
        assert decision.speaker == "A"