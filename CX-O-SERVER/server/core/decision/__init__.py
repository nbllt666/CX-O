"""RADIX-Lite 管理 Agent 决策核心（CX-O 迁移版）。

从 CXHMS modules/模块10_管理Agent扩展 迁移至 CX-O-SERVER server/core/decision。
    - DecisionCore：6 决策点自主决策（D1-D6），rubric 驱动
    - AgentToolsV2：8 个新增工具（agent CRUD + 蒸馏 + 模板 + 决策）
    - 决策审计日志持久化到 data/distillation_logs/{session_id}.json

对应契约:
    - 接口契约: public/interface_stub/decision_core.pyi
    - 接口契约: public/interface_stub/agent_tools_v2.pyi
    - 数据契约: public/schema/storage_decision.schema.json
    - 数据契约: public/schema/agent_config_v2.schema.json
    - 数据契约: public/schema/distillation_log.schema.json
    - 数据契约: public/schema/rejected_content.schema.json
    - 配置契约: public/config_template/radix_config.json (decision_core 段 + vllm 段)

公开导出:
    - DecisionCore             — 决策核心主类
    - AgentToolsV2             — 8 工具实现
    - RubricSnapshot           — rubric 快照模型
    - DecisionInput            — 决策输入模型
    - FinalDecision            — 最终决策结果模型
    - StorageDecision          — 存储决策模型
    - AddAgentRequest          — add_agent 请求模型
    - UpdateAgentRequest       — update_agent 请求模型
    - AgentRecord              — agent 记录模型
    - StartDistillationToolRequest   — start_distillation 请求模型
    - AdvanceDistillationToolRequest — advance_distillation 请求模型
    - FinalizeDistillationToolRequest — finalize_distillation 请求模型
    - RenderTemplateToolRequest      — render_template 请求模型
    - DecideStorageToolRequest       — decide_storage 请求模型

@version 1.1.0
@see public/interface_stub/decision_core.pyi
@see public/interface_stub/agent_tools_v2.pyi
"""

from server.core.decision.agent_tools import (
    AddAgentRequest,
    AdvanceDistillationToolRequest,
    AgentRecord,
    AgentToolsV2,
    DecideStorageToolRequest,
    FinalizeDistillationToolRequest,
    RenderTemplateToolRequest,
    StartDistillationToolRequest,
    UpdateAgentRequest,
)
from server.core.decision.decision_core import (
    DecisionCore,
    DecisionInput,
    FinalDecision,
    RubricSnapshot,
    StorageDecision,
)

__all__ = [
    "DecisionCore",
    "AgentToolsV2",
    "RubricSnapshot",
    "DecisionInput",
    "FinalDecision",
    "StorageDecision",
    "AddAgentRequest",
    "UpdateAgentRequest",
    "AgentRecord",
    "StartDistillationToolRequest",
    "AdvanceDistillationToolRequest",
    "FinalizeDistillationToolRequest",
    "RenderTemplateToolRequest",
    "DecideStorageToolRequest",
]

__version__ = "1.1.0"
