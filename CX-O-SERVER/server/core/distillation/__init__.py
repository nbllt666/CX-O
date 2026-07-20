"""RADIX-Lite 蒸馏服务（DistillationService）—— CX-O 迁移版。

从 CXHMS modules/模块9_蒸馏服务 迁移至 CX-O-SERVER server/core/distillation。
CX-O 扩展：5 模态（text / character_card / image / video / audio）+ DecisionCore 真实接入。

CX-O-SERVER 主路由注册（端口 8000），承载 9 状态机多轮蒸馏工作流。
接入 MultimodalPipeline（B2）+ DecisionCore（B4）。

对应契约:
    - 接口契约: public/interface_stub/distillation_service.pyi
    - 数据契约: public/schema/distillation_session.schema.json
    - 数据契约: public/schema/distillation_log.schema.json
    - 配置契约: public/config_template/radix_config.json (distillation_service 段 + decision_core 段)

状态机（9 状态）:
    S_INIT -> S_PREREAD -> S_QUESTION -> S_REFLECT -> S_CROSSVALIDATE
           -> S_EXTRACT -> S_STORAGE_DECISION -> S_FINALIZE / S_REJECT

    回环: S_REFLECT -> S_QUESTION (D4_REDISTILL 决策驱动，受 max_redistill_turns 限制)
    主动追问: ask_user_on_ambiguity=True 且 S_QUESTION 时 agent_action=ask_user
    拒绝路径: S_REJECT (quality_score < rubric.quality_reject_threshold)

子系统协同（CX-O 真实实现）:
    - MultimodalPipeline (server.core.multimodal.MultimodalPipeline) — B2 已就位
    - DecisionCore       (server.core.decision.DecisionCore)         — B4 已就位，6 决策点真实接入

公开导出:
    - DistillationService               — 蒸馏服务主类
    - StartDistillationRequest          — 启动会话请求
    - StartDistillationResponse         — 启动会话响应
    - AdvanceDistillationRequest        — 推进状态机请求
    - AdvanceDistillationResponse       — 推进状态机响应
    - FinalizeDistillationRequest       — 终结会话请求
    - FinalizeDistillationResponse      — 终结会话响应
    - SessionStatusResponse             — 会话状态查询响应

@version 1.1.0  # CX-O 迁移版
"""

from server.core.distillation.distillation_service import (
    AdvanceDistillationRequest,
    AdvanceDistillationResponse,
    DistillationService,
    FinalizeDistillationRequest,
    FinalizeDistillationResponse,
    SessionStatusResponse,
    StartDistillationRequest,
    StartDistillationResponse,
)

__all__ = [
    "DistillationService",
    "StartDistillationRequest",
    "StartDistillationResponse",
    "AdvanceDistillationRequest",
    "AdvanceDistillationResponse",
    "FinalizeDistillationRequest",
    "FinalizeDistillationResponse",
    "SessionStatusResponse",
]

__version__ = "1.1.0"
