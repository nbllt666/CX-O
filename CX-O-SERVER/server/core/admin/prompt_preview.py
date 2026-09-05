"""提示词装配预览（CX-A readonly 能力：target=prompt action=preview 与
POST /api/admin/prompt/preview 共用核心，spec enhance-cxfc-admin-and-integrate-dream 三）。

零副作用核心：以哨兵 session + 显式 history 只读复用 prompt_builder.build_messages
装配逻辑，不写会话、不动 context store、不触发任何 LLM 调用。
"""
from typing import Any, Dict, List, Optional

from server.core.admin.control_plane import AdminControlError

# 预览专用哨兵会话 ID：保证预览消息流绝不与真实会话混淆（也便于测试断言不落盘）
PREVIEW_SESSION_ID = "__admin_preview__"


class _ReadOnlyContextStub:
    """只读 context_mgr 替身（零副作用防御层）。

    【已核实】prompt_builder.build_messages 对 context_mgr 的全部触达点集中在
    _resolve_history（get_recent_messages / get_message_count / get_messages，
    均为只读方法，无任何写路径）。本预览始终显式传 history（未传时给 []），
    _resolve_history 走 history[-limit:] 分支，context_mgr 理论上不会被触达；
    此处仍传入一个仅实现上述三个只读方法的最小替身作防御：若未来 build_messages
    增加隐式读路径，触达的是空替身而非真实存储；替身不提供任何写方法，写操作会
    AttributeError 快速失败而非静默落库。
    """

    def get_recent_messages(self, session_id: str, limit: int) -> list:
        return []

    def get_message_count(self, session_id: str) -> int:
        return 0

    def get_messages(self, session_id: str, limit: int = 0, offset: int = 0) -> list:
        return []


def _mirror_hidden_prompt_keys(agent_config: dict, include_hidden_prompts: bool, branch: str) -> List[str]:
    """镜像 prompt_builder 默认分支的隐藏提示词键选择逻辑（只读观测，不参与装配）。

    【同步注意】键清单与 prompt_builder.build_messages 默认分支（L334-L348 附近）
    保持一致；build_messages 装配逻辑冻结不可改（spec 约束），此镜像仅用于回显
    注入键，若上游键清单变更需同步此处。
    """
    if branch != "default" or not include_hidden_prompts:
        # ACP/实时语音分支不加载 hidden_prompt.yaml；include_hidden_prompts=False
        # （AnythingLLM 兼容路径语义）显式跳过
        return []
    from server import prompt_builder

    hidden = prompt_builder._get_hidden_prompts()
    model_type = (agent_config.get("model", "main") or "main").lower()
    keys: List[str] = []
    if "tools" in hidden:
        keys.append("tools")
    if model_type == "main":
        candidates = [
            "emotion_prompts", "avatar_prompts", "effect_prompts",
            "tool_usage_prompts", "graph_tools", "master_model_prompt",
        ]
    elif model_type == "summary":
        candidates = ["emotion_prompts", "effect_prompts", "graph_tools", "summary_model_prompt"]
    elif model_type in ("assistant", "memory"):
        candidates = [
            "emotion_prompts", "effect_prompts", "tool_usage_prompts",
            "graph_tools", "assistant_model_prompt",
        ]
    else:
        candidates = []
    keys.extend(k for k in candidates if k in hidden)
    return keys


def build_preview_messages(
    agent_id: str,
    user_message: str,
    history: Optional[List[dict]] = None,
    is_realtime_voice: bool = False,
    acp_context: Optional[dict] = None,
    include_hidden_prompts: bool = True,
) -> Dict[str, Any]:
    """构建提示词装配预览（零副作用，不触发任何 LLM 调用）。

    Args:
        agent_id: 目标 Agent ID（agents.json 中必须存在，否则 ADMIN_AGENT_NOT_FOUND）
        user_message: 测试用户消息（非空字符串）
        history: 显式历史消息（不传时按 [] 处理，绝不读真实会话历史）
        is_realtime_voice: True 时回显实时语音瘦身分支
        acp_context: 非 None 时回显 ACP 自动回复分支（需为 dict，建议含 from_agent_id）
        include_hidden_prompts: 是否注入隐藏提示词（与 build_messages 同名参数语义一致）

    Returns:
        {messages, branch, hidden_prompt_keys, history_limit, history_count,
         token_estimate, agent_id, session_id}

    Raises:
        AdminControlError: 参数非法 / Agent 不存在 / 装配失败（路由层映射 400）
    """
    # ---- 参数校验（轻量、同步、LLM 无关）----
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise AdminControlError("ADMIN_PREVIEW_INVALID: agent_id 必须为非空字符串")
    if not isinstance(user_message, str) or not user_message:
        raise AdminControlError("ADMIN_PREVIEW_INVALID: user_message 必须为非空字符串")
    if acp_context is not None and not isinstance(acp_context, dict):
        raise AdminControlError("ADMIN_PREVIEW_INVALID: acp_context 需为对象（dict）")

    try:
        # ---- Agent 配置解析（只读 agents.json，经 chat_helpers 统一入口）----
        from server import chat_helpers

        agent_config = chat_helpers.get_agent_config(agent_id)
        if not agent_config:
            raise AdminControlError(f"ADMIN_AGENT_NOT_FOUND: agent '{agent_id}' 不存在")

        # ---- history 归一：显式传入（不传给 []），保证 _resolve_history 不触达 context_mgr ----
        preview_history = [dict(h) for h in history if isinstance(h, dict)] if history else []

        # ---- 分支判定（与 build_messages 分支优先级一致：acp > realtime > default）----
        branch = "acp" if acp_context is not None else (
            "realtime" if is_realtime_voice else "default"
        )

        # ---- 历史上限（只读观测；读取失败回退 ContextLimitsConfig 内置默认 10）----
        history_limit = 10
        try:
            from server.config import get_settings

            history_limit = get_settings().config.limits.context.chat_context_limit
        except Exception:
            pass

        # ---- 隐藏提示词键回显（只读镜像）----
        hidden_prompt_keys = _mirror_hidden_prompt_keys(agent_config, include_hidden_prompts, branch)

        # ---- 复用 build_messages 装配（唯一装配真相源；只读复用不改装配逻辑）----
        from server import prompt_builder

        messages = prompt_builder.build_messages(
            agent_config=agent_config,
            context_mgr=_ReadOnlyContextStub(),
            session_id=PREVIEW_SESSION_ID,
            user_message=user_message,
            memory_context=None,  # 预览不检索记忆，避免触碰记忆库（零副作用）
            images=None,
            is_realtime_voice=is_realtime_voice,
            history=preview_history,
            include_hidden_prompts=include_hidden_prompts,
            acp_context=acp_context,
        )

        # ---- token 粗估：全部消息内容字符数 // 4 ----
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            total_chars += len(content) if isinstance(content, str) else len(str(content))

        return {
            "messages": messages,
            "branch": branch,
            "hidden_prompt_keys": hidden_prompt_keys,
            "history_limit": history_limit,
            "history_count": len(preview_history),
            "token_estimate": total_chars // 4,
            "agent_id": agent_id,
            "session_id": PREVIEW_SESSION_ID,
        }
    except AdminControlError:
        raise
    except Exception as e:
        # 全程 try-except 包裹 LLM 无关逻辑：装配失败降级为明确错误，不落半截状态
        raise AdminControlError(f"ADMIN_PREVIEW_FAILED: {e}")
