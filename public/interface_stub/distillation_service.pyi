"""DistillationService 接口契约存根。

定义 RADIX-Lite 蒸馏服务的 4 个 API 端点签名 + 内部状态机方法签名。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

端点清单（4个）：
  1. POST /api/v1/distillation/start                      — 启动蒸馏会话
  2. POST /api/v1/distillation/{session_id}/advance       — 推进蒸馏状态机
  3. POST /api/v1/distillation/{session_id}/finalize      — 终结蒸馏会话
  4. GET  /api/v1/distillation/{session_id}               — 查询会话状态

状态机：S_INIT → S_PREREAD → S_QUESTION → S_REFLECT → S_CROSSVALIDATE
       → S_EXTRACT → S_STORAGE_DECISION → S_FINALIZE / S_REJECT

后端对应（已核对 server/api/routers/distillation.py，真实路径 /api/v1/distillation/*，
另含批量切分 5 端点 start-batch/group/{group_id}/finalize-agent/parse-character-card/start-from-character-card）；
种子阶段契约——本存根为代表性签名，s0201 后续补全。

@version 1.0.0
@see public/schema/distillation_session.schema.json
@see public/config_template/radix_config.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class StartDistillationRequest(BaseModel):
    """启动蒸馏会话请求。"""
    source_type: str  # enum: text / character_card / image / conversation_log
    source_ref: Optional[str] = None
    template_id: str
    max_turns: int = 4  # 1-6
    ask_user_on_ambiguity: bool = True


class StartDistillationResponse(BaseModel):
    """启动蒸馏会话响应。"""
    session_id: str
    initial_state: str  # S_PREREAD
    preread_summary: Optional[str]


class AdvanceDistillationRequest(BaseModel):
    """推进蒸馏状态机请求。"""
    user_response: Optional[str] = None  # ask_user 时的用户响应


class AdvanceDistillationResponse(BaseModel):
    """推进蒸馏状态机响应。"""
    session_id: str
    current_state: str
    agent_action: str  # enum: ask_user / proceed / reflect / cross_validate / extract / decide / finalize / reject
    next_needed: bool  # 是否需要用户进一步输入


class FinalizeDistillationRequest(BaseModel):
    """终结蒸馏会话请求。"""
    override_decision: Optional[str] = None  # 人类覆盖决策


class FinalizeDistillationResponse(BaseModel):
    """终结蒸馏会话响应。"""
    stored: bool
    location: str  # enum: memories / permanent_memories / rejected
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


class DistillationService:
    """DistillationService 接口契约。

    CX-O-SERVER 路由（端口 8000），承载 9 状态机多轮蒸馏工作流。
    作为 CX-O-SERVER 主路由注册（server/api/routers/distillation.py），通过 HTTP REST API 暴露。
    """

    async def start_distillation(
        self,
        source_type: str,
        source_ref: Optional[str],
        template_id: str,
        max_turns: int,
        ask_user_on_ambiguity: bool,
    ) -> StartDistillationResponse:
        """启动蒸馏会话。

        异步触发 MultimodalPipeline 预处理，session 进入 S_PREREAD 状态。

        Args:
            source_type: 数据源类型（text/character_card/image/conversation_log）
            source_ref: 数据源引用（文件路径/URL/文本 hash）
            template_id: 关联模板 ID
            max_turns: 最大轮次（1-6）
            ask_user_on_ambiguity: 是否主动追问

        Returns:
            StartDistillationResponse: session_id + initial_state + preread_summary

        Raises:
            ValueError: source_type 不在枚举中 / max_turns 超出范围（422）
            RuntimeError: MultimodalPipeline 预处理失败（422）
            ConnectionError: MultimodalPipeline 不可用（500）
        """
        ...

    async def advance_distillation(
        self,
        session_id: str,
        user_response: Optional[str],
    ) -> AdvanceDistillationResponse:
        """推进蒸馏状态机一步。

        支持回环（S_REFLECT → S_QUESTION）和主动追问（ask_user_on_ambiguity=True）。

        Args:
            session_id: 会话 ID
            user_response: 用户对 ask_user 的响应（如无则为 None）

        Returns:
            AdvanceDistillationResponse: session_id + current_state + agent_action + next_needed

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 非法状态转移 / 会话已终结 / 超过最大轮次（409）
            RuntimeError: LLM 调用失败（500）
        """
        ...

    async def finalize_distillation(
        self,
        session_id: str,
        override_decision: Optional[str],
    ) -> FinalizeDistillationResponse:
        """终结蒸馏会话，执行存储决策。

        调用 DecisionCore 执行 6 决策点，返回存储结果。

        Args:
            session_id: 会话 ID
            override_decision: 人类覆盖决策（非 None 时覆盖 agent 决策）

        Returns:
            FinalizeDistillationResponse: stored + location + memory_id + metadata + reason

        Raises:
            KeyError: session_id 不存在（404）
            ValueError: 会话已终结（409）
            RuntimeError: DecisionCore 决策失败 / 审计日志写入失败（500）
        """
        ...

    async def get_session_status(self, session_id: str) -> SessionStatusResponse:
        """查询会话状态。

        Args:
            session_id: 会话 ID

        Returns:
            SessionStatusResponse: 完整会话状态

        Raises:
            KeyError: session_id 不存在（404）
        """
        ...

    def _transition_state(self, current_state: str, agent_action: str) -> str:
        """内部方法：状态机转移。

        Args:
            current_state: 当前状态
            agent_action: agent 动作

        Returns:
            下一个状态

        Raises:
            ValueError: 非法状态转移
        """
        ...
