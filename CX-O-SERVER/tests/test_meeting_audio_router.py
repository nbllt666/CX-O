"""AudioRouter 音频路由单元测试（§9）。

覆盖：令牌门控（仅持有者放行）、非持有者静音、附和混音开关与音量。
运行：python -m pytest tests/test_meeting_audio_router.py -v
"""
import pytest

from server.core.meeting.audio_router import AudioRouter
from server.core.meeting.models import AgentMember
from server.core.meeting.room import MeetingRoom
from server.core.meeting.token import SpeakingToken


class TestAudioRouter:
    def _room(self):
        return MeetingRoom(
            room_id="ar",
            user="user",
            agents=[AgentMember("A"), AgentMember("B")],
            token=SpeakingToken(),
        )

    @pytest.mark.asyncio
    async def test_route_allows_only_holder(self):
        """仅令牌持有者放行其 TTS 流。"""
        room = self._room()
        router = AudioRouter()
        await room.token.acquire("A")

        # A 持牌 → 放行（返回迭代器）
        stream = await router.route("A", self._chunks(), room)
        assert stream is not None
        gathered = [c async for c in stream]
        assert gathered == ["chunk1", "chunk2"]

        # B 未持牌 → 静音（返回 None）
        assert await router.route("B", self._chunks(), room) is None

    @pytest.mark.asyncio
    async def test_route_returns_none_when_no_holder(self):
        """无持牌者时任何人路由都静音。"""
        room = self._room()
        router = AudioRouter()
        assert await router.route("A", self._chunks(), room) is None

    @pytest.mark.asyncio
    async def test_route_after_turn_change(self):
        """令牌转手后新持有者放行。"""
        room = self._room()
        router = AudioRouter()
        await room.token.acquire("A")
        await room.token.release("A")
        await room.token.acquire("B")
        assert await router.route("A", self._chunks(), room) is None
        assert await router.route("B", self._chunks(), room) is not None

    @pytest.mark.asyncio
    async def test_is_allowed(self):
        """is_allowed 门控跟随令牌持有人。"""
        room = self._room()
        router = AudioRouter()
        assert router.is_allowed("A", room) is False
        await room.token.acquire("A")
        assert router.is_allowed("A", room) is True
        assert router.is_allowed("B", room) is False

    def test_backchannel_disabled_passthrough(self):
        """附和关闭时 mix_backchannel 原样透传。"""
        router = AudioRouter(backchannel_enabled=False)
        assert router.mix_backchannel(b"data") == b"data"

    def test_backchannel_default_off(self):
        router = AudioRouter()
        assert router.backchannel_enabled is False
        assert router.backchannel_volume == 0.2

    async def _chunks(self):
        yield "chunk1"
        yield "chunk2"