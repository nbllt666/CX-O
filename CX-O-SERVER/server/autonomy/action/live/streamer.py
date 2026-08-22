"""CX-O-Autonomy 直播行动（P3-T1）。

Streamer 封装「半自动直播」的完整行动流水线，供 autonomy_start_live /
autonomy_stop_live 工具 handler 与自主主循环调用：

    prepare_script（生成直播脚本） → start_live（半自动确认门 + OBS 开播）
    → stop_live（下播 + 直播回忆记忆）

行为语义：
- prepare_script：经 llm_client 按人设生成中文直播脚本（标题/主题/大纲/开场白/
  互动要点），返回结构化 {title, outline, opening, script, reason}；llm_client
  缺失返回 {script: "", reason: "llm_unavailable"}；LLM 调用失败/空内容返回
  {script: "", reason: "llm_error"}。
- start_live：半自动门——注入 confirmation_callback 时请求用户确认并返回
  {status: "awaiting_confirmation"} 等待确认（不执行开播）；确认通过（或未注入
  回调）且 computer_control 可调用时执行 OBS 开播动作序列，返回
  {status: "executed", script, result}；未接入执行器返回 {status: "prepared", script}。
- stop_live：computer_control 可调用时执行下播动作，随后经 memory_actions 写入
  "直播回忆"长期记忆（tags=["#直播回忆", "#经历"]，permanent=False，
  importance=4），返回 {status, summary_memory_id}；memory_actions 缺失时
  summary_memory_id 为 None。

本模块无文件 IO，禁止相对路径。
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Callable, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 直播回忆记忆写入参数（对齐 memory_actions.write_memory 语义）
_LIVE_MEMORY_TAGS: List[str] = ["#直播回忆", "#经历"]
_LIVE_MEMORY_TYPE = "long_term"
_LIVE_MEMORY_PERMANENT = False
_LIVE_MEMORY_IMPORTANCE = 4

# OBS 开播/下播动作序列用到的电脑控制工具（对齐 computer_control_plugin.schema.json）
TOOL_RUN_COMMAND = "computer_run_command"
TOOL_KEYBOARD = "computer_keyboard_control"

# LLM 脚本生成状态标记（写入 prepare_script 返回的 reason 字段）
_REASON_OK = "ok"
_REASON_LLM_UNAVAILABLE = "llm_unavailable"
_REASON_LLM_ERROR = "llm_error"


class Streamer:
    """半自动直播行动：生成脚本 → 用户确认 → OBS 开播 → 下播写回忆。

    Args:
        llm_client: LLMClient 实例（chat 返回 LLMResponse，取 .content 作为直播
            脚本）；可为 None，此时 prepare_script 返回 llm_unavailable。
        memory_actions: MemoryActions 实例（提供 write_memory）；可为 None，
            此时 stop_live 不写记忆（summary_memory_id=None）。
        computer_control: 电脑控制调用器，签名 computer_control(script) -> dict，
            可同步/异步；为 None 时开播/下播走 prepared/stopped 未执行态
            （等待执行器接入）。
        confirmation_callback: 用户确认回调，签名 confirmation_callback(script)，
            可同步/异步；注入时 start_live 请求用户确认并返回 awaiting_confirmation
            （半自动等待确认，P4 前端接线）。
        persona: 人设字典，取 persona.system_prompt 或 persona.description 用于脚本生成。
    """

    def __init__(
        self,
        *,
        llm_client: Optional[Any] = None,
        memory_actions: Optional[Any] = None,
        computer_control: Optional[Callable] = None,
        confirmation_callback: Optional[Callable] = None,
        persona: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化直播行动：保存注入依赖与人设。"""
        self.llm_client: Any = llm_client
        self.memory_actions: Any = memory_actions
        self.computer_control: Optional[Callable] = computer_control
        self.confirmation_callback: Optional[Callable] = confirmation_callback
        self.persona: Dict[str, Any] = persona or {}

    # ================================================================ 脚本生成
    async def prepare_script(
        self, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """按人设生成中文直播脚本（标题/主题/大纲/开场白/互动要点）。

        Args:
            context: 可选上下文（含素材 material / 主题 theme 等生成素材）。

        Returns:
            成功返回 {title, outline, opening, script, reason:"ok"}；
            llm_client 缺失返回 {script: "", reason: "llm_unavailable"}；
            LLM 调用失败/空内容返回 {script: "", reason: "llm_error"}。
        """
        if self.llm_client is None:
            return {"script": "", "reason": _REASON_LLM_UNAVAILABLE}

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_content(context)},
        ]
        try:
            response = await self.llm_client.chat(messages=messages)
        except Exception as e:
            logger.error("直播脚本生成 LLM 调用失败: %s", e)
            return {"script": "", "reason": _REASON_LLM_ERROR}
        if getattr(response, "error", None):
            logger.error("直播脚本生成 LLM 返回错误: %s", response.error)
            return {"script": "", "reason": _REASON_LLM_ERROR}
        text = str(getattr(response, "content", "") or "").strip()
        if not text:
            return {"script": "", "reason": _REASON_LLM_ERROR}

        parsed = self._parse_script_response(text)
        return {**parsed, "reason": _REASON_OK}

    # ================================================================ 半自动开播
    async def start_live(
        self, script: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """半自动开播：请求用户确认 → OBS 开播动作序列。

        Args:
            script: 直播脚本字典（可来自 prepare_script 或调用方）；缺省空字典。

        Returns:
            注入确认回调时：{status: "awaiting_confirmation", script}（等待确认，不执行）；
            确认通过（或未注入回调）且执行器可用时：{status: "executed", script, result}；
            未接入执行器：{status: "prepared", script}。
        """
        script_obj: Dict[str, Any] = dict(script or {})

        # 半自动门：注入确认回调 → 请求用户确认并等待（不执行开播）
        if callable(self.confirmation_callback):
            await self._maybe_await(self.confirmation_callback(script_obj))
            return {"status": "awaiting_confirmation", "script": script_obj}

        # 确认通过（或无回调）且执行器可用 → 执行 OBS 开播动作序列
        if callable(self.computer_control):
            result = self.computer_control(self._build_start_script())
            result = await self._maybe_await(result)
            return {"status": "executed", "script": script_obj, "result": result}

        # 未接入执行器：脚本已就绪，返回 prepared 未执行态
        return {"status": "prepared", "script": script_obj}

    # ================================================================ 下播写回忆
    async def stop_live(
        self, summary: Optional[str] = None
    ) -> Dict[str, Any]:
        """下播并写入"直播回忆"长期记忆。

        Args:
            summary: 下播总结文本；缺省时使用自动生成的下播总结。

        Returns:
            {status: "stopped", result?, summary_memory_id}；memory_actions 缺失
            或记忆写入失败时 summary_memory_id 为 None。
        """
        result = None
        if callable(self.computer_control):
            raw = self.computer_control(self._build_stop_script())
            result = await self._maybe_await(raw)

        content = str(summary or "").strip() or self._auto_summary()
        summary_memory_id: Optional[str] = None
        if self.memory_actions is not None:
            try:
                memory_result = await self.memory_actions.write_memory(
                    content=content,
                    tags=list(_LIVE_MEMORY_TAGS),
                    type=_LIVE_MEMORY_TYPE,
                    permanent=_LIVE_MEMORY_PERMANENT,
                    importance=_LIVE_MEMORY_IMPORTANCE,
                )
            except Exception as e:
                logger.error("直播回忆记忆写入失败: %s", e)
                memory_result = {"error": str(e), "memory_id": None}
            if isinstance(memory_result, dict):
                summary_memory_id = memory_result.get("memory_id")
            else:
                summary_memory_id = str(memory_result)

        out: Dict[str, Any] = {
            "status": "stopped",
            "summary_memory_id": summary_memory_id,
        }
        if result is not None:
            out["result"] = result
        return out

    # ================================================================ 子步骤
    def _build_system_prompt(self) -> str:
        """组装脚本生成的 system prompt：人设 + 中文直播脚本写作指令。"""
        lines: List[str] = []
        persona_text = self.persona.get("system_prompt") or self.persona.get("description")
        if persona_text:
            lines.append(f"【人设】{persona_text}")
            lines.append("")
        lines.append(
            "请以第一人称设计一场中文直播，按以下五个部分输出（每部分一行，"
            "以【标题】【主题】【大纲】【开场白】【互动要点】作为行首标记）：\n"
            "【标题】直播标题（20字以内）\n"
            "【主题】直播主题\n"
            "【大纲】直播流程大纲（分点简述）\n"
            "【开场白】开场白（贴合人设，温柔自然）\n"
            "【互动要点】与观众互动的要点"
        )
        return "\n".join(lines)

    def _build_user_content(self, context: Optional[Dict[str, Any]]) -> str:
        """组装脚本生成的 user 消息：可选主题/素材。"""
        ctx = context or {}
        parts: List[str] = []
        theme = ctx.get("theme") or ctx.get("主题")
        if theme:
            parts.append(f"直播主题：{theme}")
        material = ctx.get("material") or ctx.get("素材")
        if material:
            parts.append(f"可参考素材：{material}")
        if not parts:
            parts.append("请自由发挥。")
        return "\n".join(parts)

    @staticmethod
    def _parse_script_response(text: str) -> Dict[str, Any]:
        """从 LLM 返回文本解析直播脚本结构化字段（标题/大纲/开场白/互动要点）。

        优先匹配 【section】...（到下一个【或结尾）；回退匹配 section：/ section:；
        解析失败时整段作为正文（script），标题取首个非空行。
        """
        if not text or not text.strip():
            return {
                "title": "",
                "outline": "",
                "opening": "",
                "script": "",
                "interaction": "",
            }

        def _extract(section: str) -> str:
            match = re.search(rf"【{section}】\s*(.*?)(?=\n\s*【|\Z)", text, re.S)
            if match:
                return match.group(1).strip()
            match = re.search(rf"{section}\s*[:：]\s*(.+)", text)
            if match:
                return match.group(1).strip()
            return ""

        title = _extract("标题") or _extract("主题")
        outline = _extract("大纲")
        opening = _extract("开场白")
        interaction = _extract("互动要点")

        if not (title or outline or opening):
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            title = lines[0][:30] if lines else ""
            outline = ""
            opening = ""

        return {
            "title": title,
            "outline": outline,
            "opening": opening,
            "script": text,
            "interaction": interaction,
        }

    def _build_start_script(self) -> List[Dict[str, Any]]:
        """构造 OBS 开播动作序列（面向电脑控制执行器）。

        computer_run_command 启动 OBS 并以 --startstreaming 参数直接开始推流
        （对齐 command_request 契约：command + 结构化 args，不拼接 shell）。
        """
        return [
            {
                "tool": TOOL_RUN_COMMAND,
                "arguments": {"command": "obs64", "args": ["--startstreaming"]},
                "description": "启动 OBS 并开始推流",
            },
        ]

    def _build_stop_script(self) -> List[Dict[str, Any]]:
        """构造 OBS 下播动作序列（面向电脑控制执行器）。

        computer_run_command 以 --stopstreaming 参数停止 OBS 推流。
        """
        return [
            {
                "tool": TOOL_RUN_COMMAND,
                "arguments": {"command": "obs64", "args": ["--stopstreaming"]},
                "description": "停止 OBS 推流",
            },
        ]

    def _auto_summary(self) -> str:
        """生成默认下播总结文本（未提供 summary 时使用）。"""
        return "本次直播已结束，感谢观众朋友的陪伴。期待下一次与大家分享更多有趣的故事与见闻。"

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """若 value 是 awaitable 则等待后返回，否则原样返回（兼容 sync/async）。"""
        if inspect.isawaitable(value):
            return await value
        return value
