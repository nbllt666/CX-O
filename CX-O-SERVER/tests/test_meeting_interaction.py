"""互动空间群聊式多态回应单元测试（T2）。

覆盖：插话门控（speech_rate=0 不插话 / rate=1 且关键词命中才插话）、
连续 agent-agent 对话在用户新消息时打断、audience 角色转录写入。
运行：python -m pytest tests/test_meeting_interaction.py -v
"""
import pytest

from server.core.meeting.coordinator import MeetingCoordinator
from server.core.meeting.models import AgentMember


def _coordinator(**kwargs) -> MeetingCoordinator:
    """构造固定回应的协调器（relay 间隔极小，避免测试卡顿）。"""
    kw = {"relay_pause_sec": 0.001}
    kw.update(kwargs)
    return MeetingCoordinator(responder=lambda r, a, t: "收到", **kw)


@pytest.mark.asyncio
class TestInterjection:
    async def test_no_interject_when_rate_zero(self):
        """speech_rate=0：主答后其他 Agent 不插话。"""
        coord = _coordinator(speech_rate=0.0)
        await coord.start_meeting(
            user="用户",
            agents=[
                AgentMember("A", persona="天气", relevance=0.9, desire_to_speak=0.9),
                AgentMember("B", persona="天气"),
            ],
            room_id="ri0",
        )
        result = await coord.process_user_speech("ri0", "聊天气")
        assert [t["speaker"] for t in result["turns"]] == ["A"]

    async def test_interject_when_rate_one_and_keyword(self):
        """speech_rate=1 且关键词命中：主答后其他 Agent 插话。"""
        coord = _coordinator(speech_rate=1.0)
        await coord.start_meeting(
            user="用户",
            agents=[
                AgentMember("A", persona="天气", relevance=0.9, desire_to_speak=0.9),
                AgentMember("B", persona="天气"),
            ],
            room_id="ri1",
        )
        result = await coord.process_user_speech("ri1", "聊天气")
        speakers = [t["speaker"] for t in result["turns"]]
        assert "A" in speakers
        assert "B" in speakers  # 关键词命中 + rate=1 → B 插话

    async def test_no_interject_when_keyword_missing(self):
        """speech_rate=1 但关键词不重叠：仍不插话。"""
        coord = _coordinator(speech_rate=1.0)
        await coord.start_meeting(
            user="用户",
            agents=[
                AgentMember("A", persona="天气", relevance=0.9, desire_to_speak=0.9),
                AgentMember("B", persona="音乐"),
            ],
            room_id="ri4",
        )
        result = await coord.process_user_speech("ri4", "聊天气")
        # B 的人设关键词"音乐"与"聊天气"不重叠 → 不插话
        assert [t["speaker"] for t in result["turns"]] == ["A"]

    async def test_new_user_message_interrupts_agent_chain(self):
        """连续 agent-agent 对话：用户新消息强制打断（令牌复位、排队清空）。"""
        coord = _coordinator(speech_rate=1.0)
        await coord.start_meeting(
            user="用户",
            agents=[
                AgentMember("A", persona="天气", relevance=0.9, desire_to_speak=0.9),
                AgentMember("B", persona="天气"),
            ],
            room_id="ri2",
        )
        r1 = await coord.process_user_speech("ri2", "聊天气")
        assert "A" in [t["speaker"] for t in r1["turns"]]
        assert "B" in [t["speaker"] for t in r1["turns"]]

        room = coord.get_room("ri2")
        # 连续对话后令牌应为空闲，排队队列被清空
        assert room.token.who_holds() is None
        assert not room.token.pending_queue

        # 用户新消息（无关键词重叠）→ 令牌已复位，无残留排队 agent 说话
        r2 = await coord.process_user_speech("ri2", "换个话题吧")
        assert [t["speaker"] for t in r2["turns"]] == ["A"]
        assert room.token.who_holds() is None
        assert not room.token.pending_queue


@pytest.mark.asyncio
class TestAudienceDanmaku:
    async def test_process_audience_message_finds_active_room(self):
        """process_audience_message 找到进行中且开启观众席的房间并转录 audience。"""
        coord = _coordinator()
        await coord.start_meeting(
            user="用户", agents=[AgentMember("A")], room_id="da1", audience_enabled=True
        )
        result = await coord.process_audience_message("主播好", userid="u1", username="水友")
        assert result is not None
        entries = coord.get_room("da1").transcript.entries
        assert entries[0].role == "audience"
        assert entries[0].speaker == "audience:水友"

    async def test_process_audience_message_none_when_disabled(self):
        """无开启观众席的活跃房间时静默返回 None。"""
        coord = _coordinator()
        await coord.start_meeting(user="用户", agents=[AgentMember("A")], room_id="da2")
        result = await coord.process_audience_message("hello")
        assert result is None
        assert coord.get_room("da2").transcript.entries == []

    async def test_toggle_audience_none_no_connector(self):
        """toggle_audience(enabled=True) 且 danmaku_source type=none 时不创建连接器（无副作用）。"""
        coord = _coordinator(danmaku_source={"type": "none"})
        await coord.start_meeting(user="用户", agents=[AgentMember("A")], room_id="da3")
        room = await coord.toggle_audience("da3", True)
        assert room.audience_enabled is True
        assert "da3" not in coord._connector  # type=none → 不落连接器表

        # 关闭观众席同样无副作用
        await coord.toggle_audience("da3", False)
        assert coord.get_room("da3").audience_enabled is False

    async def test_danmaku_reply_broadcast_shape(self):
        """audience 消息产出 agent 回复时，danmaku_reply 广播事件形状正确。"""
        coord = _coordinator()
        await coord.start_meeting(
            user="用户", agents=[AgentMember("A")], room_id="da4", audience_enabled=True
        )
        reply_payloads = []

        def fake_reply_cb(payload):
            reply_payloads.append(payload)

        coord.register_danmaku_reply(fake_reply_cb)
        await coord.process_message(
            "da4", "主播你好", role="audience", meta={"username": "水友", "userid": "u1"}
        )

        assert reply_payloads, "应发射 danmaku_reply 事件"
        first = reply_payloads[0]
        assert first["type"] == "danmaku_reply"
        assert first["room_id"] == "da4"
        assert first["agent_id"] == "A"
        assert first["username"] == "水友"
        assert first["text"]  # 非空回复


@pytest.mark.asyncio
class TestAudienceTranscription:
    async def test_audience_role_written_to_room(self):
        """audience 角色消息以「audience:<名>」写入转录与最近消息流。"""
        coord = _coordinator()
        await coord.start_meeting(user="用户", agents=[AgentMember("A")], room_id="ri3")
        await coord.process_message(
            "ri3", "主播你好", role="audience", meta={"username": "水友123", "userid": "u1"}
        )
        room = coord.get_room("ri3")
        entries = room.transcript.entries
        assert entries[0].role == "audience"
        assert entries[0].speaker == "audience:水友123"
        # 上下文渲染为「观众 用户名: 内容」
        ctx = room.transcript.render_context(20)
        assert "观众 水友123: 主播你好" in ctx
        # 最近消息流含 audience 条目
        recent = room.to_dict()["recent_messages"]
        assert recent[0]["role"] == "audience"
        assert recent[0]["speaker"] == "audience:水友123"

        # 无 username/userid 时回退 "guest"
        await coord.process_message("ri3", "大家好", role="audience", meta={})
        speakers = [e.speaker for e in coord.get_room("ri3").transcript.entries]
        assert "audience:guest" in speakers