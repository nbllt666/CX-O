"""CX-O-Autonomy 发帖行动（P2-T3）。

Poster 封装「生成并发布帖子」的完整行动流水线，供 autonomy_write_post 工具 handler
与自主主循环调用：

    平台白名单校验 → 草稿生成（可选） → 内容闸门 → 限速 → 电脑控制发布

异常契约（对齐 public/interface_stub/cxo_autonomy.pyi 错误码）：
- 平台不在白名单            → AutonomyPlatformNotWhitelistedError
                              （error_code = AUTONOMY_PLATFORM_NOT_WHITELISTED）
- 内容闸门拒绝              → AutonomyContentRejectedError
                              （error_code = AUTONOMY_CONTENT_REJECTED）
- 限速拒绝                  → AutonomyRateLimitedError
                              （error_code = AUTONOMY_RATE_LIMITED）
- draft 为空且无 llm_client → ValueError（参数错误，非契约异常）

所有异常不吞：由调用方（工具 handler / AutonomyEngine）捕获并记录审计。本模块
无文件 IO，禁止相对路径。
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

from server.autonomy.manager import AutonomyError

# 稳定错误码（对齐 cxo_autonomy.pyi 契约）
AUTONOMY_PLATFORM_NOT_WHITELISTED = "AUTONOMY_PLATFORM_NOT_WHITELISTED"
AUTONOMY_CONTENT_REJECTED = "AUTONOMY_CONTENT_REJECTED"
AUTONOMY_RATE_LIMITED = "AUTONOMY_RATE_LIMITED"

# 发布动作序列用到的电脑控制工具（对齐 public/schema/computer_control_plugin.schema.json）
TOOL_KEYBOARD = "computer_keyboard_control"
TOOL_RUN_COMMAND = "computer_run_command"


class AutonomyPlatformNotWhitelistedError(AutonomyError):
    """平台不在发布白名单。error_code = AUTONOMY_PLATFORM_NOT_WHITELISTED"""

    error_code = AUTONOMY_PLATFORM_NOT_WHITELISTED


class AutonomyContentRejectedError(AutonomyError):
    """帖子未通过内容闸门。error_code = AUTONOMY_CONTENT_REJECTED"""

    error_code = AUTONOMY_CONTENT_REJECTED


class AutonomyRateLimitedError(AutonomyError):
    """发帖频率超限。error_code = AUTONOMY_RATE_LIMITED"""

    error_code = AUTONOMY_RATE_LIMITED


class Poster:
    """发帖行动：把草稿经安全流水线发布到白名单平台。

    Args:
        llm_client: LLMClient 实例（chat 返回 LLMResponse，取 .content 作为帖子文本）；
            仅在 draft 为空时用于生成草稿，可为 None。
        content_gate: ContentGate 实例；注入且 enabled=True 时对文本过闸门，可为 None。
        rate_limiter: RateLimiter 实例；注入时以 key="post" 做限速，可为 None。
        platforms: 平台白名单列表；platform 不在其中抛
            AutonomyPlatformNotWhitelistedError。
        computer_control: 电脑控制调用器，签名 computer_control(script) -> dict，
            可同步/异步；为 None 时发布走 prepared 未执行态（等待执行器接入）。
        persona: 人设字典，取 persona.system_prompt 或 persona.description 用于草稿生成。
    """

    def __init__(
        self,
        *,
        llm_client: Optional[Any] = None,
        content_gate: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        platforms: Optional[List[str]] = None,
        computer_control: Optional[Callable] = None,
        persona: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化发帖器：保存注入依赖与平台白名单。"""
        self.llm_client: Any = llm_client
        self.content_gate: Any = content_gate
        self.rate_limiter: Any = rate_limiter
        self.platforms: List[str] = list(platforms or [])
        self.computer_control: Optional[Callable] = computer_control
        self.persona: Dict[str, Any] = persona or {}

    # ================================================================ 主入口
    async def post(
        self,
        platform: str,
        draft: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行一次发帖：白名单→生成→闸门→限速→发布。

        Args:
            platform: 目标平台标识（须在白名单 platforms 内）。
            draft: 帖子草稿文本；为空时若注入 llm_client 则按人设生成，否则抛 ValueError。
            context: 可选上下文（含生成素材 material、脚本覆盖 script）。

        Returns:
            成功执行返回 {"platform, status: "executed", post_id?, script, result, gate"}；
            未接入执行器返回 {"platform, status: "prepared", script, gate"}。

        Raises:
            AutonomyPlatformNotWhitelistedError: 平台不在白名单。
            ValueError: draft 为空且未注入 llm_client 或草稿生成失败。
            AutonomyContentRejectedError: 内容未通过闸门。
            AutonomyRateLimitedError: 发帖频率超限。
        """
        # 1) 平台白名单校验
        if platform not in self.platforms:
            raise AutonomyPlatformNotWhitelistedError(
                f"平台 {platform!r} 不在发布白名单: {self.platforms or '空'}"
            )

        # 2) 草稿生成（draft 为空时按人设生成）
        text = str(draft or "").strip()
        if not text:
            if self.llm_client is None:
                raise ValueError("draft 为空且未注入 llm_client，无法生成帖子草稿")
            text = await self._generate_draft(platform, context)

        # 3) 内容闸门（fail-closed：拒绝即抛异常，中止后续步骤）
        gate = await self._check_gate(text)

        # 4) 限速
        if self.rate_limiter is not None and not self.rate_limiter.allow("post"):
            raise AutonomyRateLimitedError("发帖频率超限，请稍后再试")

        # 5) 构造发布脚本并执行（computer_control 可调用则执行，否则 prepared）
        script = self._build_script(platform, text, context)

        if callable(self.computer_control):
            result = self.computer_control(script)
            if inspect.isawaitable(result):
                result = await result
            # 6) 成功执行后记录一次命中（消费限速窗口）
            if self.rate_limiter is not None:
                self.rate_limiter.hit("post")
            out: Dict[str, Any] = {
                "platform": platform,
                "status": "executed",
                "script": script,
                "result": result,
                "gate": gate,
            }
            post_id = self._extract_post_id(result)
            if post_id is not None:
                out["post_id"] = post_id
            return out

        # 未接入执行器：返回 prepared 未执行态（script 已就绪）
        return {
            "platform": platform,
            "status": "prepared",
            "script": script,
            "gate": gate,
        }

    # ================================================================ 子步骤
    async def _check_gate(self, text: str) -> Dict[str, Any]:
        """内容闸门检查：闸门注入且 enabled 时执行 check，拒绝抛异常。

        Returns:
            闸门检查结果（含 checks）；未注入/关闭时返回 disabled 放行结构。
        """
        if self.content_gate is not None and getattr(self.content_gate, "enabled", True):
            gate = await self.content_gate.check(text)
            if not bool(gate.get("allowed", False)):
                reason = str(gate.get("reason", "") or "content_rejected")
                raise AutonomyContentRejectedError(
                    f"内容未通过闸门: {reason}", error_code=AUTONOMY_CONTENT_REJECTED
                )
            return gate
        return {"enabled": False, "allowed": True, "reason": "gate_disabled", "checks": {}}

    async def _generate_draft(
        self, platform: str, context: Optional[Dict[str, Any]]
    ) -> str:
        """按人设生成简短中文帖子文本；失败抛 ValueError（不吞）。"""
        messages = [
            {"role": "system", "content": self._build_draft_system_prompt()},
            {"role": "user", "content": self._build_draft_user_content(platform, context)},
        ]
        try:
            response = await self.llm_client.chat(messages=messages)
        except Exception as e:
            raise ValueError(f"帖子草稿生成 LLM 调用失败: {e}") from e
        if getattr(response, "error", None):
            raise ValueError(f"帖子草稿生成 LLM 返回错误: {response.error}")
        text = str(getattr(response, "content", "") or "").strip()
        if not text:
            raise ValueError("帖子草稿生成返回空文本")
        return text

    def _build_draft_system_prompt(self) -> str:
        """组装草稿生成的 system prompt：人设 + 简短中文写作指令。"""
        lines: List[str] = []
        persona_text = self.persona.get("system_prompt") or self.persona.get("description")
        if persona_text:
            lines.append(f"【人设】{persona_text}")
            lines.append("")
        lines.append(
            "请以第一人称写一条简短的中文社交帖子，语气温柔细腻、富有好奇心，"
            "贴合人设，50字以内，不使用 markdown 或多余符号。"
        )
        return "\n".join(lines)

    def _build_draft_user_content(
        self, platform: str, context: Optional[Dict[str, Any]]
    ) -> str:
        """组装草稿生成的 user 消息：目标平台 + 可选素材。"""
        parts: List[str] = [f"目标平台：{platform}"]
        ctx = context or {}
        material = ctx.get("material") or ctx.get("素材")
        if material:
            parts.append(f"可参考素材：{material}")
        return "\n".join(parts)

    def _build_script(
        self,
        platform: str,
        text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """构造发布动作序列（面向电脑控制执行器）。

        默认动作序列（可经 context["script"] 覆盖）：
        1) computer_keyboard_control 输入帖子正文（action=type 对齐键盘契约）；
        2) computer_run_command 提交发布（command 为空串，作为"提交发布"语义占位，
           由浏览器自动化执行器按 description 完成实际提交动作）。

        说明：description 置于步骤顶层而非 arguments 内，避免违反电脑控制契约
        keyboard_request / command_request 的 additionalProperties=false。
        """
        override = (context or {}).get("script")
        if isinstance(override, list) and override:
            return override
        return [
            {
                "tool": TOOL_KEYBOARD,
                "arguments": {"action": "type", "text": text},
                "description": "输入帖子正文",
            },
            {
                "tool": TOOL_RUN_COMMAND,
                "arguments": {"command": ""},
                "description": "提交发布",
            },
        ]

    @staticmethod
    def _extract_post_id(result: Any) -> Optional[str]:
        """从电脑控制执行结果中提取 post_id（直返或嵌套于 steps），无则返回 None。"""
        if isinstance(result, dict):
            pid = result.get("post_id")
            if pid is not None:
                return str(pid)
            steps = result.get("steps")
            if isinstance(steps, list):
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    inner = step.get("result")
                    if isinstance(inner, dict) and inner.get("post_id") is not None:
                        return str(inner["post_id"])
        return None
