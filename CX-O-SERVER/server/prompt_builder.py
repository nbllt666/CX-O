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
    核心人设 + 记忆检索 + 最近 2 轮对话，跳过重型隐藏提示词
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

# 实时语音模式 vLLM prefix cache 命中长度补足 padding。
# ---------------------------------------------------------------------------
# 背景：vLLM 0.22 + gemma-4-e4b-it（sliding attention，窗口 512）的 prefix cache
# 对 <353 tokens 的 prompt 完全不写入/不命中（实测：341 tokens 恒 240ms TTFT；
# 353 tokens 命中后 30-60ms）。生产实时语音新会话无历史时仅 [system+user] 2 条
# 消息 ≈ 341-343 tokens < 353 → LLM TTFT 恒 ~240ms。
# 方案：在 system 消息末尾追加一段固定、语义无害的对话引导语 padding，使完整
# messages token 化后 >=360 tokens（保守余量），TTFT 从 ~240ms 降至 ~60ms。
# 约束：
#   - 不得精简/删除 system_prompt 原有内容（仅追加），不改变回答质量。
#   - 不含任务性指令，仅引导自然对话。
#   - 常量供 server/main.py 语音前缀预热复用，保证预热与生产请求完全同构，
#     从而建立可命中的 prefix cache。
# 实测（tokenize_check.py）：608 字符 system_prompt ≈ 341 tokens，约 1.78 字符/token；
# 本 padding 约 76 字符 ≈ 42 tokens，追加后 341+42=383 >= 360（'你好'）与 343+42=385。
#
# 【回应边界（忽略规则）】除 prefix-cache 补足外，此处同时承载"忽略传导"指令：
# 实时语音主管线（主 LLM 对话）独立于 agent_interrupt 的 IGNORE 判定，只要 ASR
# 产出 ≥2 字文本就会把用户输入送进主 LLM 并可能回复。为让"需要忽略用户说的话"
# （情绪表达/自言自语/噪音）时主 LLM 真的不回复，在此注入回应边界——主 LLM 对
# 非对话性输入可选择不回应/简短回应，对明确提问/请求务必回答。
REALTIME_VOICE_PROMPT_PADDING = (
    "\n\n我们正在通过实时语音自然对话。我会认真倾听你的每一句话，"
    "用亲切友好的方式回应，并尽我所能提供清晰、有帮助的内容。"
    "你可以随时继续表达你的想法，我在这里。"
    "如回复需带明显情绪/语速/音量变化，可在末尾加<tts_instruction>{\"text\":\"语气描述\","
    "\"speed\":语速倍率,\"volume\":音量倍率}</tts_instruction>标签让语音更具表现力；"
    "平淡回复则不加。"
    "\n\n【回应边界】当你说的话只是表达情绪、自言自语或随意感慨（如\"唉，好累啊\"），"
    "而不是在向我提问或请求帮助时，我可以选择不回应或只做简短回应，不强行接话；"
    "当你明确提问或请求帮助时，务必认真、清晰地回答。"
)

# ACP 自动回复模式历史消息条数（与历史实现保持一致）
ACP_HISTORY_LIMIT = 50

# ACP 自动回复专用提示词（移植自 CXHMS v3.1.0，原定义于 server/core/acp/manager.py）
# 替换通用隐藏提示词，避免压制角色设定；强制要求使用 acp_send_message 工具回复，
# 形成真正的 agent-to-agent 互动链路。收敛至本文件作为唯一真相源。
ACP_REPLY_HINT_PROMPT = """<acp_context>
你收到了来自其他 Agent 的 ACP（Agent Communication Protocol）消息。请严格保持你的角色设定和语气风格。

<reply_rule>
**通常应使用 acp_send_message 工具回复对方 Agent，禁止直接在文本中写出回复内容。**

工具调用方式：
- 工具名：acp_send_message
- 参数：
  - agent_id：对方 Agent 的 ID（即消息发送方 from_agent_id）
  - message：你的回复内容（以你的角色身份和语气风格撰写）

示例：若收到来自 agent-xxx 的消息，应调用 acp_send_message(agent_id="agent-xxx", message="你的回复")

调用工具后，可以附加简短的内心独白或动作描写（如角色卡风格），但主要对话内容必须通过工具发送。

**允许不回复的情况**：如果对话已自然结束（如对方说了告别语、对话已无实质内容可回应、继续回复只会形成无意义的循环），你可以选择不调用工具，仅输出一句简短的内心独白即可，不需要强制回复。判断标准：这条消息是否真正需要你的回应？如果不需要，沉默也是一种回答。
</reply_rule>

<behavior>
1. 以你的角色身份回应对方 Agent，保持角色的语言习惯、性格特征
2. 不要以"通用 AI 助手"或"智能助手"自居——你是你，不是万能助手
3. 若需要查询其他 Agent，可调用 acp_list_agents 工具
4. 其他工具（如记忆、搜索）按需调用，但不要主动执行无关操作
5. 回复应自然、有对话感，避免机械的"我随时准备协助您"式套话
6. 避免无意义的循环回复——如果对话已经结束，不要为了回复而回复
</behavior>
</acp_context>"""

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


@lru_cache(maxsize=1)
def _get_hidden_prompts() -> dict:
    """定位并加载 hidden_prompt.yaml（整体缓存）。

    整个函数 lru_cache：隐藏提示词在运行期视为静态，路径解析 + settings 访问 +
    文件 stat 均只在首次调用发生，消除每次 build_messages（含实时语音热路径，
    目标 80ms TTFT）的重复开销。内部 _load_hidden_prompts 已按 path 缓存文件内容。

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
    本函数优先用单次查询 get_recent_messages 取最近 limit 条（消除 count+offset
    两次往返，实时语音热路径受益），不可用时回退 count+offset；再退化首窗口截尾。
    """
    if history is not None:
        return history[-limit:]
    if context_mgr is None:
        return []
    # 优先单次查询取最近 N 条（消除 count+offset 两次往返，实时语音热路径受益）
    recent = getattr(context_mgr, "get_recent_messages", None)
    if callable(recent):
        try:
            return recent(session_id, limit)
        except Exception:
            pass
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
    history: Optional[List[dict]] = None,
    include_hidden_prompts: bool = True,
    acp_context: Optional[dict] = None,
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
            跳过重型隐藏提示词，仅保留核心人设 + 最近 2 轮对话。
        history: 调用方已加载的历史消息（可选）。未提供时从 context_mgr 读取。
        include_hidden_prompts: 是否注入隐藏提示词（默认 True；AnythingLLM 兼容路径置 False）。
        acp_context: 非 None 时进入 ACP 自动回复模式——Agent 通过工具调用决定是否回复，
            无用户轮次。注入 ACP_REPLY_HINT_PROMPT + 历史 + incoming_message 上下文，
            不追加 user 消息、不注入主聊天隐藏提示词（与历史 ACP 行为一致）。
            字典需含 "from_agent_id"（消息发送方 ID）。

    Returns:
        list[dict]: OpenAI 格式的消息列表。
    """
    messages: List[dict] = []

    system_prompt = agent_config.get("system_prompt", "")
    # 核心人设 System Prompt：实时与非实时模式均保留，确保 LLM 不丢失基础人设和能力。
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # ====================================================================
    # ACP 自动回复模式：无用户轮次，Agent 通过工具调用决定是否回复。
    # 注入 ACP 专用提示 + 历史 + 外来消息上下文，不追加 user 消息，
    # 不注入主聊天隐藏提示词（与历史 ACP 行为一致）。
    # ====================================================================
    if acp_context is not None:
        messages.append({"role": "system", "content": ACP_REPLY_HINT_PROMPT})

        acp_history = _resolve_history(context_mgr, session_id, history, ACP_HISTORY_LIMIT)
        _append_history(messages, acp_history)

        from_agent_id = acp_context.get("from_agent_id", "unknown")
        messages.append({
            "role": "system",
            "content": (
                f"<incoming_message>\n"
                f"本条消息来自 Agent（from_agent_id={from_agent_id}）。\n"
                f"如需回复，按 <reply_rule> 调用 acp_send_message 发给该 Agent；"
                f"对话已自然结束时可不回复。\n"
                f"</incoming_message>"
            ),
        })
        return messages

    # ====================================================================
    # 实时语音模式：瘦身 Prompt，保留核心人设 + 记忆 + 最近 2 轮对话
    # --------------------------------------------------------------------
    # 保留：核心人设 system_prompt + 记忆检索（memory_context）+ 最近 2 轮对话
    # 跳过：技能注入、重型隐藏提示词（控制 token 膨胀，维持语音低延迟）
    # ====================================================================
    if is_realtime_voice:
        # vLLM prefix cache 命中长度补足：新会话无历史时 [system+user] 仅 ~341 tokens
        # < 353（vLLM 写入/命中阈值），恒 miss → TTFT ~240ms。在 system 末尾追加
        # 固定无害 padding（REALTIME_VOICE_PROMPT_PADDING）使完整 messages >=360 tokens。
        # 仅追加、不精简 system_prompt 原有内容，语义无害不改变回答质量。
        # padding 同时承载【回应边界（忽略规则）】，不可删减精简。
        for _msg in messages:
            if _msg.get("role") == "system":
                _msg["content"] = _msg["content"] + REALTIME_VOICE_PROMPT_PADDING
                break

        # 记忆注入：追加在稳定前缀 system(padded) 之后、历史之前，作为独立 system 消息。
        # vLLM prefix cache 对 system 前缀 KV 仍 partial 命中；记忆属每次变化段，仅 prefill。
        # receive from caller (audio.py 已通过 retrieve_memory_context 检索)；use_memory=False 或
        # 检索结果为空时跳过。检索失败由调用方降级为 None，此处不影响语音主流程。
        if memory_context and agent_config.get("use_memory", True):
            messages.append({"role": "system", "content": f"相关记忆:\n{memory_context}"})

        realtime_history = _resolve_history(
            context_mgr, session_id, history, REALTIME_VOICE_HISTORY_LIMIT
        )
        # _resolve_history 已保证返回 ≤ REALTIME_VOICE_HISTORY_LIMIT 条，无需再切片
        _append_history(messages, realtime_history)

        # 实时语音模式不支持多模态图像注入，直接送文本
        messages.append({"role": "user", "content": user_message})

        # Token 预算：核心人设 ~100 + 2 轮对话 ~200 = ~300 tokens < 600
        return messages

    # ====================================================================
    # 以下为非实时模式（默认）：按模型类型注入隐藏提示词
    # include_hidden_prompts=False 用于 AnythingLLM 兼容路径，保持其最小化行为。
    # ====================================================================
    # 隐藏提示词仅在非实时路径按需加载（实时语音早退分支不触碰，避免热路径触发 YAML 加载）
    if include_hidden_prompts:
        hidden_prompts = _get_hidden_prompts()
        model_type = agent_config.get("model", "main").lower()
        hidden_parts = []

        if "tools" in hidden_prompts:
            hidden_parts.append(hidden_prompts["tools"])

        if model_type == "main":
            for key in ["emotion_prompts", "avatar_prompts", "effect_prompts", "tool_usage_prompts", "graph_tools", "master_model_prompt"]:
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
        try:
            _append_multimodal_user(messages, images, user_message)
        except Exception:
            # 多模态组装失败（如图像格式异常）时降级为纯文本，避免整次对话报错
            logger.warning("多模态图像组装失败，降级为纯文本用户消息")
            messages.append({"role": "user", "content": user_message})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages
