"""管理 Agent 扩展工具接口契约存根。

定义 RADIX-Lite 管理 Agent 的 8 个新增工具签名。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

工具清单（8个）：
  Agent CRUD（3个）：
    1. add_agent(agent_id, name, config) → agent_record
    2. update_agent(agent_id, updates) → agent_record
    3. delete_agent(agent_id) → bool
  蒸馏（3个）：
    4. start_distillation(source_type, source_ref, template_id, max_turns, ask_user) → session
    5. advance_distillation(session_id, user_response) → state
    6. finalize_distillation(session_id, override_decision) → storage_result
  模板（1个）：
    7. render_template(template_id, variables, workflow_mode) → rendered_prompt
  决策（1个）：
    8. decide_storage(session_id, override_decision) → storage_decision

@version 1.0.0
@see public/schema/agent_config_v2.schema.json
@see public/schema/distillation_session.schema.json
@see public/schema/storage_decision.schema.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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


class AgentToolsV2:
    """管理 Agent 扩展工具接口契约。

    8 个新增工具，由管理 agent（memory-agent 升级）调用。
    工具调用前检查 tools_config 启用状态和 distillation_enabled 开关。
    """

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
        ...

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
        ...

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
        ...

    def start_distillation(self, request: StartDistillationToolRequest) -> Dict[str, Any]:
        """工具 4: 启动多轮蒸馏会话。

        调用 DistillationService.start_distillation（HTTP POST /api/v1/distillation/start）。

        Args:
            request: source_type + source_ref + template_id + max_turns + ask_user

        Returns:
            {session_id, initial_state, preread_summary}

        Raises:
            PermissionError: distillation_enabled=false 或工具未启用（403）
            ValueError: source_type 无效 / max_turns 超范围（422）
            ConnectionError: DistillationService 不可用（500）
        """
        ...

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
        ...

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
        ...

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
            ValueError: frontmatter 无效 / 缺少 required_vars（422)
            RuntimeError: Jinja2 渲染失败（422）
        """
        ...

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
        ...
