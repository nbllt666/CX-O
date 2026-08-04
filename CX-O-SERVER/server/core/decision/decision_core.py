"""DecisionCore 真实实现。

RADIX-Lite 决策核心：6 决策点自主决策（D1-D6），由 rubric 驱动。
rubric 不可被 LLM 自行修改，仅人类编辑 data/agents.json。
决策审计日志持久化到 data/distillation_logs/{session_id}.json。
LLM 置信度极低或不可用时回退 system_prompt 规则（rules-0 §三 fallback）。

对应契约:
    - 接口契约: public/interface_stub/decision_core.pyi
    - 数据契约: public/schema/storage_decision.schema.json
    - 审计日志契约: public/schema/distillation_log.schema.json
    - 配置契约: public/config_template/radix_config.json (decision_core 段 + vllm 段)

@version 1.0.0
@see public/interface_stub/decision_core.pyi
@see public/schema/storage_decision.schema.json
@see public/schema/distillation_log.schema.json
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# CX-O 迁移版：_THIS_DIR = c:\CX-O\CX-O-SERVER\server\core\decision
#   _PROJECT_ROOT = c:\CX-O\CX-O-SERVER（上 3 级）
#   _PUBLIC_ROOT  = c:\CX-O（上 4 级，public/ 契约区根）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_PUBLIC_ROOT = os.path.dirname(_PROJECT_ROOT)
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_AGENTS_FILE = os.path.join(_DATA_DIR, "agents.json")
_LOG_DIR = os.path.join(_DATA_DIR, "distillation_logs")
_CONFIG_FILE = os.path.join(
    _PUBLIC_ROOT, "public", "config_template", "radix_config.json"
)


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# Pydantic 模型（与 decision_core.pyi 存根严格一致）
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
# 枚举常量（与 storage_decision.schema.json / distillation_log.schema.json 一致）
# --------------------------------------------------------------------------- #

DECISION_POINTS = frozenset({
    "D1_LOCATION",
    "D2_METADATA",
    "D3_ASK_USER",
    "D4_REDISTILL",
    "D5_CROSS_VALIDATE",
    "D6_REJECT",
})

LOCATIONS = frozenset({"memories", "permanent_memories", "rejected"})

FINAL_ACTIONS = frozenset({
    "store", "ask_user", "redistill", "cross_validate", "reject", "skip",
})

# rubric 4 必需阈值字段（与 agent_config_v2.schema.json decision_rubric.required 一致）
_REQUIRED_RUBRIC_FIELDS = (
    "importance_threshold_permanent",
    "quality_reject_threshold",
    "max_redistill_turns",
    "ask_user_confidence_threshold",
)

# system_prompt 规则回退时使用的默认 importance（rules-0 §三 fallback）
_FALLBACK_IMPORTANCE = 0.75


def _default_rubric_dict() -> Dict[str, Any]:
    """返回默认 rubric 字典（与 radix_config.json decision_core 段默认值一致）。"""
    return {
        "importance_threshold_permanent": 0.7,
        "quality_reject_threshold": 0.3,
        "max_redistill_turns": 2,
        "ask_user_confidence_threshold": 0.4,
        "cross_validate_sources": [],
        "session_timeout_seconds": 1800,
        "rejected_content_retention_days": 30,
    }


def _default_decision_core_config() -> Dict[str, Any]:
    """返回 decision_core 配置段默认值（从 radix_config.json 提取）。"""
    return {
        "importance_threshold_permanent": 0.7,
        "quality_reject_threshold": 0.3,
        "max_redistill_turns": 2,
        "ask_user_confidence_threshold": 0.4,
        "cross_validate_sources": [],
        "rejected_content_retention_days": 30,
        "system_prompt_fallback_enabled": True,
    }


def _default_vllm_config() -> Dict[str, Any]:
    """返回 vllm 配置段默认值。"""
    return {
        "base_url": "http://127.0.0.1:8002",
        "vision_model": "",
        "vision_base_url": "http://127.0.0.1:8002",
        "embedding_base_url": "http://127.0.0.1:8101",
        "timeout_seconds": 300,
        "max_tokens": 2048,
        "temperature": 0.3,
    }


def _load_radix_config() -> Dict[str, Any]:
    """加载 radix_config.json，失败时使用全默认值（best-effort，不阻断）。

    Returns:
        配置字典，含 decision_core 段与 vllm 段。
    """
    defaults = {
        "decision_core": _default_decision_core_config(),
        "vllm": _default_vllm_config(),
    }
    try:
        if not os.path.isfile(_CONFIG_FILE):
            return defaults
        with open(_CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        # auto_fill：缺失字段补默认值（rules-3 §三）
        dc = cfg.get("decision_core", {})
        for k, v in defaults["decision_core"].items():
            dc.setdefault(k, v)
        vllm = cfg.get("vllm", {})
        for k, v in defaults["vllm"].items():
            vllm.setdefault(k, v)
        return {"decision_core": dc, "vllm": vllm}
    except (json.JSONDecodeError, OSError):
        return defaults


class DecisionCore:
    """DecisionCore 决策核心。

    6 决策点自主决策，由 rubric 驱动。
    rubric 不可被 LLM 自行修改，仅人类编辑 data/agents.json。
    LLM 不可用或置信度极低时回退 system_prompt 规则。

    Attributes:
        _config: radix_config 的 decision_core + vllm 段
        _agents_file: agents.json 路径
        _log_dir: 审计日志目录
        _llm_available: LLM 是否可用（测试可注入 False 触发回退）
        _memory_seq: memory_id 自增序列
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        agents_file: Optional[str] = None,
        log_dir: Optional[str] = None,
        llm_available: bool = True,
    ) -> None:
        """初始化 DecisionCore。

        Args:
            config: 配置字典（含 decision_core 段与 vllm 段）。None 时从 radix_config.json 加载。
            agents_file: agents.json 路径。None 时使用默认 data/agents.json。
            log_dir: 审计日志目录。None 时使用默认 data/distillation_logs/。
            llm_available: LLM 是否可用。测试可注入 False 触发 system_prompt 回退。
        """
        self._config: Dict[str, Any] = config if config is not None else _load_radix_config()
        self._agents_file: str = agents_file if agents_file else _AGENTS_FILE
        self._log_dir: str = log_dir if log_dir else _LOG_DIR
        self._llm_available: bool = llm_available
        self._memory_seq: int = 1

        # auto_init：日志目录不存在时自动创建（rules-0 §三 auto_init: data补全）
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except OSError:
            # 目录创建失败不阻断启动，写入时再报错
            pass

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

        根据 importance 和 rubric.importance_threshold_permanent 决定存入位置。
        - importance >= 阈值 → permanent_memories
        - importance < 阈值 → memories
        - quality_score < rubric.quality_reject_threshold → rejected（触发 D6）

        LLM 不可用时回退 system_prompt 规则（llm_confidence=None）。

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
        if not session_id:
            raise KeyError("session_id 不能为空（404）")

        quality_score = decision_input.quality_score
        if quality_score is None:
            quality_score = 0.82
        if not (0 <= quality_score <= 1):
            raise ValueError(f"quality_score 超出范围 0-1（422）: {quality_score}")

        # 先尝试 LLM 决策；不可用时回退 system_prompt 规则
        llm_reasoning: Optional[str] = None
        llm_confidence: Optional[float] = None
        importance = _FALLBACK_IMPORTANCE

        try:
            prompt = self._build_d1_prompt(decision_input, rubric)
            decision_str, confidence = self._llm_decide(prompt, decision_input)
            llm_reasoning = f"[LLM] D1 位置决策：{decision_str}（confidence={confidence}）"
            llm_confidence = confidence
            # LLM 推断 importance（回退值兜底）
            importance = _FALLBACK_IMPORTANCE
        except ConnectionError:
            # system_prompt 规则回退（rules-0 §三 fallback）
            llm_reasoning = None
            llm_confidence = None

        # rubric 驱动决策（system_prompt 规则）
        if quality_score < rubric.quality_reject_threshold:
            location = "rejected"
            reason = (
                f"quality_score={quality_score} < "
                f"quality_reject_threshold={rubric.quality_reject_threshold}，"
                "触发 D6 拒绝存储"
            )
            memory_id: Optional[int] = None
            final_action = "reject"
        elif importance >= rubric.importance_threshold_permanent:
            location = "permanent_memories"
            reason = (
                f"importance={importance} >= "
                f"importance_threshold_permanent={rubric.importance_threshold_permanent}，"
                "存入永久记忆"
            )
            memory_id = self._alloc_memory_id()
            final_action = "store"
        else:
            location = "memories"
            reason = (
                f"importance={importance} < "
                f"importance_threshold_permanent={rubric.importance_threshold_permanent}，"
                "存入临时记忆"
            )
            memory_id = self._alloc_memory_id()
            final_action = "store"

        metadata = self._default_metadata(session_id, decision_input)
        decision = self._build_storage_decision(
            session_id=session_id,
            decision_point="D1_LOCATION",
            location=location,
            memory_id=memory_id,
            metadata=metadata,
            reason=reason,
            quality_score=quality_score,
            rubric=rubric,
            llm_confidence=llm_confidence,
        )

        # 写审计日志（best-effort）
        self._write_audit_log(
            session_id=session_id,
            decision_point="D1_LOCATION",
            decision_input=decision_input,
            rubric=rubric,
            llm_reasoning=llm_reasoning,
            llm_confidence=llm_confidence,
            final_decision=FinalDecision(
                action=final_action,
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

        决定记忆的元数据（时间 / 重要性 / 来源 / 标签）。
        LLM 不可用时回退 system_prompt 规则。

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
        if not session_id:
            raise KeyError("session_id 不能为空（404）")

        # 尝试 LLM 决策元数据；不可用时回退规则
        try:
            prompt = self._build_d2_prompt(decision_input)
            decision_str, confidence = self._llm_decide(prompt, decision_input)
            source = decision_input.artifact_summary or f"[LLM] {decision_str}"
            tags = ["radix", "d2_metadata", f"llm_{decision_str}"]
        except ConnectionError:
            # system_prompt 规则回退
            source = decision_input.artifact_summary or "text"
            tags = ["radix", "d2_metadata", "fallback"]

        return {
            "time": _iso_now(),
            "importance": _FALLBACK_IMPORTANCE,
            "source": source,
            "tags": tags,
        }

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
        if not session_id:
            raise KeyError("session_id 不能为空（404）")
        if not (0 <= quality_score <= 1):
            raise ValueError(
                f"quality_score 超出范围 0-1（422）: {quality_score}"
            )

        reason = (
            f"quality_score={quality_score} < "
            f"quality_reject_threshold={rubric.quality_reject_threshold}，"
            "拒绝存储，内容保留 30 天"
        )

        retention_days = self._config.get("decision_core", {}).get(
            "rejected_content_retention_days", 30
        )
        decision = self._build_storage_decision(
            session_id=session_id,
            decision_point="D6_REJECT",
            location="rejected",
            memory_id=None,
            metadata={"retention_days": retention_days},
            reason=reason,
            quality_score=quality_score,
            rubric=rubric,
            llm_confidence=None,
        )

        self._write_audit_log(
            session_id=session_id,
            decision_point="D6_REJECT",
            decision_input=DecisionInput(
                session_state="S_STORAGE_DECISION",
                quality_score=quality_score,
            ),
            rubric=rubric,
            llm_reasoning=None,
            llm_confidence=None,
            final_decision=FinalDecision(
                action="reject",
                location="rejected",
                details={"quality_score": quality_score},
            ),
        )
        return decision

    # ------------------------------------------------------------------ #
    # 内部方法（签名严格匹配 .pyi）
    # ------------------------------------------------------------------ #

    def _load_rubric(self, agent_id: str) -> RubricSnapshot:
        """内部方法：加载 rubric。

        从 data/agents.json 读取指定 agent 的 decision_rubric 字段。
        agents.json 不存在或 agent_id 缺失时回退默认 rubric（best-effort）。

        Args:
            agent_id: Agent ID

        Returns:
            RubricSnapshot

        Raises:
            KeyError: agent_id 不存在或 decision_rubric 字段缺失（422）
            IOError: agents.json 读取失败（500）
        """
        if not agent_id:
            raise KeyError("agent_id 不能为空（422）")

        try:
            if not os.path.isfile(self._agents_file):
                # agents.json 不存在时回退默认 rubric（auto_init 兜底）
                return self._rubric_from_dict(_default_rubric_dict())
            with open(self._agents_file, "r", encoding="utf-8") as fh:
                agents_data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise IOError(
                f"agents.json JSON 解析失败（500）: {exc}"
            ) from exc
        except OSError as exc:
            raise IOError(f"agents.json 读取失败（500）: {exc}") from exc

        # agents.json 结构：{"agents": [{"agent_id": ..., "decision_rubric": ...}, ...]}
        # 或 {"agent_id": {...}, ...} 两种兼容
        agents_list = agents_data.get("agents", []) if isinstance(agents_data, dict) else []
        for record in agents_list:
            if isinstance(record, dict) and record.get("agent_id") == agent_id:
                rubric = record.get("decision_rubric")
                if rubric is None:
                    raise KeyError(
                        f"agent_id={agent_id} 缺少 decision_rubric 字段（422）"
                    )
                return self._rubric_from_dict(rubric)

        # 兼容 dict 形式
        if isinstance(agents_data, dict) and agent_id in agents_data:
            record = agents_data[agent_id]
            if isinstance(record, dict):
                rubric = record.get("decision_rubric")
                if rubric is None:
                    raise KeyError(
                        f"agent_id={agent_id} 缺少 decision_rubric 字段（422）"
                    )
                return self._rubric_from_dict(rubric)

        raise KeyError(
            f"agent_id 不存在或 decision_rubric 字段缺失（422）: {agent_id}"
        )

    def _llm_decide(
        self,
        prompt: str,
        decision_input: DecisionInput,
    ) -> Tuple[str, float]:
        """内部方法：LLM 决策。

        通过 vLLM HTTP 接口（OpenAI 兼容）调用 LLM 进行决策。
        LLM 不可用时 raise ConnectionError，触发 system_prompt 规则回退。

        Args:
            prompt: 决策提示词
            decision_input: 决策输入

        Returns:
            (decision_str, confidence_float) 元组

        Raises:
            ConnectionError: LLM 端点不可用，触发 system_prompt 规则回退（503）
        """
        if not self._llm_available:
            raise ConnectionError(
                "LLM 端点不可用（503），触发 system_prompt 规则回退"
            )

        vllm_cfg = self._config.get("vllm", _default_vllm_config())
        base_url = vllm_cfg.get("base_url", "http://127.0.0.1:8002")
        timeout = vllm_cfg.get("timeout_seconds", 300)
        max_tokens = vllm_cfg.get("max_tokens", 2048)
        temperature = vllm_cfg.get("temperature", 0.3)

        url = f"{base_url}/v1/chat/completions"
        payload = {
            "model": "radix-decision-core",
            "messages": [
                {"role": "system", "content": "你是 RADIX-Lite DecisionCore 决策助手。"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            import requests  # 同步 HTTP（rules-0 §三 async 禁止子线程 asyncio+aiohttp）
        except ImportError as exc:
            raise ConnectionError(
                f"requests 库不可用（503），触发 system_prompt 规则回退: {exc}"
            ) from exc

        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code != 200:
                raise ConnectionError(
                    f"LLM 端点返回 {resp.status_code}（503），触发 system_prompt 规则回退"
                )
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # 解析 LLM 输出：期望 "decision:store confidence:0.85" 格式
            decision_str, confidence = self._parse_llm_output(content)
            return decision_str, confidence
        except (requests.RequestException, OSError) as exc:
            raise ConnectionError(
                f"LLM 端点连接失败（503），触发 system_prompt 规则回退: {exc}"
            ) from exc
        except (ValueError, KeyError, IndexError) as exc:
            raise ConnectionError(
                f"LLM 响应解析失败（503），触发 system_prompt 规则回退: {exc}"
            ) from exc

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

        日志结构严格符合 distillation_log.schema.json（additionalProperties: false）。

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
        try:
            if decision_point not in DECISION_POINTS:
                raise ValueError(f"无效决策点（422）: {decision_point}")

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

            # 读取已有日志（追加模式）
            log_path = os.path.join(self._log_dir, f"{session_id}.json")
            logs: List[Dict[str, Any]] = []
            if os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as fh:
                        logs = json.load(fh)
                    if not isinstance(logs, list):
                        logs = []
                except (json.JSONDecodeError, OSError):
                    logs = []

            logs.append(log_entry)

            # auto_init：目录不存在时创建
            os.makedirs(self._log_dir, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as fh:
                json.dump(logs, fh, ensure_ascii=False, indent=2)
        except Exception:
            # best-effort：写入失败不阻断主流程（distillation_log.schema.json exceptions.IOError_500）
            pass

    # ------------------------------------------------------------------ #
    # 私有辅助方法（非契约方法）
    # ------------------------------------------------------------------ #

    def _rubric_from_dict(self, rubric_dict: Dict[str, Any]) -> RubricSnapshot:
        """从字典构造 RubricSnapshot，校验 4 必需字段。"""
        for field in _REQUIRED_RUBRIC_FIELDS:
            if field not in rubric_dict:
                raise KeyError(
                    f"decision_rubric 缺少必需字段（422）: {field}"
                )
        return RubricSnapshot(
            importance_threshold_permanent=float(rubric_dict["importance_threshold_permanent"]),
            quality_reject_threshold=float(rubric_dict["quality_reject_threshold"]),
            max_redistill_turns=int(rubric_dict["max_redistill_turns"]),
            ask_user_confidence_threshold=float(rubric_dict["ask_user_confidence_threshold"]),
            cross_validate_sources=list(rubric_dict.get("cross_validate_sources", [])),
        )

    def _alloc_memory_id(self) -> int:
        """分配 memory_id（自增序列）。"""
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
            "importance": _FALLBACK_IMPORTANCE,
            "source": decision_input.artifact_summary or "text",
            "tags": ["radix", "d1_location"],
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

    def _build_d1_prompt(
        self,
        decision_input: DecisionInput,
        rubric: RubricSnapshot,
    ) -> str:
        """构造 D1 决策提示词。"""
        return (
            "请决策存入位置。\n"
            f"会话状态: {decision_input.session_state}\n"
            f"质量评分: {decision_input.quality_score}\n"
            f"重要性阈值: {rubric.importance_threshold_permanent}\n"
            f"拒绝阈值: {rubric.quality_reject_threshold}\n"
            "请输出格式: decision:<store|reject> confidence:<0-1>"
        )

    def _build_d2_prompt(self, decision_input: DecisionInput) -> str:
        """构造 D2 元数据决策提示词。"""
        return (
            "请决策记忆元数据（时间/重要性/来源/标签）。\n"
            f"会话状态: {decision_input.session_state}\n"
            f"内容摘要: {decision_input.artifact_summary or 'N/A'}\n"
            "请输出格式: decision:<metadata_type> confidence:<0-1>"
        )

    def _parse_llm_output(self, content: str) -> Tuple[str, float]:
        """解析 LLM 输出，提取 decision 与 confidence。

        期望格式: "decision:store confidence:0.85"
        解析失败时回退 (store, 0.5)。
        """
        decision_str = "store"
        confidence = 0.5
        try:
            lower = content.lower()
            if "decision:" in lower:
                part = lower.split("decision:", 1)[1].split()[0]
                decision_str = part.strip(",.;")
            if "confidence:" in lower:
                part = lower.split("confidence:", 1)[1].split()[0]
                confidence = float(part.strip(",.;"))
                confidence = max(0.0, min(1.0, confidence))
        except (ValueError, IndexError):
            pass
        return decision_str, confidence

    # ------------------------------------------------------------------ #
    # 测试辅助（非契约方法，仅供单元测试使用）
    # ------------------------------------------------------------------ #

    def _read_audit_logs(self, session_id: str) -> List[Dict[str, Any]]:
        """读取指定会话的审计日志（仅供测试使用）。

        Args:
            session_id: 会话 ID

        Returns:
            日志条目列表
        """
        log_path = os.path.join(self._log_dir, f"{session_id}.json")
        if not os.path.isfile(log_path):
            return []
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                logs = json.load(fh)
            return logs if isinstance(logs, list) else []
        except (json.JSONDecodeError, OSError):
            return []
