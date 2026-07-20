"""DistillationService 预生成 Mock 实现（CX-O 迁移版）。

对应接口契约: public/interface_stub/distillation_service.pyi
对应数据契约: public/schema/distillation_session.schema.json
对应配置契约: public/config_template/radix_config.json

Mock 策略:
- 返回符合 schema 的固定样例数据
- 内存态维护 session 存储以保证 advance/get_session_status 一致性
- 异常路径通过 raise 模拟（KeyError=404 / ValueError=409）
- 真实实现就位后，切换导入路径即可替换

@version 1.1.0
@see public/interface_stub/distillation_service.pyi
@see public/schema/distillation_session.schema.json

CX-O 迁移版，基于 CXHMS v1.2.0 Mock 适配。
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Pydantic 响应模型（与 .pyi 存根保持一致，Mock 自包含）
# --------------------------------------------------------------------------- #


class StartDistillationResponse(BaseModel):
    """启动蒸馏会话响应。"""
    session_id: str
    initial_state: str
    preread_summary: Optional[str]


class AdvanceDistillationResponse(BaseModel):
    """推进蒸馏状态机响应。"""
    session_id: str
    current_state: str
    agent_action: str
    next_needed: bool


class FinalizeDistillationResponse(BaseModel):
    """终结蒸馏会话响应。"""
    stored: bool
    location: str
    memory_id: Optional[int]
    metadata: Dict[str, Any]
    reason: str


class SessionStatusResponse(BaseModel):
    """会话状态查询响应。字段与 distillation_session.schema.json 一致。"""
    session_id: str
    source_type: str
    state: str
    template_id: str
    max_turns: int
    ask_user_on_ambiguity: bool
    turns: List[Dict[str, Any]]
    preread_summary: Optional[str]
    ambiguity_questions: List[str]
    extracted_content: Optional[str]
    quality_score: Optional[float]
    created_at: str
    updated_at: Optional[str]
    finalized_at: Optional[str]
    is_finalized: bool
    error_message: Optional[str]


# --------------------------------------------------------------------------- #
# 状态机定义（与 distillation_session.schema.json enum 一致）
# --------------------------------------------------------------------------- #

_SOURCE_TYPES = {"text", "character_card", "image", "video", "audio", "conversation_log"}

_STATES = (
    "S_INIT", "S_PREREAD", "S_QUESTION", "S_REFLECT", "S_CROSSVALIDATE",
    "S_EXTRACT", "S_STORAGE_DECISION", "S_FINALIZE", "S_REJECT",
)

_AGENT_ACTIONS = (
    "ask_user", "proceed", "reflect", "cross_validate",
    "extract", "decide", "finalize", "reject",
)

# 状态机转移表：(current_state, agent_action) -> next_state
# 与 .pyi docstring 描述的状态机一致
_TRANSITIONS: Dict[str, Dict[str, str]] = {
    "S_INIT": {"proceed": "S_PREREAD"},
    "S_PREREAD": {"ask_user": "S_QUESTION", "proceed": "S_QUESTION"},
    "S_QUESTION": {"proceed": "S_REFLECT", "ask_user": "S_QUESTION"},
    "S_REFLECT": {"proceed": "S_CROSSVALIDATE", "reflect": "S_QUESTION"},
    "S_CROSSVALIDATE": {"cross_validate": "S_EXTRACT", "proceed": "S_EXTRACT"},
    "S_EXTRACT": {"extract": "S_STORAGE_DECISION"},
    "S_STORAGE_DECISION": {"decide": "S_FINALIZE", "reject": "S_REJECT"},
    "S_FINALIZE": {"finalize": "S_FINALIZE"},
    "S_REJECT": {"reject": "S_REJECT"},
}

# 默认预读摘要样例
_PREREAD_SUMMARY = (
    "[Mock] 预读摘要：检测到一段文本数据源，包含用户对话历史与若干实体信息。"
    "疑点：实体边界不明确，需进一步澄清。"
)

# 默认疑点清单
_AMBIGUITY_QUESTIONS = [
    "[Mock] 1. 数据源中提到的“项目”是否指 RADIX-Lite？",
    "[Mock] 2. 时间戳是否需要归一化到 UTC？",
]

# 默认抽取内容
_EXTRACTED_CONTENT = (
    "[Mock] 结构化抽取结果：\n"
    "- 实体：RADIX-Lite, MemoryManager, DecisionCore\n"
    "- 关系：DecisionCore 调用 MemoryManager.write_with_decision\n"
    "- 时间：2026-07-15T10:00:00Z\n"
)


class MockDistillationService:
    """DistillationService 的 Mock 实现。

    内存态维护 session，遵循 7 状态机多轮蒸馏工作流。
    返回值通过 distillation_session.schema.json 校验。
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    async def start_distillation(
        self,
        source_type: str,
        source_ref: Optional[str],
        template_id: str,
        max_turns: int,
        ask_user_on_ambiguity: bool,
    ) -> StartDistillationResponse:
        """启动蒸馏会话。

        Mock behavior: 校验 source_type/max_turns，生成 UUID session_id，
        创建内存态 session 并进入 S_PREREAD，返回预读摘要样例。
        """
        if source_type not in _SOURCE_TYPES:
            raise ValueError(
                f"source_type 不在枚举中（422）: {source_type}"
            )
        if not (1 <= max_turns <= 6):
            raise ValueError(
                f"max_turns 超出范围 1-6（422）: {max_turns}"
            )
        if not template_id:
            raise ValueError("template_id 不能为空（422）")

        session_id = str(uuid.uuid4())
        now = _iso_now()
        session = {
            "session_id": session_id,
            "source_type": source_type,
            "source_ref": source_ref,
            "state": "S_PREREAD",
            "template_id": template_id,
            "max_turns": max_turns,
            "ask_user_on_ambiguity": ask_user_on_ambiguity,
            "turns": [
                {
                    "turn_index": 0,
                    "state": "S_INIT",
                    "agent_action": "proceed",
                    "agent_output": "[Mock] 初始化会话",
                    "user_response": None,
                    "timestamp": now,
                },
                {
                    "turn_index": 1,
                    "state": "S_PREREAD",
                    "agent_action": "proceed",
                    "agent_output": _PREREAD_SUMMARY,
                    "user_response": None,
                    "timestamp": now,
                },
            ],
            "preread_summary": _PREREAD_SUMMARY,
            "ambiguity_questions": list(_AMBIGUITY_QUESTIONS),
            "extracted_content": None,
            "quality_score": None,
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
            "is_finalized": False,
            "error_message": None,
        }
        self._sessions[session_id] = session

        return StartDistillationResponse(
            session_id=session_id,
            initial_state="S_PREREAD",
            preread_summary=_PREREAD_SUMMARY,
        )

    async def advance_distillation(
        self,
        session_id: str,
        user_response: Optional[str],
    ) -> AdvanceDistillationResponse:
        """推进蒸馏状态机一步。

        Mock behavior: 沿状态机转移表推进，记录新轮次。
        推进至 S_STORAGE_DECISION 后 next_needed=False，否则 True。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"session_id 不存在（404）: {session_id}")
        if session["is_finalized"]:
            raise ValueError(
                f"会话已终结（409）: state={session['state']}"
            )

        current_state = session["state"]
        # Mock 推进策略：按线性路径走，S_REFLECT 回环一次到 S_QUESTION
        if current_state == "S_PREREAD":
            next_state, action = "S_QUESTION", "ask_user"
            next_needed = True
        elif current_state == "S_QUESTION":
            next_state, action = "S_REFLECT", "proceed"
            next_needed = False
        elif current_state == "S_REFLECT":
            next_state, action = "S_CROSSVALIDATE", "cross_validate"
            next_needed = False
        elif current_state == "S_CROSSVALIDATE":
            next_state, action = "S_EXTRACT", "extract"
            next_needed = False
            session["extracted_content"] = _EXTRACTED_CONTENT
        elif current_state == "S_EXTRACT":
            next_state, action = "S_STORAGE_DECISION", "decide"
            session["quality_score"] = 0.82
            next_needed = False
        elif current_state == "S_STORAGE_DECISION":
            next_state, action = "S_FINALIZE", "finalize"
            session["is_finalized"] = True
            session["finalized_at"] = _iso_now()
            next_needed = False
        else:
            raise ValueError(
                f"非法状态转移（409）: current_state={current_state}"
            )

        session["state"] = next_state
        session["updated_at"] = _iso_now()
        session["turns"].append(
            {
                "turn_index": len(session["turns"]),
                "state": next_state,
                "agent_action": action,
                "agent_output": f"[Mock] 推进至 {next_state}",
                "user_response": user_response,
                "timestamp": _iso_now(),
            }
        )

        return AdvanceDistillationResponse(
            session_id=session_id,
            current_state=next_state,
            agent_action=action,
            next_needed=next_needed,
        )

    async def finalize_distillation(
        self,
        session_id: str,
        override_decision: Optional[str],
    ) -> FinalizeDistillationResponse:
        """终结蒸馏会话，执行存储决策。

        Mock behavior: 标记 session 为 finalized，返回存储结果样例。
        override_decision 非 None 时 location=permanent_memories。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"session_id 不存在（404）: {session_id}")
        if session["is_finalized"]:
            raise ValueError("会话已终结（409）")

        quality_score = session.get("quality_score") or 0.82
        if override_decision == "permanent":
            location = "permanent_memories"
            reason = "[Mock] 人类 override_decision=permanent，存入永久记忆"
        elif override_decision == "reject":
            location = "rejected"
            reason = "[Mock] 人类 override_decision=reject，拒绝存储"
        elif quality_score < 0.3:
            location = "rejected"
            reason = f"[Mock] quality_score={quality_score} 低于拒绝阈值，存入 rejected"
        else:
            location = "memories"
            reason = f"[Mock] quality_score={quality_score} 达标，存入临时记忆"

        session["state"] = "S_FINALIZE" if location != "rejected" else "S_REJECT"
        session["is_finalized"] = True
        session["finalized_at"] = _iso_now()
        session["updated_at"] = _iso_now()

        stored = location != "rejected"
        memory_id = 1 if stored else None
        metadata = {
            "time": _iso_now(),
            "importance": 0.75,
            "source": session["source_type"],
            "tags": ["mock", "radix", session["template_id"]],
        }

        return FinalizeDistillationResponse(
            stored=stored,
            location=location,
            memory_id=memory_id,
            metadata=metadata,
            reason=reason,
        )

    async def get_session_status(self, session_id: str) -> SessionStatusResponse:
        """查询会话状态。

        Mock behavior: 从内存态返回完整 session 字段。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"session_id 不存在（404）: {session_id}")

        return SessionStatusResponse(
            session_id=session["session_id"],
            source_type=session["source_type"],
            state=session["state"],
            template_id=session["template_id"],
            max_turns=session["max_turns"],
            ask_user_on_ambiguity=session["ask_user_on_ambiguity"],
            turns=list(session["turns"]),
            preread_summary=session["preread_summary"],
            ambiguity_questions=list(session["ambiguity_questions"]),
            extracted_content=session["extracted_content"],
            quality_score=session["quality_score"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            finalized_at=session["finalized_at"],
            is_finalized=session["is_finalized"],
            error_message=session["error_message"],
        )

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _transition_state(self, current_state: str, agent_action: str) -> str:
        """内部方法：状态机转移。

        Mock behavior: 查 _TRANSITIONS 表返回下一状态，非法转移 raise ValueError。
        """
        if current_state not in _STATES:
            raise ValueError(f"非法状态（422）: {current_state}")
        if agent_action not in _AGENT_ACTIONS:
            raise ValueError(f"非法 agent_action（422）: {agent_action}")

        transitions = _TRANSITIONS.get(current_state, {})
        next_state = transitions.get(agent_action)
        if next_state is None:
            raise ValueError(
                f"非法状态转移（409）: {current_state} + {agent_action}"
            )
        return next_state
