"""AgentToolsV2 预生成 Mock 实现（CX-O 迁移版）。

对应接口契约: public/interface_stub/agent_tools_v2.pyi
对应数据契约: public/schema/agent_config_v2.schema.json
对应配置契约: public/config_template/radix_config.json
关联数据契约: public/schema/distillation_session.schema.json
关联数据契约: public/schema/storage_decision.schema.json

Mock 策略:
- 返回符合 schema 的固定样例数据
- 内存态维护 agents 表（预置 default + memory-agent 两个样例）
- 8 工具方法返回固定样例 Dict（结构对齐 DistillationService/TemplateEngine/DecisionCore 响应）
- 异常路径通过 raise 模拟（KeyError=404 / ValueError=422 / PermissionError=403）
- 真实实现就位后，切换导入路径即可替换

@version 1.1.0
@see public/interface_stub/agent_tools_v2.pyi
@see public/schema/agent_config_v2.schema.json

CX-O 迁移版，基于 CXHMS v1.2.0 Mock 适配。
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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


class AddAgentRequest(BaseModel):
    """add_agent 请求。"""
    agent_id: str
    name: str
    config: Dict[str, Any]  # tools_config / decision_rubric / distillation_enabled


class UpdateAgentRequest(BaseModel):
    """update_agent 请求。"""
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class AgentRecord(BaseModel):
    """agent 记录。字段与 agent_config_v2.schema.json 一致。"""
    agent_id: str
    name: str
    tools_config: Dict[str, bool]
    decision_rubric: Dict[str, Any]
    distillation_enabled: bool
    legacy_parser_enabled: bool = True


class StartDistillationToolRequest(BaseModel):
    """start_distillation 工具请求。"""
    source_type: str  # enum: text / character_card / image / conversation_log
    source_ref: Optional[str] = None
    template_id: str
    max_turns: int = 4
    ask_user_on_ambiguity: bool = True


class AdvanceDistillationToolRequest(BaseModel):
    """advance_distillation 工具请求。"""
    session_id: str
    user_response: Optional[str] = None


class FinalizeDistillationToolRequest(BaseModel):
    """finalize_distillation 工具请求。"""
    session_id: str
    override_decision: Optional[str] = None


class RenderTemplateToolRequest(BaseModel):
    """render_template 工具请求。"""
    template_id: str
    variables: Dict[str, Any]
    workflow_mode: Optional[str] = None


class DecideStorageToolRequest(BaseModel):
    """decide_storage 工具请求。"""
    session_id: str
    override_decision: Optional[str] = None


# --------------------------------------------------------------------------- #
# 枚举与默认值（与 agent_config_v2.schema.json 一致）
# --------------------------------------------------------------------------- #

_SOURCE_TYPES = {"text", "character_card", "image", "video", "audio", "conversation_log"}

# 8 工具默认配置（全部启用）
_DEFAULT_TOOLS_CONFIG: Dict[str, bool] = {
    "add_agent": True,
    "update_agent": True,
    "delete_agent": True,
    "start_distillation": True,
    "advance_distillation": True,
    "finalize_distillation": True,
    "render_template": True,
    "decide_storage": True,
}

# 4 必需 rubric 阈值默认值（与 radix_config.json decision_core 一致）
_DEFAULT_DECISION_RUBRIC: Dict[str, Any] = {
    "importance_threshold_permanent": 0.7,
    "quality_reject_threshold": 0.3,
    "max_redistill_turns": 2,
    "ask_user_confidence_threshold": 0.4,
    "cross_validate_sources": [],
    "session_timeout_seconds": 1800,
    "rejected_content_retention_days": 30,
}


def _make_default_agent() -> AgentRecord:
    """构造 default agent 记录。"""
    return AgentRecord(
        agent_id="default",
        name="默认 Agent",
        tools_config=dict(_DEFAULT_TOOLS_CONFIG),
        decision_rubric=dict(_DEFAULT_DECISION_RUBRIC),
        distillation_enabled=False,
        legacy_parser_enabled=True,
    )


def _make_memory_agent() -> AgentRecord:
    """构造 memory-agent 记录（管理 agent，蒸馏已启用）。"""
    return AgentRecord(
        agent_id="memory-agent",
        name="记忆管理 Agent",
        tools_config=dict(_DEFAULT_TOOLS_CONFIG),
        decision_rubric=dict(_DEFAULT_DECISION_RUBRIC),
        distillation_enabled=True,
        legacy_parser_enabled=False,
    )


class MockAgentToolsV2:
    """管理 Agent 扩展工具的 Mock 实现。

    8 工具方法返回固定样例 Dict，结构对齐各子服务响应。
    AgentRecord 返回值通过 agent_config_v2.schema.json 校验。
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentRecord] = {}
        self._seed()

    def _seed(self) -> None:
        """预置 default + memory-agent 两个样例 agent。"""
        for record in (_make_default_agent(), _make_memory_agent()):
            self._agents[record.agent_id] = record

    # ------------------------------------------------------------------ #
    # Agent CRUD（3 个）
    # ------------------------------------------------------------------ #

    def add_agent(self, request: AddAgentRequest) -> AgentRecord:
        """工具 1: 创建新 agent 配置。

        Mock behavior: 校验 agent_id 唯一性与 rubric 完整性，写入内存态表。
        """
        if request.agent_id in self._agents:
            raise FileExistsError(
                f"agent_id 已存在（409）: {request.agent_id}"
            )
        if not request.agent_id:
            raise ValueError("agent_id 不能为空（422）")
        if not request.name:
            raise ValueError("name 不能为空（422）")

        config = request.config or {}
        tools_config = config.get("tools_config", dict(_DEFAULT_TOOLS_CONFIG))
        decision_rubric = config.get("decision_rubric")
        if decision_rubric is None:
            raise ValueError(
                "decision_rubric 缺失（422）"
            )
        # 校验 4 必需阈值
        for field in (
            "importance_threshold_permanent",
            "quality_reject_threshold",
            "max_redistill_turns",
            "ask_user_confidence_threshold",
        ):
            if field not in decision_rubric:
                raise ValueError(
                    f"decision_rubric 缺少必需字段（422）: {field}"
                )

        record = AgentRecord(
            agent_id=request.agent_id,
            name=request.name,
            tools_config=tools_config,
            decision_rubric=decision_rubric,
            distillation_enabled=config.get("distillation_enabled", False),
            legacy_parser_enabled=config.get("legacy_parser_enabled", True),
        )
        self._agents[request.agent_id] = record
        return record

    def update_agent(self, agent_id: str, request: UpdateAgentRequest) -> AgentRecord:
        """工具 2: 更新 agent 配置。

        Mock behavior: 更新 name/config，agent_id 不存在 raise KeyError。
        """
        record = self._agents.get(agent_id)
        if record is None:
            raise KeyError(f"agent_id 不存在（404）: {agent_id}")

        if request.name is not None:
            record.name = request.name
        if request.config is not None:
            cfg = request.config
            if "tools_config" in cfg:
                record.tools_config = cfg["tools_config"]
            if "decision_rubric" in cfg:
                rubric = cfg["decision_rubric"]
                for field in (
                    "importance_threshold_permanent",
                    "quality_reject_threshold",
                    "max_redistill_turns",
                    "ask_user_confidence_threshold",
                ):
                    if field not in rubric:
                        raise ValueError(
                            f"decision_rubric 缺少必需字段（422）: {field}"
                        )
                record.decision_rubric = rubric
            if "distillation_enabled" in cfg:
                record.distillation_enabled = cfg["distillation_enabled"]
            if "legacy_parser_enabled" in cfg:
                record.legacy_parser_enabled = cfg["legacy_parser_enabled"]

        return record

    def delete_agent(self, agent_id: str) -> bool:
        """工具 3: 删除 agent（含级联清理）。

        Mock behavior: 从内存态表删除，agent_id 不存在 raise KeyError。
        返回 bool（与 .pyi 签名一致）。
        """
        if agent_id not in self._agents:
            raise KeyError(f"agent_id 不存在（404）: {agent_id}")
        del self._agents[agent_id]
        return True

    # ------------------------------------------------------------------ #
    # 蒸馏工具（3 个）
    # ------------------------------------------------------------------ #

    def start_distillation(self, request: StartDistillationToolRequest) -> Dict[str, Any]:
        """工具 4: 启动多轮蒸馏会话。

        Mock behavior: 返回 {session_id, initial_state, preread_summary} 样例。
        source_type 无效 raise ValueError，max_turns 超范围 raise ValueError。
        """
        if request.source_type not in _SOURCE_TYPES:
            raise ValueError(
                f"source_type 无效（422）: {request.source_type}"
            )
        if not (1 <= request.max_turns <= 6):
            raise ValueError(
                f"max_turns 超范围 1-6（422）: {request.max_turns}"
            )

        return {
            "session_id": _new_uuid(),
            "initial_state": "S_PREREAD",
            "preread_summary": (
                "[Mock] 预读摘要：检测到 "
                f"{request.source_type} 数据源，准备进入多轮蒸馏。"
            ),
        }

    def advance_distillation(self, request: AdvanceDistillationToolRequest) -> Dict[str, Any]:
        """工具 5: 推进蒸馏状态机。

        Mock behavior: 返回 {session_id, current_state, agent_action, next_needed} 样例。
        """
        if not request.session_id:
            raise KeyError("session_id 不能为空（404）")

        return {
            "session_id": request.session_id,
            "current_state": "S_QUESTION",
            "agent_action": "ask_user",
            "next_needed": True,
        }

    def finalize_distillation(self, request: FinalizeDistillationToolRequest) -> Dict[str, Any]:
        """工具 6: 终结蒸馏会话。

        Mock behavior: 返回 {stored, location, memory_id, metadata, reason} 样例。
        override_decision='permanent' → permanent_memories；'reject' → rejected。
        """
        if not request.session_id:
            raise KeyError("session_id 不能为空（404）")

        if request.override_decision == "permanent":
            location = "permanent_memories"
            stored = True
            memory_id = 1
            reason = "[Mock] 人类 override=permanent，存入永久记忆"
        elif request.override_decision == "reject":
            location = "rejected"
            stored = False
            memory_id = None
            reason = "[Mock] 人类 override=reject，拒绝存储"
        else:
            location = "memories"
            stored = True
            memory_id = 1
            reason = "[Mock] quality_score=0.82 达标，存入临时记忆"

        return {
            "stored": stored,
            "location": location,
            "memory_id": memory_id,
            "metadata": {
                "time": _iso_now(),
                "importance": 0.75,
                "source": "[Mock] text",
                "tags": ["mock", "radix"],
            },
            "reason": reason,
        }

    # ------------------------------------------------------------------ #
    # 模板工具（1 个）
    # ------------------------------------------------------------------ #

    def render_template(self, request: RenderTemplateToolRequest) -> Dict[str, Any]:
        """工具 7: 渲染 Jinja2 模板。

        Mock behavior: 返回 {rendered_prompt, workflow_definition, expected_turns} 样例。
        template_id 为空 raise KeyError。
        """
        if not request.template_id:
            raise KeyError("template_id 不能为空（404）")

        workflow_mode = request.workflow_mode or "multi_turn"
        rendered = (
            f"[Mock] 渲染模板 {request.template_id}，"
            f"变量 keys={list(request.variables.keys())}"
        )
        return {
            "rendered_prompt": rendered,
            "workflow_definition": {
                "workflow_mode": workflow_mode,
                "expected_turns": 4,
            },
            "expected_turns": 4,
        }

    # ------------------------------------------------------------------ #
    # 决策工具（1 个）
    # ------------------------------------------------------------------ #

    def decide_storage(self, request: DecideStorageToolRequest) -> Dict[str, Any]:
        """工具 8: DecisionCore 智能存储决策。

        Mock behavior: 返回 StorageDecision 关键字段样例 Dict。
        override_decision 非 None 时覆盖 location。
        """
        if not request.session_id:
            raise KeyError("session_id 不能为空（404）")

        if request.override_decision == "permanent":
            location = "permanent_memories"
            reason = "[Mock] 人类 override=permanent，存入永久记忆"
        elif request.override_decision == "reject":
            location = "rejected"
            reason = "[Mock] 人类 override=reject，拒绝存储"
        else:
            location = "memories"
            reason = "[Mock] quality_score=0.82 达标，存入临时记忆"

        return {
            "decision_id": _new_uuid(),
            "session_id": request.session_id,
            "decision_point": "D1_LOCATION",
            "location": location,
            "memory_id": 1 if location != "rejected" else None,
            "metadata": {
                "time": _iso_now(),
                "importance": 0.75,
                "source": "[Mock] text",
                "tags": ["mock", "radix"],
            },
            "reason": reason,
            "quality_score": 0.82,
        }
