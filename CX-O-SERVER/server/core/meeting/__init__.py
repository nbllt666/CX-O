"""多 Agent 语音会议协调器（MeetingRoom）包。

设计基准：《CX-O 多 Agent 语音会议协调器》。

七大模块：
- ``room``          MeetingRoom 共享房间
- ``token``         SpeakingToken 发言令牌
- ``turn_arbiter``  TurnArbiter 发言权仲裁
- ``interrupt_coord`` InterruptCoordinator 多向打断
- ``transcript``    MeetingTranscript 会议记录
- ``audio_router``  AudioRouter 音频路由
- ``coordinator``   MeetingCoordinator 圆桌导演（总控）
"""
from __future__ import annotations

from server.core.meeting.audio_router import AudioRouter
from server.core.meeting.coordinator import MeetingCoordinator
from server.core.meeting.interrupt_coord import InterruptCoordinator
from server.core.meeting.models import (
    AgentMember,
    IntentType,
    IntentionResult,
    RoomState,
    TokenState,
    TranscriptEntry,
    TurnDecision,
)
from server.core.meeting.room import MeetingRoom
from server.core.meeting.token import SpeakingToken
from server.core.meeting.transcript import MeetingTranscript
from server.core.meeting.turn_arbiter import TurnArbiter

__all__ = [
    "AudioRouter",
    "MeetingCoordinator",
    "InterruptCoordinator",
    "MeetingRoom",
    "SpeakingToken",
    "MeetingTranscript",
    "TurnArbiter",
    "AgentMember",
    "IntentionResult",
    "TranscriptEntry",
    "TurnDecision",
    "RoomState",
    "TokenState",
    "IntentType",
]