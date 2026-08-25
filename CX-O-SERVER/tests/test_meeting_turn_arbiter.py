"""TurnArbiter 主答选择单元测试（§6，重塑后）。

覆盖：点名优先 / 启发式主答（无 LLM 时取发言欲最高者）/ LLM 指定主答 /
共情回落 / 忽略 / @点名识别。
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
        """点名直给：主答直给被点名的 agent（mode=primary）。"""
        room = _room("r1", ("A", 0.3, 0.3), ("小悠", 0.9, 0.9))
        arbiter = TurnArbiter(
            interpret=lambda u, a: IntentionResult(IntentType.ADDRESSED, target="小悠")
        )
        decision = await arbiter.arbitrate("小悠你说", room)
        assert decision.mode == "primary"
        assert decision.speaker == "小悠"
        assert decision.intent == IntentType.ADDRESSED

    async def test_open_discussion_heuristic_primary(self):
        """开放提问：无 LLM 时主答取发言欲（motivation）最高者。"""
        room = _room("r2", ("A", 0.5, 0.5), ("B", 0.9, 0.9), ("C", 0.2, 0.2))
        arbiter = TurnArbiter()  # 默认启发式
        decision = await arbiter.arbitrate("大家觉得呢", room)
        assert decision.mode == "primary"
        assert decision.speaker == "B"  # 发言欲最高
        assert decision.intent == IntentType.OPEN_DISCUSSION

    async def test_llm_target_selects_primary(self):
        """注入 interpret（LLM）通过 target 指定主答者。"""
        room = _room("r3", ("A", 0.2, 0.2), ("B", 0.1, 0.1), ("C", 0.9, 0.9))
        arbiter = TurnArbiter(
            interpret=lambda u, a: IntentionResult(IntentType.OPEN_DISCUSSION, target="A")
        )
        decision = await arbiter.arbitrate("大家谈谈", room)
        assert decision.mode == "primary"
        assert decision.speaker == "A"  # 尊重 LLM 选择，而非发言欲最高的 C
        assert decision.intent == IntentType.OPEN_DISCUSSION

    async def test_empathy_falls_back_to_primary(self):
        """陈述共情：回到主答选择（发言欲最高者）。"""
        room = _room("r5", ("A", 0.9, 0.3), ("B", 0.3, 0.3), ("C", 0.2, 0.2))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("今天好累", room)
        assert decision.intent == IntentType.EMPATHY
        assert decision.mode == "primary"
        assert decision.speaker == "A"

    async def test_ignore_no_speaker(self):
        """自言自语：无人回应。"""
        room = _room("r6", ("A", 0.5, 0.5))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("哦", room)
        assert decision.intent == IntentType.IGNORE
        assert decision.mode == "primary"
        assert decision.speaker is None

    async def test_default_heuristic_detects_addressing(self):
        """缺省启发式能识别"点名"。"""
        room = _room("r7", ("小悠", 0.5, 0.5))
        arbiter = TurnArbiter()  # 无注入 → 默认启发式
        decision = await arbiter.arbitrate("小悠悠，你说说看", room)
        assert decision.intent == IntentType.ADDRESSED
        assert decision.speaker == "小悠"

    async def test_at_mention_detects_addressing(self):
        """@agent 形式点名识别。"""
        room = _room("r9", ("小悠", 0.5, 0.5), ("阿光", 0.5, 0.5))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("@小悠 来一个", room)
        assert decision.intent == IntentType.ADDRESSED
        assert decision.speaker == "小悠"

    async def test_open_question_marks(self):
        """带问号的默认判为开放提问。"""
        room = _room("r8", ("A", 0.7, 0.7), ("B", 0.3, 0.3))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("周末去哪玩呢？", room)
        assert decision.intent == IntentType.OPEN_DISCUSSION
        assert decision.mode == "primary"
        assert decision.speaker == "A"

    async def test_participants_list_includes_all(self):
        """participants 为在场候选清单。"""
        room = _room("r10", ("A", 0.5, 0.5), ("B", 0.5, 0.5), ("C", 0.5, 0.5))
        arbiter = TurnArbiter()
        decision = await arbiter.arbitrate("大家聊起来", room)
        assert decision.participants == ["A", "B", "C"]