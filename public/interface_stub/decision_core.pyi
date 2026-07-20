"""DecisionCore 接口契约存根。

定义 RADIX-Lite DecisionCore 的 6 决策点方法签名 + rubric 加载签名。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

6 决策点：
  - D1_LOCATION: 存入位置决策（memories / permanent_memories / rejected）
  - D2_METADATA: 元数据决策（时间 / 重要性 / 来源 / 标签）
  - D3_ASK_USER: 追问决策（quality_score 边界触发）
  - D4_REDISTILL: 再次蒸馏决策（max_redistill_turns 限制）
  - D5_CROSS_VALIDATE: 跨源验证决策（多源对比）
  - D6_REJECT: 拒绝存储决策（quality_score < quality_reject_threshold）

rubric 驱动决策，读取 data/agents.json 的 decision_rubric 字段。
决策审计日志写入 data/distillation_logs/{session_id}.json。
LLM 置信度极低时回退 system_prompt 规则。

@version 1.0.0
@see public/schema/storage_decision.schema.json
@see public/schema/distillation_log.schema.json
@see public/config_template/radix_config.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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


class DecisionCore:
    """DecisionCore 接口契约。

    6 决策点自主决策，由 rubric 驱动。
    rubric 不可被 LLM 自行修改，仅人类编辑 data/agents.json。
    """

    def decide_location(
        self,
        session_id: str,
        decision_input: DecisionInput,
        rubric: RubricSnapshot,
    ) -> StorageDecision:
        """D1: 存入位置决策。

        根据 importance 和 rubric.importance_threshold_permanent 决定存入位置。
        - importance >= 阈值 → permanent_memories
        - importance < 阈值 → memories
        - quality_score < rubric.quality_reject_threshold → rejected（触发 D6）

        Args:
            session_id: 会话 ID
            decision_input: 决策输入
            rubric: rubric 快照

        Returns:
            StorageDecision: 存储决策

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 决策输入无效（422）
            ConnectionError: LLM 不可用，回退 system_prompt 规则（503）
            RuntimeError: 审计日志写入失败（500）
        """
        ...

    def decide_metadata(
        self,
        session_id: str,
        decision_input: DecisionInput,
    ) -> Dict[str, Any]:
        """D2: 元数据决策。

        决定记忆的元数据（时间 / 重要性 / 来源 / 标签）。

        Args:
            session_id: 会话 ID
            decision_input: 决策输入

        Returns:
            元数据字典（time / importance / source / tags）

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 决策输入无效（422）
            ConnectionError: LLM 不可用，回退 system_prompt 规则（503）
        """
        ...

    def decide_ask_user(
        self,
        session_id: str,
        llm_confidence: float,
        rubric: RubricSnapshot,
    ) -> bool:
        """D3: 追问决策。

        根据 LLM 置信度和 rubric.ask_user_confidence_threshold 决定是否追问人类。

        Args:
            session_id: 会话 ID
            llm_confidence: LLM 决策置信度
            rubric: rubric 快照

        Returns:
            是否需要追问（True=拉起 AskUserQuestion）

        Raises:
            KeyError: session_id 不存在（404）
        """
        ...

    def decide_redistill(
        self,
        session_id: str,
        current_turn: int,
        rubric: RubricSnapshot,
    ) -> bool:
        """D4: 再次蒸馏决策。

        根据 current_turn 和 rubric.max_redistill_turns 决定是否再次蒸馏。

        Args:
            session_id: 会话 ID
            current_turn: 当前轮次
            rubric: rubric 快照

        Returns:
            是否需要再次蒸馏（True=回环至 S_QUESTION）

        Raises:
            KeyError: session_id 不存在（404）
        """
        ...

    def decide_cross_validate(
        self,
        session_id: str,
        decision_input: DecisionInput,
        rubric: RubricSnapshot,
    ) -> bool:
        """D5: 跨源验证决策。

        根据 rubric.cross_validate_sources 和内容特征决定是否跨源验证。

        Args:
            session_id: 会话 ID
            decision_input: 决策输入
            rubric: rubric 快照

        Returns:
            是否需要跨源验证

        Raises:
            KeyError: session_id 不存在（404）
        """
        ...

    def decide_reject(
        self,
        session_id: str,
        quality_score: float,
        rubric: RubricSnapshot,
    ) -> StorageDecision:
        """D6: 拒绝存储决策。

        根据 quality_score 和 rubric.quality_reject_threshold 决定是否拒绝存储。
        拒绝的内容存入 rejected_content 保留 30 天。

        Args:
            session_id: 会话 ID
            quality_score: 质量评分
            rubric: rubric 快照

        Returns:
            StorageDecision: location=rejected

        Raises:
            KeyError: session_id 不存在（404）
            RuntimeError: 审计日志写入失败（500）
        """
        ...

    def _load_rubric(self, agent_id: str) -> RubricSnapshot:
        """内部方法：加载 rubric。

        从 data/agents.json 读取指定 agent 的 decision_rubric 字段。

        Args:
            agent_id: Agent ID

        Returns:
            RubricSnapshot

        Raises:
            KeyError: agent_id 不存在或 decision_rubric 字段缺失（422）
            IOError: agents.json 读取失败（500）
        """
        ...

    def _llm_decide(
        self,
        prompt: str,
        decision_input: DecisionInput,
    ) -> tuple:
        """内部方法：LLM 决策。

        Args:
            prompt: 决策提示词
            decision_input: 决策输入

        Returns:
            (decision_str, confidence_float) 元组

        Raises:
            ConnectionError: LLM 端点不可用，触发 system_prompt 规则回退（503）
        """
        ...

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

        日志持久化到 data/distillation_logs/{session_id}.json。
        best-effort：写入失败不阻断主流程，但记录错误。

        Args:
            session_id: 会话 ID
            decision_point: 决策点（D1-D6）
            decision_input: 决策输入
            rubric: rubric 快照
            llm_reasoning: LLM 推理摘要（回退时为 None）
            llm_confidence: LLM 置信度（回退时为 None）
            final_decision: 最终决策

        Raises:
            IOError: 日志写入失败（best-effort，不阻断）
        """
        ...
