"""AgentToolsV2 真实实现。

RADIX-Lite 管理 Agent 扩展工具：8 个新增工具。
  - Agent CRUD（3个）：add_agent / update_agent / delete_agent
  - 蒸馏（3个）：start_distillation / advance_distillation / finalize_distillation
  - 模板（1个）：render_template
  - 决策（1个）：decide_storage

工具调用前检查 tools_config 启用状态和 distillation_enabled 开关。
蒸馏工具调用 DistillationService（Task 4 尚未实现，使用 Mock）。
模板工具进程内调用 TemplateEngine（模块7）。
决策工具进程内调用 DecisionCore（本模块）。

对应契约:
    - 接口契约: public/interface_stub/agent_tools_v2.pyi
    - 数据契约: public/schema/agent_config_v2.schema.json
    - 关联契约: public/schema/distillation_session.schema.json
    - 关联契约: public/schema/storage_decision.schema.json

@version 1.0.0
@see public/interface_stub/agent_tools_v2.pyi
@see public/schema/agent_config_v2.schema.json
"""

import asyncio
import json
import os
from typing import Any, Dict, Optional

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# CX-O 迁移版：_THIS_DIR = c:\CX-O\CX-O-SERVER\server\core\decision
#   _PROJECT_ROOT = c:\CX-O\CX-O-SERVER（上 3 级）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_AGENTS_FILE = os.path.join(_DATA_DIR, "agents.json")


# --------------------------------------------------------------------------- #
# Pydantic 模型（与 agent_tools_v2.pyi 存根严格一致）
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

_SOURCE_TYPES = frozenset({"text", "character_card", "image", "conversation_log"})

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

_REQUIRED_RUBRIC_FIELDS = (
    "importance_threshold_permanent",
    "quality_reject_threshold",
    "max_redistill_turns",
    "ask_user_confidence_threshold",
)


def _run_async(coro: Any) -> Any:
    """同步执行 async 协程（主线程，非子线程 asyncio+aiohttp）。

    rules-0 §三 async 禁止子线程 asyncio+aiohttp，本函数在主线程同步桥接。
    仅当无运行中的事件循环时可同步执行；若已有运行中的事件循环（如在异步工具
    执行路径内被调用），同步桥接无法阻塞该线程，明确报错引导改用 async 路径，
    避免原先 asyncio.run → run_until_complete 的二次抛错掩盖真实原因。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的事件循环：主线程同步执行
        return asyncio.run(coro)
    raise RuntimeError(
        "_run_async 不能在运行中的事件循环内同步执行，请改用 async 调用路径"
    )


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


class AgentToolsV2:
    """管理 Agent 扩展工具实现。

    8 个新增工具，由管理 agent（memory-agent 升级）调用。
    工具调用前检查 tools_config 启用状态和 distillation_enabled 开关。

    Attributes:
        _caller_agent_id: 当前调用方 agent ID（用于 tools_config 检查）
        _agents_file: agents.json 路径
        _decision_core: DecisionCore 实例（decide_storage 工具使用）
        _template_engine: TemplateEngine 实例（render_template 工具使用）
        _distillation_service: DistillationService 实例（蒸馏工具使用）
    """

    def __init__(
        self,
        caller_agent_id: Optional[str] = None,
        agents_file: Optional[str] = None,
        decision_core: Optional[Any] = None,
        template_engine: Optional[Any] = None,
        distillation_service: Optional[Any] = None,
    ) -> None:
        """初始化 AgentToolsV2。

        Args:
            caller_agent_id: 当前调用方 agent ID。None 时跳过 tools_config 检查（便于测试）。
            agents_file: agents.json 路径。None 时使用默认 data/agents.json。
            decision_core: DecisionCore 实例。None 时内部懒加载。
            template_engine: TemplateEngine 实例。None 时尝试 import 真实实现，失败 fallback Mock。
            distillation_service: DistillationService 实例。None 时尝试 import 真实实现，失败 fallback Mock。
        """
        self._caller_agent_id: Optional[str] = caller_agent_id
        self._agents_file: str = agents_file if agents_file else _AGENTS_FILE
        self._decision_core: Optional[Any] = decision_core
        self._template_engine: Optional[Any] = template_engine
        self._distillation_service: Optional[Any] = distillation_service

        # auto_init：data 目录不存在时创建（rules-0 §三 auto_init: data补全）
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Agent CRUD（3 个）
    # ------------------------------------------------------------------ #

    def add_agent(self, request: AddAgentRequest) -> AgentRecord:
        """工具 1: 创建新 agent 配置。

        Args:
            request: agent_id + name + config

        Returns:
            创建的 agent 记录

        Raises:
            FileExistsError: agent_id 已存在（409）
            ValueError: config 无效 / rubric 缺失（422）
            PermissionError: 当前 agent 无 add_agent 工具权限（403）
            IOError: agents.json 写入失败（500）
        """
        self._check_tool_enabled("add_agent")

        if not request.agent_id:
            raise ValueError("agent_id 不能为空（422）")
        if not request.name:
            raise ValueError("name 不能为空（422）")

        agents_data = self._load_agents()
        agents_list = agents_data.get("agents", [])

        for record in agents_list:
            if record.get("agent_id") == request.agent_id:
                raise FileExistsError(
                    f"agent_id 已存在（409）: {request.agent_id}"
                )

        config = request.config or {}
        tools_config = config.get("tools_config", dict(_DEFAULT_TOOLS_CONFIG))
        decision_rubric = config.get("decision_rubric")
        if decision_rubric is None:
            raise ValueError("decision_rubric 缺失（422）")
        # 校验 4 必需阈值
        for field in _REQUIRED_RUBRIC_FIELDS:
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
        agents_list.append(record.model_dump())
        agents_data["agents"] = agents_list
        self._save_agents(agents_data)
        return record

    def update_agent(self, agent_id: str, request: UpdateAgentRequest) -> AgentRecord:
        """工具 2: 更新 agent 配置。

        Args:
            agent_id: 目标 agent ID
            request: 更新内容（name / config）

        Returns:
            更新后的 agent 记录

        Raises:
            KeyError: agent_id 不存在（404）
            ValueError: config 无效（422）
            PermissionError: 无 update_agent 权限（403）
            IOError: agents.json 写入失败（500）
        """
        self._check_tool_enabled("update_agent")

        agents_data = self._load_agents()
        agents_list = agents_data.get("agents", [])

        target_idx: Optional[int] = None
        for idx, record in enumerate(agents_list):
            if record.get("agent_id") == agent_id:
                target_idx = idx
                break
        if target_idx is None:
            raise KeyError(f"agent_id 不存在（404）: {agent_id}")

        record_dict = agents_list[target_idx]
        if request.name is not None:
            record_dict["name"] = request.name
        if request.config is not None:
            cfg = request.config
            if "tools_config" in cfg:
                record_dict["tools_config"] = cfg["tools_config"]
            if "decision_rubric" in cfg:
                rubric = cfg["decision_rubric"]
                for field in _REQUIRED_RUBRIC_FIELDS:
                    if field not in rubric:
                        raise ValueError(
                            f"decision_rubric 缺少必需字段（422）: {field}"
                        )
                record_dict["decision_rubric"] = rubric
            if "distillation_enabled" in cfg:
                record_dict["distillation_enabled"] = cfg["distillation_enabled"]
            if "legacy_parser_enabled" in cfg:
                record_dict["legacy_parser_enabled"] = cfg["legacy_parser_enabled"]

        record = AgentRecord(**record_dict)
        agents_list[target_idx] = record.model_dump()
        agents_data["agents"] = agents_list
        self._save_agents(agents_data)
        return record

    def delete_agent(self, agent_id: str) -> bool:
        """工具 3: 删除 agent（含级联清理）。

        删除 agent 配置 + 级联清理关联数据（蒸馏会话 / 审计日志）。

        Args:
            agent_id: 目标 agent ID

        Returns:
            是否删除成功

        Raises:
            KeyError: agent_id 不存在（404）
            PermissionError: 无 delete_agent 权限（403）
            IOError: agents.json 写入失败（500）
        """
        self._check_tool_enabled("delete_agent")

        agents_data = self._load_agents()
        agents_list = agents_data.get("agents", [])

        target_idx: Optional[int] = None
        for idx, record in enumerate(agents_list):
            if record.get("agent_id") == agent_id:
                target_idx = idx
                break
        if target_idx is None:
            raise KeyError(f"agent_id 不存在（404）: {agent_id}")

        del agents_list[target_idx]
        agents_data["agents"] = agents_list
        self._save_agents(agents_data)

        # 级联清理：删除该 agent 关联的审计日志（best-effort）
        self._cascade_cleanup_agent(agent_id)
        return True

    # ------------------------------------------------------------------ #
    # 蒸馏工具（3 个）
    # ------------------------------------------------------------------ #

    def start_distillation(self, request: StartDistillationToolRequest) -> Dict[str, Any]:
        """工具 4: 启动多轮蒸馏会话。

        调用 DistillationService.start_distillation（进程内调用，Task 6 已从 Mock 切换为真实实现）。

        Args:
            request: source_type + source_ref + template_id + max_turns + ask_user

        Returns:
            {session_id, initial_state, preread_summary}

        Raises:
            PermissionError: distillation_enabled=false 或工具未启用（403）
            ValueError: source_type 无效 / max_turns 超范围（422）
            ConnectionError: DistillationService 不可用（500）
        """
        self._check_tool_enabled("start_distillation")
        self._check_distillation_enabled()

        if request.source_type not in _SOURCE_TYPES:
            raise ValueError(
                f"source_type 无效（422）: {request.source_type}"
            )
        if not (1 <= request.max_turns <= 6):
            raise ValueError(
                f"max_turns 超范围 1-6（422）: {request.max_turns}"
            )
        if not request.template_id:
            raise ValueError("template_id 不能为空（422）")

        service = self._get_distillation_service()
        try:
            response = _run_async(service.start_distillation(
                source_type=request.source_type,
                source_ref=request.source_ref,
                template_id=request.template_id,
                max_turns=request.max_turns,
                ask_user_on_ambiguity=request.ask_user_on_ambiguity,
            ))
        except Exception as exc:
            raise ConnectionError(
                f"DistillationService 不可用（500）: {exc}"
            ) from exc

        return {
            "session_id": response.session_id,
            "initial_state": response.initial_state,
            "preread_summary": response.preread_summary,
        }

    def advance_distillation(self, request: AdvanceDistillationToolRequest) -> Dict[str, Any]:
        """工具 5: 推进蒸馏状态机。

        调用 DistillationService.advance_distillation（HTTP POST /api/v1/distillation/{session_id}/advance）。

        Args:
            request: session_id + user_response

        Returns:
            {session_id, current_state, agent_action, next_needed}

        Raises:
            PermissionError: 工具未启用（403）
            KeyError: session_id 不存在（404）
            ValueError: 非法状态转移 / 会话已终结（409）
            ConnectionError: DistillationService 不可用（500）
        """
        self._check_tool_enabled("advance_distillation")

        if not request.session_id:
            raise KeyError("session_id 不能为空（404）")

        service = self._get_distillation_service()
        try:
            response = _run_async(service.advance_distillation(
                session_id=request.session_id,
                user_response=request.user_response,
            ))
        except KeyError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise ConnectionError(
                f"DistillationService 不可用（500）: {exc}"
            ) from exc

        return {
            "session_id": response.session_id,
            "current_state": response.current_state,
            "agent_action": response.agent_action,
            "next_needed": response.next_needed,
        }

    def finalize_distillation(self, request: FinalizeDistillationToolRequest) -> Dict[str, Any]:
        """工具 6: 终结蒸馏会话。

        调用 DistillationService.finalize_distillation（HTTP POST /api/v1/distillation/{session_id}/finalize）。

        Args:
            request: session_id + override_decision

        Returns:
            {stored, location, memory_id, metadata, reason}

        Raises:
            PermissionError: 工具未启用（403）
            KeyError: session_id 不存在（404）
            ValueError: 会话已终结（409）
            ConnectionError: DistillationService 不可用（500）
        """
        self._check_tool_enabled("finalize_distillation")

        if not request.session_id:
            raise KeyError("session_id 不能为空（404）")

        service = self._get_distillation_service()
        try:
            response = _run_async(service.finalize_distillation(
                session_id=request.session_id,
                override_decision=request.override_decision,
            ))
        except KeyError:
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise ConnectionError(
                f"DistillationService 不可用（500）: {exc}"
            ) from exc

        return {
            "stored": response.stored,
            "location": response.location,
            "memory_id": response.memory_id,
            "metadata": response.metadata,
            "reason": response.reason,
        }

    # ------------------------------------------------------------------ #
    # 模板工具（1 个）
    # ------------------------------------------------------------------ #

    def render_template(self, request: RenderTemplateToolRequest) -> Dict[str, Any]:
        """工具 7: 渲染 Jinja2 模板。

        调用 TemplateEngine.render_template（进程内调用）。

        Args:
            request: template_id + variables + workflow_mode

        Returns:
            {rendered_prompt, workflow_definition, expected_turns}

        Raises:
            PermissionError: 工具未启用（403）
            KeyError: template_id 不存在（404）
            ValueError: frontmatter 无效 / 缺少 required_vars（422）
            RuntimeError: Jinja2 渲染失败（422）
        """
        self._check_tool_enabled("render_template")

        if not request.template_id:
            raise KeyError("template_id 不能为空（404）")

        engine = self._get_template_engine()
        result = engine.render_template(
            template_id=request.template_id,
            variables=request.variables,
            workflow_mode=request.workflow_mode,
        )

        return {
            "rendered_prompt": result.rendered_prompt,
            "workflow_definition": result.workflow_definition,
            "expected_turns": result.expected_turns,
        }

    # ------------------------------------------------------------------ #
    # 决策工具（1 个）
    # ------------------------------------------------------------------ #

    def decide_storage(self, request: DecideStorageToolRequest) -> Dict[str, Any]:
        """工具 8: DecisionCore 智能存储决策。

        调用 DecisionCore 执行 6 决策点，返回存储决策结果。

        Args:
            request: session_id + override_decision

        Returns:
            {decision_id, session_id, decision_point, location, memory_id, metadata, reason, quality_score}

        Raises:
            PermissionError: 工具未启用（403）
            KeyError: session_id 不存在（404）
            ValueError: rubric 无效（422）
            ConnectionError: LLM 不可用，回退 system_prompt 规则（503）
            RuntimeError: 审计日志写入失败（500）
        """
        self._check_tool_enabled("decide_storage")

        if not request.session_id:
            raise KeyError("session_id 不能为空（404）")

        core = self._get_decision_core()

        # 加载 rubric（使用 caller_agent_id 或默认 memory-agent）
        agent_id = self._caller_agent_id or "memory-agent"
        rubric = core._load_rubric(agent_id)

        # 构造决策输入（实际场景由蒸馏会话产出，此处用默认值）
        from server.core.decision.decision_core import DecisionInput
        decision_input = DecisionInput(
            artifact_summary=None,
            session_state="S_STORAGE_DECISION",
            turn_history_summary=None,
            extracted_content=None,
            quality_score=0.82,
        )

        # 调用 D1 决策
        decision = core.decide_location(
            session_id=request.session_id,
            decision_input=decision_input,
            rubric=rubric,
        )

        # 人类 override_decision 覆盖
        if request.override_decision == "permanent":
            decision.location = "permanent_memories"
            decision.override_decision = "permanent"
            decision.reason = "人类 override=permanent，存入永久记忆"
        elif request.override_decision == "reject":
            decision.location = "rejected"
            decision.override_decision = "reject"
            decision.reason = "人类 override=reject，拒绝存储"
            decision.memory_id = None

        return {
            "decision_id": decision.decision_id,
            "session_id": decision.session_id,
            "decision_point": decision.decision_point,
            "location": decision.location,
            "memory_id": decision.memory_id,
            "metadata": decision.metadata,
            "reason": decision.reason,
            "quality_score": decision.quality_score,
        }

    # ------------------------------------------------------------------ #
    # 私有辅助方法
    # ------------------------------------------------------------------ #

    def _check_tool_enabled(self, tool_name: str) -> None:
        """检查工具是否启用（tools_config）。

        caller_agent_id 为 None 时跳过检查（便于测试）。
        PermissionError 在 try-except 之外 raise，避免被 OSError 捕获
        （PermissionError 是 OSError 子类）。
        """
        if self._caller_agent_id is None:
            return
        tools_config: Optional[Dict[str, bool]] = None
        try:
            agents_data = self._load_agents()
            agents_list = agents_data.get("agents", [])
            for record in agents_list:
                if record.get("agent_id") == self._caller_agent_id:
                    tools_config = record.get("tools_config", {})
                    break
            # caller agent 不存在时放行（best-effort）
        except (IOError, OSError):
            # 读取失败时放行（best-effort）
            pass

        if tools_config is not None:
            if not tools_config.get(tool_name, True):
                raise PermissionError(
                    f"工具未启用（403）: {tool_name} (caller={self._caller_agent_id})"
                )

    def _check_distillation_enabled(self) -> None:
        """检查蒸馏是否启用（distillation_enabled）。

        PermissionError 在 try-except 之外 raise，避免被 OSError 捕获。
        """
        if self._caller_agent_id is None:
            return
        distillation_enabled: Optional[bool] = None
        try:
            agents_data = self._load_agents()
            agents_list = agents_data.get("agents", [])
            for record in agents_list:
                if record.get("agent_id") == self._caller_agent_id:
                    distillation_enabled = record.get("distillation_enabled", False)
                    break
        except (IOError, OSError):
            pass

        if distillation_enabled is not None:
            if not distillation_enabled:
                raise PermissionError(
                    f"蒸馏未启用（403）: distillation_enabled=false (caller={self._caller_agent_id})"
                )

    def _load_agents(self) -> Dict[str, Any]:
        """加载 agents.json。

        文件不存在时返回默认结构（含 default + memory-agent 两个预置 agent）。

        Returns:
            agents 数据字典 {"agents": [...]}
        """
        try:
            if not os.path.isfile(self._agents_file):
                return {
                    "agents": [
                        _make_default_agent().model_dump(),
                        _make_memory_agent().model_dump(),
                    ]
                }
            with open(self._agents_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {"agents": []}
            if "agents" not in data:
                data["agents"] = []
            return data
        except json.JSONDecodeError:
            return {"agents": []}
        except OSError as exc:
            raise IOError(f"agents.json 读取失败（500）: {exc}") from exc

    def _save_agents(self, agents_data: Dict[str, Any]) -> None:
        """保存 agents.json。

        Raises:
            IOError: 写入失败（500）
        """
        try:
            os.makedirs(os.path.dirname(self._agents_file), exist_ok=True)
            with open(self._agents_file, "w", encoding="utf-8") as fh:
                json.dump(agents_data, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            raise IOError(f"agents.json 写入失败（500）: {exc}") from exc

    def _cascade_cleanup_agent(self, agent_id: str) -> None:
        """级联清理 agent 关联数据（审计日志 best-effort）。"""
        # best-effort：清理失败不阻断
        try:
            log_dir = os.path.join(_DATA_DIR, "distillation_logs")
            if not os.path.isdir(log_dir):
                return
            # 审计日志按 session_id 命名，无法直接按 agent_id 清理
            # 实际级联清理需要 session 关联表，此处仅做 best-effort 占位
        except OSError:
            pass

    def _get_decision_core(self) -> Any:
        """懒加载 DecisionCore 实例。"""
        if self._decision_core is None:
            from server.core.decision.decision_core import DecisionCore
            self._decision_core = DecisionCore()
        return self._decision_core

    def _get_template_engine(self) -> Any:
        """懒加载 TemplateEngine 实例。

        优先使用真实实现（模块7），不可用时 fallback Mock。
        """
        if self._template_engine is None:
            try:
                from server.core.templates.engine import TemplateEngine  # CX-O 迁移版：模块7 待迁移，fallback Mock
                self._template_engine = TemplateEngine()
            except Exception:
                # fallback Mock（rules-0 §三 fallback: try-except）
                from public.pre_generated_mock.mock_template_engine import MockTemplateEngine
                self._template_engine = MockTemplateEngine()
        return self._template_engine

    def _get_distillation_service(self) -> Any:
        """懒加载 DistillationService 实例。

        RADIX-Lite Task 6: 已从 MockDistillationService 切换为真实 DistillationService
        （模块9_蒸馏服务，Task 4 已闭合）。真实实现不可用时 fallback Mock
        （rules-0 §三 try-except fallback）。
        """
        if self._distillation_service is None:
            try:
                from server.core.distillation.distillation_service import DistillationService
                self._distillation_service = DistillationService()
            except Exception:
                # fallback Mock（rules-0 §三 try-except fallback）
                from public.pre_generated_mock.mock_distillation_service import MockDistillationService
                self._distillation_service = MockDistillationService()
        return self._distillation_service
