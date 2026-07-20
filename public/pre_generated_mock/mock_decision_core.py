"""DecisionCore 预生成 Mock 实现（CX-O 迁移版）。

对应接口契约: public/interface_stub/decision_core.pyi
对应数据契约: public/schema/storage_decision.schema.json
对应配置契约: public/config_template/radix_config.json
对应审计日志契约: public/schema/distillation_log.schema.json

Mock 策略:
- 返回符合 schema 的固定样例数据
- rubric 驱动 6 决策点（D1-D6），阈值匹配时触发对应分支
- 异常路径通过 raise 模拟（KeyError=404 / ValueError=422 / ConnectionError=503）
- 审计日志内存态暂存（best-effort，写入失败不阻断）
- 真实实现就位后，切换导入路径即可替换

@version 1.1.0
@see public/interface_stub/decision_core.pyi
@see public/schema/storage_decision.schema.json
@see public/schema/distillation_log.schema.json

CX-O 迁移版，基于 CXHMS v1.2.0 Mock 适配。
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Pydantic 模型（与 .pyi 存根保持一致，Mock 自包含）
# --------------------------------------------------------------------------- #


class RubricSnapshot(BaseModel):
    """rubric 快照。字段与 storage_decision.schema.json rubric_snapshot 一致。"""
    importance_threshold_permanent: float
    quality_reject_threshold: float
    max_redistill_turns: int
    ask_user_confidence_threshold: float
    cross_validate_sources: List[str] = []


class DecisionInput(BaseModel):
    """决策输入。"""
    artifact_summary: Optional[str] = None
    session_state: str
    turn_history_summary: Optional[str] = None
    extracted_content: Optional[str] = None
    quality_score: Optional[float] = None


class FinalDecision(BaseModel):
    """最终决策结果。字段与 distillation_log.schema.json final_decision 一致。"""
    action: str  # enum: store / ask_user / redistill / cross_validate / reject / skip
    location: Optional[str] = None  # enum: memories / permanent_memories / rejected / None
    details: Dict[str, Any]


class StorageDecision(BaseModel):
    """存储决策。字段与 storage_decision.schema.json 一致。"""
    decision_id: str
    session_id: str
    decision_point: str  # enum: D1_LOCATION / D2_METADATA / D3_ASK_USER / D4_REDISTILL / D5_CROSS_VALIDATE / D6_REJECT
    location: str  # enum: memories / permanent_memories / rejected
    memory_id: Optional[int]
    metadata: Dict[str, Any]
    reason: str
    quality_score: float
    rubric_snapshot: RubricSnapshot
    llm_confidence: Optional[float]
    override_decision: Optional[str]
    created_at: str


# --------------------------------------------------------------------------- #
# 枚举常量（与 storage_decision.schema.json 一致）
# --------------------------------------------------------------------------- #

_DECISION_POINTS = {
    "D1_LOCATION", "D2_METADATA", "D3_ASK_USER",
    "D4_REDISTILL", "D5_CROSS_VALIDATE", "D6_REJECT",
}

_LOCATIONS = {"memories", "permanent_memories", "rejected"}

_FINAL_ACTIONS = {
    "store", "ask_user", "redistill", "cross_validate", "reject", "skip",
}


# 默认 rubric（与 radix_config.json decision_core 默认值一致）
def _default_rubric() -> RubricSnapshot:
    return RubricSnapshot(
        importance_threshold_permanent=0.7,
        quality_reject_threshold=0.3,
        max_redistill_turns=2,
        ask_user_confidence_threshold=0.4,
        cross_validate_sources=[],
    )


# 预置 agent rubric 表（模拟 data/agents.json）
_AGENT_RUBRICS: Dict[str, RubricSnapshot] = {
    "default": _default_rubric(),
    "memory-agent": RubricSnapshot(
        importance_threshold_permanent=0.7,
        quality_reject_threshold=0.3,
        max_redistill_turns=2,
        ask_user_confidence_threshold=0.4,
        cross_validate_sources=["text", "conversation_log"],
    ),
}


class MockDecisionCore:
    """DecisionCore 的 Mock 实现。

    rubric 驱动 6 决策点，内存态暂存审计日志。
    返回值通过 storage_decision.schema.json 校验。
    """

    def __init__(self) -> None:
        # 审计日志内存态：session_id -> List[log_dict]
        self._audit_logs: Dict[str, List[Dict[str, Any]]] = {}
        # memory_id 自增序列（Mock）
        self._memory_seq: int = 1
        # LLM 是否可用（默认可用，可被测试设为 False 触发回退）
        self._llm_available: bool = True

    # ------------------------------------------------------------------ #
    # 6 决策点
    # ------------------------------------------------------------------ #

    def decide_location(
        self,
        session_id: str,
        decision_input: DecisionInput,
        rubric: RubricSnapshot,
    ) -> StorageDecision:
        """D1: 存入位置决策。

        Mock behavior: 根据 quality_score 与 importance 阈值决定 location。
        - quality_score < rubric.quality_reject_threshold → rejected
        - importance >= rubric.importance_threshold_permanent → permanent_memories
        - 否则 → memories
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")

        quality_score = decision_input.quality_score
        if quality_score is None:
            quality_score = 0.82
        if not (0 <= quality_score <= 1):
            raise ValueError(f"quality_score 超出范围 0-1（422）: {quality_score}")

        # 默认 importance 从 extracted_content 推断（Mock 固定 0.75）
        importance = 0.75

        if quality_score < rubric.quality_reject_threshold:
            location = "rejected"
            reason = (
                f"[Mock] quality_score={quality_score} < "
                f"quality_reject_threshold={rubric.quality_reject_threshold}，"
                "触发 D6 拒绝"
            )
            memory_id = None
        elif importance >= rubric.importance_threshold_permanent:
            location = "permanent_memories"
            reason = (
                f"[Mock] importance={importance} >= "
                f"importance_threshold_permanent={rubric.importance_threshold_permanent}，"
                "存入永久记忆"
            )
            memory_id = self._alloc_memory_id()
        else:
            location = "memories"
            reason = (
                f"[Mock] importance={importance} < "
                f"importance_threshold_permanent={rubric.importance_threshold_permanent}，"
                "存入临时记忆"
            )
            memory_id = self._alloc_memory_id()

        decision = self._build_storage_decision(
            session_id=session_id,
            decision_point="D1_LOCATION",
            location=location,
            memory_id=memory_id,
            metadata=self._default_metadata(session_id, decision_input),
            reason=reason,
            quality_score=quality_score,
            rubric=rubric,
            llm_confidence=0.85,
        )

        # 写审计日志（best-effort）
        self._write_audit_log(
            session_id=session_id,
            decision_point="D1_LOCATION",
            decision_input=decision_input,
            rubric=rubric,
            llm_reasoning="[Mock] D1 位置决策推理摘要",
            llm_confidence=0.85,
            final_decision=FinalDecision(
                action="store",
                location=location,
                details={"importance": importance, "memory_id": memory_id},
            ),
        )
        return decision

    def decide_metadata(
        self,
        session_id: str,
        decision_input: DecisionInput,
    ) -> Dict[str, Any]:
        """D2: 元数据决策。

        Mock behavior: 返回固定样例元数据（time / importance / source / tags）。
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")

        return {
            "time": _iso_now(),
            "importance": 0.75,
            "source": decision_input.artifact_summary or "[Mock] text",
            "tags": ["mock", "radix", "d2_metadata"],
        }

    def decide_ask_user(
        self,
        session_id: str,
        llm_confidence: float,
        rubric: RubricSnapshot,
    ) -> bool:
        """D3: 追问决策。

        Mock behavior: llm_confidence < rubric.ask_user_confidence_threshold 时返回 True。
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")
        if not (0 <= llm_confidence <= 1):
            raise ValueError(
                f"llm_confidence 超出范围 0-1（422）: {llm_confidence}"
            )

        return llm_confidence < rubric.ask_user_confidence_threshold

    def decide_redistill(
        self,
        session_id: str,
        current_turn: int,
        rubric: RubricSnapshot,
    ) -> bool:
        """D4: 再次蒸馏决策。

        Mock behavior: current_turn < rubric.max_redistill_turns 时返回 True。
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")
        if current_turn < 0:
            raise ValueError(
                f"current_turn 不能为负（422）: {current_turn}"
            )

        return current_turn < rubric.max_redistill_turns

    def decide_cross_validate(
        self,
        session_id: str,
        decision_input: DecisionInput,
        rubric: RubricSnapshot,
    ) -> bool:
        """D5: 跨源验证决策。

        Mock behavior: rubric.cross_validate_sources 非空且 extracted_content 非空时返回 True。
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")

        return (
            len(rubric.cross_validate_sources) > 0
            and bool(decision_input.extracted_content)
        )

    def decide_reject(
        self,
        session_id: str,
        quality_score: float,
        rubric: RubricSnapshot,
    ) -> StorageDecision:
        """D6: 拒绝存储决策。

        Mock behavior: 返回 location=rejected 的 StorageDecision。
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")
        if not (0 <= quality_score <= 1):
            raise ValueError(
                f"quality_score 超出范围 0-1（422）: {quality_score}"
            )

        reason = (
            f"[Mock] quality_score={quality_score} < "
            f"quality_reject_threshold={rubric.quality_reject_threshold}，"
            "拒绝存储，内容保留 30 天"
        )

        decision = self._build_storage_decision(
            session_id=session_id,
            decision_point="D6_REJECT",
            location="rejected",
            memory_id=None,
            metadata={"retention_days": 30},
            reason=reason,
            quality_score=quality_score,
            rubric=rubric,
            llm_confidence=0.9,
        )

        self._write_audit_log(
            session_id=session_id,
            decision_point="D6_REJECT",
            decision_input=DecisionInput(
                session_state="S_STORAGE_DECISION",
                quality_score=quality_score,
            ),
            rubric=rubric,
            llm_reasoning="[Mock] D6 拒绝决策推理摘要",
            llm_confidence=0.9,
            final_decision=FinalDecision(
                action="reject",
                location="rejected",
                details={"quality_score": quality_score},
            ),
        )
        return decision

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _load_rubric(self, agent_id: str) -> RubricSnapshot:
        """内部方法：加载 rubric。

        Mock behavior: 从 _AGENT_RUBRICS 表读取，agent_id 不存在 raise KeyError。
        """
        if not agent_id:
            raise KeyError("agent_id 不能为空（422）")
        rubric = _AGENT_RUBRICS.get(agent_id)
        if rubric is None:
            raise KeyError(
                f"agent_id 不存在或 decision_rubric 字段缺失（422）: {agent_id}"
            )
        return rubric

    def _llm_decide(
        self,
        prompt: str,
        decision_input: DecisionInput,
    ) -> Tuple[str, float]:
        """内部方法：LLM 决策。

        Mock behavior: _llm_available=False 时 raise ConnectionError 触发 system_prompt 回退。
        否则返回固定 (decision_str, confidence) 元组。
        """
        if not self._llm_available:
            raise ConnectionError(
                "LLM 端点不可用（503），触发 system_prompt 规则回退"
            )
        # Mock 决策：根据 quality_score 给出 store/reject
        quality_score = decision_input.quality_score
        if quality_score is not None and quality_score < 0.3:
            return "reject", 0.9
        return "store", 0.85

    def _write_audit_log(
        self,
        session_id: str,
        decision_point: str,
        decision_input: DecisionInput,
        rubric: RubricSnapshot,
        llm_reasoning: Optional[str],
        llm_confidence: Optional[float],
        final_decision: FinalDecision,
    ) -> None:
        """内部方法：写入决策审计日志。

        Mock behavior: 内存态追加日志条目（best-effort，异常不阻断）。
        日志结构符合 distillation_log.schema.json。
        """
        try:
            if decision_point not in _DECISION_POINTS:
                raise ValueError(
                    f"无效决策点（422）: {decision_point}"
                )

            log_entry = {
                "log_id": _new_uuid(),
                "session_id": session_id,
                "decision_point": decision_point,
                "input": decision_input.model_dump(),
                "rubric_snapshot": rubric.model_dump(),
                "llm_reasoning": llm_reasoning,
                "llm_confidence": llm_confidence,
                "final_decision": final_decision.model_dump(),
                "timestamp": _iso_now(),
            }
            self._audit_logs.setdefault(session_id, []).append(log_entry)
        except Exception:
            # best-effort：写入失败不阻断主流程
            pass

    # ------------------------------------------------------------------ #
    # 私有辅助
    # ------------------------------------------------------------------ #

    def _alloc_memory_id(self) -> int:
        """分配 memory_id。"""
        mid = self._memory_seq
        self._memory_seq += 1
        return mid

    def _default_metadata(
        self,
        session_id: str,
        decision_input: DecisionInput,
    ) -> Dict[str, Any]:
        """构造默认元数据。"""
        return {
            "time": _iso_now(),
            "importance": 0.75,
            "source": decision_input.artifact_summary or "[Mock] text",
            "tags": ["mock", "radix", "d1_location"],
            "session_id": session_id,
        }

    def _build_storage_decision(
        self,
        session_id: str,
        decision_point: str,
        location: str,
        memory_id: Optional[int],
        metadata: Dict[str, Any],
        reason: str,
        quality_score: float,
        rubric: RubricSnapshot,
        llm_confidence: Optional[float],
        override_decision: Optional[str] = None,
    ) -> StorageDecision:
        """构造 StorageDecision 实例。"""
        return StorageDecision(
            decision_id=_new_uuid(),
            session_id=session_id,
            decision_point=decision_point,
            location=location,
            memory_id=memory_id,
            metadata=metadata,
            reason=reason,
            quality_score=quality_score,
            rubric_snapshot=rubric,
            llm_confidence=llm_confidence,
            override_decision=override_decision,
            created_at=_iso_now(),
        )
