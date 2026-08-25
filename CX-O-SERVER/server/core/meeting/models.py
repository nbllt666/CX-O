"""多 Agent 语音会议协调器 —— 共享数据模型与枚举。

本文件是 ``server/core/meeting/`` 各模块的公共类型载体，避免循环导入：

- 状态/意图枚举：``RoomState`` / ``TokenState`` / ``IntentType``
- 数据结构：``AgentMember``（参会 Agent 成员） / ``TranscriptEntry``（会议记录条目）
- 决策封装：``IntentionResult``（意图解析结果） / ``TurnDecision``（发言权裁决结果）

设计基准见《CX-O 多 Agent 语音会议协调器》§2 核心概念与 §4-§9 各模块。
"""
from __future__ import annotations

import enum
import time
from datetime import datetime
from typing import Any, List, Optional

# 默认会议发言模式（对齐 config.meeting.default_mode）
DEFAULT_MODE = "moderator"

# 可选的发言模式集合（点名/主持人/相关性竞争/轮询）
VALID_MODES = ("addressed", "moderator", "relevance", "round_robin")


class RoomState(str, enum.Enum):
    """会议房间状态：IDLE(未开始) / IN_MEETING(进行中) / PAUSED(暂停)。"""

    IDLE = "idle"
    IN_MEETING = "in_meeting"
    PAUSED = "paused"


class TokenState(str, enum.Enum):
    """发言令牌状态：IDLE(空闲) / HELD(被持有) / REVOKED(已强制收回)。"""

    IDLE = "idle"
    HELD = "held"
    REVOKED = "revoked"


class IntentType(str, enum.Enum):
    """用户话语的意图类型：

    - ADDRESSED         点名（"小悠你说"）
    - OPEN_DISCUSSION   开放提问（"大家觉得呢"）
    - EMPATHY           陈述共情（"今天好累"）
    - IGNORE            自言自语（无需回应）
    - DOMAIN            明确问某领域（"天气怎么样"）
    """

    ADDRESSED = "addressed"
    OPEN_DISCUSSION = "open_discussion"
    EMPATHY = "empathy"
    IGNORE = "ignore"
    DOMAIN = "domain"


class IntentionResult:
    """意图解析输出。

    Attributes:
        type: 意图类型。
        target: 点名时的目标 agent_id（仅 ADDRESSED 有值）。
        domain: DOMAIN 意图命中的领域关键词（可选）。
        reason: 解析理由（供审计/调试）。
    """

    __slots__ = ("type", "target", "domain", "reason")

    def __init__(
        self,
        type: IntentType,
        target: Optional[str] = None,
        domain: Optional[str] = None,
        reason: str = "",
    ):
        self.type = type
        self.target = target
        self.domain = domain
        self.reason = reason

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的字典。"""
        return {
            "type": self.type.value,
            "target": self.target,
            "domain": self.domain,
            "reason": self.reason,
        }


class TurnDecision:
    """主答选择结果。

    Attributes:
        mode: 采用的分发模式，群聊式多态回应统一为 "primary"（主答选择）。
        speaker: 被选中的主答者 agent_id；None 表示无人回应（IGNORE）。
        participants: 在场候选 agent 清单（供前端高亮）。
        intent: 触发本裁决的意图类型。
        reason: 裁决理由。
    """

    __slots__ = ("mode", "speaker", "participants", "intent", "reason")

    def __init__(
        self,
        mode: str,
        speaker: Optional[str] = None,
        participants: List[str] = None,
        intent: Optional[IntentType] = None,
        reason: str = "",
    ):
        self.mode = mode
        self.speaker = speaker
        self.participants = participants or []
        self.intent = intent
        self.reason = reason

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的字典。"""
        return {
            "mode": self.mode,
            "speaker": self.speaker,
            "participants": self.participants,
            "intent": self.intent.value if self.intent else None,
            "reason": self.reason,
        }


class AgentMember:
    """参会 Agent 成员。

    内部会话（``session``）可关联现有 ``DualStreamSession``（server/handlers/audio.py），
    亦可不携带会话仅作为元数据存在（纯内存/测试场景）。发言欲由相关度与社交欲合成。

    Attributes:
        agent_id: 全局唯一 agent 标识。
        name: 展示名（默认回退为 agent_id）。
        persona: 人设简述（供裁决器判断相关度/共情）。
        relevance: 与当前话题的相关度（0-1，讨论时动态评估）。
        desire_to_speak: 发言欲/社交需求（0-1）。
        voice: 音色标识（声音克隆，供 AudioRouter 区分）。
        session: 关联的语音会话对象（可选）。
        interrupted: 是否处于被打断状态。
    """

    __slots__ = (
        "agent_id",
        "name",
        "persona",
        "relevance",
        "desire_to_speak",
        "voice",
        "session",
        "interrupted",
    )

    def __init__(
        self,
        agent_id: str,
        name: str = "",
        persona: str = "",
        relevance: float = 0.5,
        desire_to_speak: float = 0.5,
        voice: Optional[str] = None,
        session: Any = None,
        interrupted: bool = False,
    ):
        self.agent_id = agent_id
        self.name = name or agent_id
        self.persona = persona
        self.relevance = float(relevance)
        self.desire_to_speak = float(desire_to_speak)
        self.voice = voice
        self.session = session
        self.interrupted = interrupted

    @property
    def display_name(self) -> str:
        """展示名：优先 name，其次 agent_id。"""
        return self.name or self.agent_id

    @property
    def motivation(self) -> float:
        """发言欲：好奇心(相关度) + 社交需求(发言欲)，合成 0-1。"""
        return min(1.0, 0.6 * self.relevance + 0.4 * self.desire_to_speak)

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的字典（不含 session 内部细节）。"""
        return {
            "agent_id": self.agent_id,
            "name": self.display_name,
            "persona": self.persona,
            "relevance": self.relevance,
            "desire_to_speak": self.desire_to_speak,
            "voice": self.voice,
            "interrupted": self.interrupted,
        }


class TranscriptEntry:
    """会议记录单条。

    Attributes:
        speaker: 说话者标识（user 或 agent_id）。
        role: 角色（user / agent / system）。
        text: 说话内容。
        ts: 时间戳（ISO 字符串，默认当前时间）。
    """

    __slots__ = ("speaker", "role", "text", "ts")

    def __init__(
        self,
        speaker: str,
        role: str,
        text: str,
        ts: Optional[str] = None,
    ):
        self.speaker = speaker
        self.role = role
        self.text = text
        self.ts = ts or datetime.now().isoformat(timespec="milliseconds")

    def to_dict(self) -> dict:
        """转为可 JSON 序列化的字典。"""
        return {"speaker": self.speaker, "role": self.role, "text": self.text, "ts": self.ts}


def now_ts() -> str:
    """返回当前时间戳（供外部复用，degree 统一格式）。"""
    return datetime.now().isoformat(timespec="milliseconds")


def timeticks() -> float:
    """返回单调时钟秒（供轮询/超时类计算使用）。"""
    return time.monotonic()