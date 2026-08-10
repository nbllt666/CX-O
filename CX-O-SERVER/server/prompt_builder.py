"""
server/prompt_builder.py
========================
统一提示词组装模块。

将原先分散在三处的提示词组装逻辑收敛为单一入口：
  - server.handlers.chat._build_messages
  - server.api.routers.chat.build_messages
  - server.api.routers.anythingllm._build_messages_for_chat

消除 hidden_prompt.yaml 的重复加载与行为漂移，并统一实时语音瘦身优化到所有入口。

对外唯一入口：build_messages(...)
支持：
  - 核心人设 system_prompt 注入（实时与非实时模式均保留）
  - 实时语音瘦身分支（is_realtime_voice=True）：
    仅注入对应 voice_prompt + 最近 2 轮对话，锁死 Tokens < 600 / 80ms TTFT
  - 非实时默认分支：
    按 model_type 注入隐藏提示词 + memory_context + CXFC 技能注入 + 历史 + 多模态
  - history 透传：供调用方已自行加载历史时使用（否则从 context_mgr 读取）
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml

from server.config import get_settings

logger = logging.getLogger(__name__)

# 实时语音模式历史消息条数（2 user + 2 assistant = 4 条）
REALTIME_VOICE_HISTORY_LIMIT = 4

# 项目根目录（c:\CX-O）：本文件位于 CX-O-SERVER/server/ 下，向上三级即项目根。
# 隐藏提示词 hidden_prompt.yaml 位于项目根 config/ 下（CXHMS→CX-O 迁移后与配置分离）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=8)
def _load_hidden_prompts(path: str) -> dict:
    """带缓存加载 hidden_prompt.yaml。配置路径稳定时避免每次调用重复文件 I/O（性能优化）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        logger.warning(f"加载隐藏提示词失败: {path}")
        return {}


def _get_hidden_prompts() -> dict:
    """定位并加载 hidden_prompt.yaml（带缓存）。

    优先项目根 config/（实际存放位置），回退到 settings._config_path 所在目录（旧布局）。
    """
    candidates = [_PROJECT_ROOT / "config" / "hidden_prompt.yaml"]
    try:
        settings = get_settings()
        if settings._config_path:
            candidates.append(Path(settings._config_path).parent / "hidden_prompt.yaml")
    except Exception:
        pass
    for path in candidates:
        if path.exists():
            return _load_hidden_prompts(str(path))
    # 首选路径不存在时仍尝试加载，以记录告警并返回空 dict（不中断主流程）
    return _load_hidden_prompts(str(candidates[0]))


def _append_history(messages: List[dict], history: List[dict]) -> None:
    """追加 user/assistant 历史消息。"""
    for msg in history:
        if msg.get("role") in ["user", "assistant"]:
            messages.append({"role": msg["role"], "content": msg.get("content", "")})


def _append_multimodal_user(messages: List[dict], images: List[str], user_message: str) -> None:
    """追加多模态用户消息（文本 + 图片）。"""
    content = [{"type": "text", "text": user_message}]
    for img_base64 in images:
        if img_base64.startswith("data:"):
            img_data = img_base64.split(",", 1)[1] if "," in img_base64 else img_base64
            mime_type = img_base64.split(";")[0].split(":")[1] if ":" in img_base64 else "image/jpeg"
        else:
            img_data = img_base64
            mime_type = "image/jpeg"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_data}"}})
    messages.append({"role": "user", "content": content})


def _resolve_history(context_mgr, session_id: str, history: Optional[List[dict]], limit: int) -> List[dict]:
    """返回最近 limit 条历史消息。

    注意：context_mgr.get_messages 按 created_at ASC（旧→新）返回，单纯的 limit
    只会截取最旧的消息，导致实时/非实时路径都取到陈旧上下文而非最近上下文。
    此处通过 count+offset 取最近 limit 条，修正该潜在 bug。
    """
    if history is not None:
        return history[-limit:]
    if context_mgr is None:
        return []
    try:
        total = context_mgr.get_message_count(session_id)
        offset = max(0, total - limit)
        return context_mgr.get_messages(session_id, limit=limit, offset=offset)
    except Exception:
        # 退化：context_mgr 不支持 count/offset 时，取首窗口并截尾
        return context_mgr.get_messages(session_id, limit=limit)[-limit:]


def _inject_cxfc_skills(messages: List[dict], user_message: str) -> None:
    """按用户消息关键词注入匹配的 CXFC 技能提示词（失败不影响主流程）。"""
    try:
        from server.dependencies import get_cxfc_manager

        cxfc_mgr = get_cxfc_manager()
        if not cxfc_mgr:
            return
        skill_registry = cxfc_mgr.get_skill_registry()
        matched_skills = skill_registry.find_by_keywords(user_message)
        if not matched_skills:
            return
        skill_prompts = []
        for skill in matched_skills:
            if skill.auto_inject:
                rendered = skill_registry.render_template(
                    skill.prompt_template,
                    {"user_message": user_message},
                )
                skill_prompts.append(rendered)
        if skill_prompts:
            messages.append({"role": "system", "content": "\n\n".join(skill_prompts)})
    except Exception as e:
        logger.warning(f"Skills injection failed: {e}")


def build_messages(
    agent_config: dict,
    context_mgr,
    session_id: str,
    user_message: str,
    memory_context: Optional[str] = None,
    images: Optional[List[str]] = None,
    is_realtime_voice: bool = False,
    tts_engine: str = "f5-tts",
    history: Optional[List[dict]] = None,
    include_hidden_prompts: bool = True,
) -> List[dict]:
    """构建发送给 LLM 的消息列表。

    Args:
        agent_config: Agent 配置字典，包含 system_prompt / model / use_memory / vision_enabled 等。
        context_mgr: 上下文管理器，用于读取对话历史（history 未提供时）。
        session_id: 会话 ID。
        user_message: 当前用户输入文本。
        memory_context: 记忆检索结果（可选）。
        images: 多模态图像列表（可选）。
        is_realtime_voice: 是否为实时语音模式。True 时走瘦身分支，
            跳过重型隐藏提示词，仅保留核心人设 + voice_prompt + 最近 2 轮对话。
        tts_engine: TTS 引擎名称，决定实时模式下注入哪个 voice_prompt。
            "orpheus" → orpheus_voice_prompt（含情感标签指南）；其他值 → realtime_voice_prompt（默认）。
        history: 调用方已加载的历史消息（可选）。未提供时从 context_mgr 读取。

    Returns:
        list[dict]: OpenAI 格式的消息列表。
    """
    hidden_prompts = _get_hidden_prompts()
    messages: List[dict] = []

    system_prompt = agent_config.get("system_prompt", "")
    # 核心人设 System Prompt：实时与非实时模式均保留，确保 LLM 不丢失基础人设和能力。
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # ====================================================================
    # 实时语音模式：瘦身 Prompt，确保 Tokens < 600，锁死 80ms TTFT
    # --------------------------------------------------------------------
    # 保留：核心人设 system_prompt + 对应 voice_prompt + 最近 2 轮对话
    # 跳过：MemoryRouter 深度图检索、HybridSearch、技能注入、重型隐藏提示词
    #       （合计约 1500 tokens）
    # ====================================================================
    if is_realtime_voice:
        if tts_engine == "orpheus":
            voice_prompt = hidden_prompts.get("orpheus_voice_prompt", "")
        else:
            voice_prompt = hidden_prompts.get("realtime_voice_prompt", "")
        if voice_prompt:
            messages.append({"role": "system", "content": voice_prompt})

        realtime_history = _resolve_history(
            context_mgr, session_id, history, REALTIME_VOICE_HISTORY_LIMIT
        )
        _append_history(messages, realtime_history[:REALTIME_VOICE_HISTORY_LIMIT])

        # 实时语音模式不支持多模态图像注入，直接送文本
        messages.append({"role": "user", "content": user_message})

        # Token 预算：核心人设 ~100 + voice_prompt ~200 + 2 轮对话 ~200 = ~500 tokens < 600
        return messages

    # ====================================================================
    # 以下为非实时模式（默认）：按模型类型注入隐藏提示词
    # include_hidden_prompts=False 用于 AnythingLLM 兼容路径，保持其最小化行为。
    # ====================================================================
    if include_hidden_prompts:
        model_type = agent_config.get("model", "main").lower()
        hidden_parts = []

        if "tools" in hidden_prompts:
            hidden_parts.append(hidden_prompts["tools"])

        if model_type == "main":
            for key in ["emotion_prompts", "effect_prompts", "tool_usage_prompts", "graph_tools", "master_model_prompt"]:
                if key in hidden_prompts:
                    hidden_parts.append(hidden_prompts[key])
        elif model_type == "summary":
            for key in ["emotion_prompts", "effect_prompts", "graph_tools", "summary_model_prompt"]:
                if key in hidden_prompts:
                    hidden_parts.append(hidden_prompts[key])
        elif model_type in ["assistant", "memory"]:
            for key in ["emotion_prompts", "effect_prompts", "tool_usage_prompts", "graph_tools", "assistant_model_prompt"]:
                if key in hidden_prompts:
                    hidden_parts.append(hidden_prompts[key])

        if hidden_parts:
            messages.append({"role": "system", "content": "\n\n".join(hidden_parts)})

        if memory_context and agent_config.get("use_memory", True):
            messages.append({"role": "system", "content": f"相关记忆:\n{memory_context}"})

        _inject_cxfc_skills(messages, user_message)

    history_limit = get_settings().config.limits.context.chat_context_limit
    chat_history = _resolve_history(context_mgr, session_id, history, history_limit)
    _append_history(messages, chat_history)

    if images and agent_config.get("vision_enabled", False):
        _append_multimodal_user(messages, images, user_message)
    else:
        messages.append({"role": "user", "content": user_message})

    return messages