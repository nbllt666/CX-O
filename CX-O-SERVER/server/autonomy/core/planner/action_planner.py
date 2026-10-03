"""CX-O-Autonomy LLM 规划器：ActionPlanner（P1-T6）。

ActionPlanner 根据自主系统的动机（motivations）/时段相位（phase）/社交热点
（hotspots）/环境上下文快照（context_snapshot），调用 LLM 输出结构化 JSON
行动决策，输出对齐 public/schema/autonomy_action.schema.json（action 必填，
target/payload/reason/expected_outcome 可缺省）。

行为语义：
- 组装 system prompt：人设（persona.system_prompt / description）+ 角色指令 +
  动机语义（动机值越高＝越强的行动倾向；curiosity 越高越想探索）+ 焦点自报要求 +
  行动集（allowed_actions，默认 9 项）+ 安全约束（禁止非法 action）
- 软阈值收敛候选：动机值 >= 0.6 者按值降序映射为候选行动（curiosity→read_news/search、
  social_need→write_post/start_live、creative_drive→write_memory/write_diary、
  fatigue→sleep），作为"软建议"注入 user 消息；**不裁剪 allowed_actions**（非硬门控）
- focus 自报：LLM 在决策 JSON 中声明本轮关注对象 focus={topic, level}，经
  _normalize_focus 规整后透传（缺失/非法则省略该键＝沿用上次焦点）
- 可选工具调用循环：注入 tool_executor 且 llm_client 支持 tools 时，首轮带
  tools 调用，解析 LLMResponse.tool_calls 逐个执行（tool_executor(name, args)），
  观察结果回填消息，重复直到无 tool_calls 或达 max_tool_rounds，最后按最终轮
  纯文本 content 解析 JSON
- 校验 action 是否在 allowed_actions：不在则改写为 "wait"（安全兜底动作）并
  保留 reason
- 校验 action 是否命中 blocked_actions 黑名单（构造注入或上下文传入，缺省空集）：
  命中则改写为 "wait"，reason 注明 blocked_actions
- 解析失败返回 {"action": "wait", "reason": "parse_failed"}
- LLM 调用失败（client 抛错 / LLMResponse.error）返回 {"action": "wait",
  "reason": "llm_error"}，不冒泡

本模块无文件 IO，禁止相对路径。
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 默认行动集（对齐 server/autonomy/models.py ActionType 与
# autonomy_action.schema.json 的 9 项枚举）
DEFAULT_ALLOWED_ACTIONS: List[str] = [
    "sleep",
    "wait",
    "read_news",
    "search",
    "write_memory",
    "write_post",
    "start_live",
    "stop_live",
    "write_diary",
]

# 提取最外层 JSON 对象块（容忍 markdown 代码块包裹与前后缀文本）
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

# 动机 → 候选行动软映射（对齐人类裁决：语义落地＝提示词 + 软阈值收敛候选，不是硬门控）。
# 动机值越高＝越强的行动倾向，候选仅作提示，不裁剪 allowed_actions。
_MOTIVATION_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "curiosity": ("read_news", "search"),
    "social_need": ("write_post", "start_live"),
    "creative_drive": ("write_memory", "write_diary"),
    "fatigue": ("sleep",),
}

# 软阈值：动机值 >= 该值才计入"本轮优先候选"（仅建议，不限制可选行动）
_MOTIVATION_SOFT_THRESHOLD = 0.6


async def _maybe_await(value: Any) -> Any:
    """若 value 是 awaitable 则等待后返回，否则原样返回（兼容 sync/async 可调用对象）。"""
    if inspect.isawaitable(value):
        return await value
    return value


class ActionPlanner:
    """LLM 自主行动规划器：把动机/时段/热点/上下文决策为一条结构化行动。

    Args:
        llm_client: LLMClient 实例（chat 返回 LLMResponse，可通过 kwargs 传 tools）
        persona: 人设字典，可取 persona.system_prompt 或 persona.description
        allowed_actions: 允许的行动集；缺省使用全部 9 项
        blocked_actions: 黑名单行动集（缺省空集）；action 命中时改写为 wait，
            可从构造注入，也可经 plan(context) 的 context["blocked_actions"] 传入
        tool_executor: 工具执行器，签名 (name, arguments) -> 观察结果（可同步/异步）
        memory_provider: 记忆提供者，入参 context 返回记忆文本（可同步/异步）
        max_tool_rounds: 工具调用最大轮数（每轮执行后可追加一次 LLM 调用）
    """

    def __init__(
        self,
        llm_client: Any,
        persona: Optional[Dict[str, Any]] = None,
        allowed_actions: Optional[List[str]] = None,
        blocked_actions: Optional[List[str]] = None,
        tool_executor: Optional[Callable] = None,
        memory_provider: Optional[Callable] = None,
        max_tool_rounds: int = 3,
    ) -> None:
        """初始化规划器：保存客户端、人设、行动集、黑名单与可选回调，钳制工具轮数下限。"""
        self.llm_client: Any = llm_client
        self.persona: Dict[str, Any] = persona or {}
        self.allowed_actions: List[str] = (
            list(allowed_actions) if allowed_actions else list(DEFAULT_ALLOWED_ACTIONS)
        )
        self.blocked_actions: set = set(blocked_actions or ())
        self.tool_executor: Optional[Callable] = tool_executor
        self.memory_provider: Optional[Callable] = memory_provider
        self.max_tool_rounds: int = max(1, int(max_tool_rounds))

    async def plan(self, context: dict) -> dict:
        """执行一次规划：组装提示词 → 工具调用循环 → 解析/校验 JSON → 返回行动决策。

        Args:
            context: 输入上下文，含 motivations(dict)/phase(str)/hotspots(list)/
                context_snapshot(dict)

        Returns:
            对齐 autonomy_action.schema.json 的决策字典
            （action/target/payload/reason/expected_outcome）。
            解析失败返回 {"action": "wait", "reason": "parse_failed"}；
            LLM 调用失败返回 {"action": "wait", "reason": "llm_error"}。
        """
        # 记忆注入（可选能力，失败静默忽略，不阻断规划）
        memory_text = await self._fetch_memory_text(context)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_message(context, memory_text)},
        ]
        tools: Optional[List[Dict[str, Any]]] = None
        kwargs: Dict[str, Any] = {}
        if self._supports_tools():
            tools = self._build_tools()
            kwargs["tools"] = tools

        try:
            response = await self.llm_client.chat(messages=messages, **kwargs)
        except Exception as e:
            logger.error("LLM 规划器首轮调用失败: %s", e)
            return {"action": "wait", "reason": "llm_error"}

        # 工具调用循环：最多执行 max_tool_rounds 轮，随后按最终轮文本 content 解析
        for _ in range(self.max_tool_rounds):
            if response.error:
                return {"action": "wait", "reason": "llm_error"}
            if not response.tool_calls:
                break
            # 回填带工具调用的 assistant 消息（含原始 tool_calls，供兼容后端透传）
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": response.tool_calls,
                }
            )
            for tool_call in response.tool_calls:
                name, arguments = self._extract_tool_call(tool_call)
                observation = await self._execute_tool(name, arguments)
                messages.append(
                    {"role": "tool", "name": name, "content": observation}
                )
            try:
                response = await self.llm_client.chat(messages=messages, **kwargs)
            except Exception as e:
                logger.error("LLM 规划器工具轮调用失败: %s", e)
                return {"action": "wait", "reason": "llm_error"}

        if response.error:
            return {"action": "wait", "reason": "llm_error"}

        data = self._extract_json(response.content)
        if data is None:
            return {"action": "wait", "reason": "parse_failed"}
        blocked_actions = self.blocked_actions
        ctx_blocked = context.get("blocked_actions")
        if isinstance(ctx_blocked, (list, tuple, set)) and ctx_blocked:
            blocked_actions = self.blocked_actions | set(ctx_blocked)
        return self._validate_action(data, blocked_actions=blocked_actions)

    # ================================================================ 提示词组装
    def _build_system_prompt(self) -> str:
        """组装 system prompt：人设 + 角色指令 + 动机语义 + 焦点自报 + 行动集 + 安全约束。

        动机语义段是"curiosity 越高越想探索"这一裁决的落点——旧版把裸动机 JSON
        直接喂给 LLM 且不声明方向，导致 curiosity=1.0 被误读为"信息已足够→wait"。
        """
        lines: List[str] = []
        persona_text = self.persona.get("system_prompt") or self.persona.get("description")
        if persona_text:
            lines.append(f"【人设】{persona_text}")
            lines.append("")
        lines.append("你是一个自主行动规划器。请根据给定的动机、时段、热点与上下文快照，"
                     "从允许的行动集中选择一个行动，并输出结构化 JSON action。")
        lines.append("")
        lines.append("输出格式（JSON 对象，禁止输出 JSON 之外的任何内容）：")
        lines.append(
            '{"action": "<行动类型>", "target": "<目标对象>", "payload": {<动作负载>}, '
            '"reason": "<决策理由>", "expected_outcome": "<预期效果>", '
            '"focus": {"topic": "<本轮最想探索的具体事物>", "level": <兴趣强度 0-1>}}'
        )
        lines.append("")
        lines.append(f"允许的行动集: {json.dumps(self.allowed_actions, ensure_ascii=False)}")
        lines.append("行动类型说明：sleep=休眠；wait=等待/暂不行动；read_news=阅读新闻；"
                     "search=搜索；write_memory=写入记忆；write_post=发布动态；"
                     "start_live=开始直播；stop_live=结束直播；write_diary=写日记。")
        lines.append("")
        lines.append("动机语义（重要）：动机值越高表示越强烈的行动倾向，**不是**需求已被满足。")
        lines.append("- curiosity 越高越想探索新知识 → 倾向 read_news / search，且应指向 focus.topic；")
        lines.append("- social_need 越高越想对外表达 → 倾向 write_post / start_live；")
        lines.append("- creative_drive 越高越有创作冲动 → 倾向 write_memory / write_diary；")
        lines.append("- fatigue 越高越应该休息 → 倾向 sleep。")
        lines.append("动机值偏低表示该需求暂时被满足，不必强行执行对应行动。")
        lines.append("")
        lines.append("焦点对象：你必须在输出 JSON 中声明本轮最想探索的对象 focus，"
                     '形如 {"topic": "...", "level": 0.7}。')
        lines.append("topic 要具体可检索（如\"AI 芯片出口管制\"），禁止\"新闻\"\"生活\"这类泛词；"
                     "level 为你对该对象的兴趣强度（0-1）；沿用上次焦点时可直接重复上一次的 topic。")
        lines.append("")
        lines.append("行动倾向与候选仅为**软建议**：允许的行动集不做裁剪，你可依据实际情境自行取舍。")
        lines.append("")
        lines.append("安全约束：严禁输出允许行动集之外的 action；严禁输出任何非法、越权或"
                     "违反平台规则的行动；reason 需说明决策依据。")
        return "\n".join(lines)

    def _build_user_message(self, context: dict, memory_text: str = "") -> str:
        """组装 user 消息：当前动机/时段/软候选/焦点/热点/上下文，可附加记忆摘要。"""
        parts: List[str] = []
        parts.append("以下是当前自主系统的状态，请据此输出一个行动决策 JSON。")
        parts.append("")
        parts.append(f"当前时段相位: {context.get('phase', 'unknown')}")
        motivations = context.get("motivations", {})
        if isinstance(motivations, dict):
            parts.append(f"动机状态: {json.dumps(motivations, ensure_ascii=False)}")
        else:
            parts.append(f"动机状态: {motivations}")
        candidates = self._build_candidates(motivations)
        if candidates:
            parts.append(
                "本轮优先候选（软建议，非强制）: "
                f"{json.dumps(candidates, ensure_ascii=False)}"
            )
        else:
            parts.append("本轮无显著动机（全部低于软阈值），可考虑 wait / sleep")
        focus = context.get("focus")
        if isinstance(focus, dict) and focus:
            parts.append(f"当前焦点对象: {json.dumps(focus, ensure_ascii=False)}")
        else:
            parts.append("当前焦点对象: 无（可自行提出一个具体对象）")
        hotspots = context.get("hotspots", []) or []
        if hotspots:
            parts.append(f"社交热点: {json.dumps(hotspots[:5], ensure_ascii=False)}")
        else:
            parts.append("社交热点: 无")
        snapshot = context.get("context_snapshot", {}) or {}
        if isinstance(snapshot, dict) and snapshot:
            parts.append(f"环境上下文: {json.dumps(snapshot, ensure_ascii=False)}")
        if memory_text:
            parts.append("")
            parts.append(f"相关记忆:\n{memory_text}")
        return "\n".join(parts)

    @staticmethod
    def _build_candidates(motivations: Any) -> List[str]:
        """按软阈值把显著动机收敛为候选行动（仅建议，不裁剪 allowed_actions）。

        动机值 >= _MOTIVATION_SOFT_THRESHOLD 者按值降序，依次展开其软映射行动并去重；
        无显著动机时返回空列表（提示词侧回退"可考虑 wait / sleep"）。
        """
        if not isinstance(motivations, dict):
            return []
        active: List[Tuple[str, float]] = []
        for name, value in motivations.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if float(value) >= _MOTIVATION_SOFT_THRESHOLD:
                active.append((str(name), float(value)))
        active.sort(key=lambda item: item[1], reverse=True)
        candidates: List[str] = []
        for name, _ in active:
            for action in _MOTIVATION_CANDIDATES.get(name, ()):
                if action not in candidates:
                    candidates.append(action)
        return candidates

    # ================================================================ 工具调用支持
    def _supports_tools(self) -> bool:
        """判定是否启用工具调用：需 tool_executor 可调用，且客户端未显式声明不支持。"""
        if not callable(self.tool_executor):
            return False
        client = self.llm_client
        return not (hasattr(client, "supports_tools") and client.supports_tools is False)

    @staticmethod
    def _build_tools() -> List[Dict[str, Any]]:
        """构建工具声明列表（通用 action_tool，参数自由对象，兼容 Ollama/OpenAI 形态）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "action_tool",
                    "description": "执行行动决策所需的辅助查询（如获取上下文、检索记忆）。",
                    "parameters": {"type": "object", "additionalProperties": True},
                },
            }
        ]

    @staticmethod
    def _extract_tool_call(tool_call: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """从 LLMResponse.tool_calls 条目提取 (name, arguments)。

        兼容 Ollama（{"function": {"name":..., "arguments": {...}}}）与 OpenAI 兼容
        形态（arguments 可能为 JSON 字符串）。
        """
        fn = tool_call.get("function") if isinstance(tool_call, dict) else None
        if isinstance(fn, dict):
            name = str(fn.get("name", "") or "")
            raw_args = fn.get("arguments", {}) or {}
        else:
            name = str(tool_call.get("name", "") or "")
            raw_args = tool_call.get("arguments", {}) or {}
        if isinstance(raw_args, str):
            try:
                arguments = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                arguments = {"raw": raw_args}
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            arguments = {}
        return name, arguments

    async def _execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """执行单个工具并序列化为观察文本；失败返回错误观察，不阻断整个循环。"""
        if not callable(self.tool_executor):
            return json.dumps({"error": "tool_executor 不可用"}, ensure_ascii=False)
        try:
            result = await _maybe_await(self.tool_executor(name, arguments))
        except Exception as e:
            logger.warning("工具执行失败 %s: %s", name, e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)

    # ================================================================ 记忆注入
    async def _fetch_memory_text(self, context: dict) -> str:
        """通过 memory_provider 拉取相关记忆摘要；不可用或失败静默返回空串。"""
        if not callable(self.memory_provider):
            return ""
        try:
            raw = await _maybe_await(self.memory_provider(context))
        except Exception as e:
            logger.warning("记忆注入失败: %s", e)
            return ""
        if raw is None:
            return ""
        return str(raw)

    # ================================================================ 解析与校验
    def _extract_json(self, text: Any) -> Optional[Dict[str, Any]]:
        """从 LLM 输出中提取 JSON 对象：先整体解析，再容忍 markdown 代码块与前后缀文本。

        Returns:
            解析出的 dict，或 None（无法解析出合法 JSON 对象）。
        """
        if not text or not isinstance(text, str):
            return None
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    def _validate_action(
        self, data: Dict[str, Any], blocked_actions: Optional[set] = None
    ) -> Dict[str, Any]:
        """校验 action 合法性并对齐输出字段：黑名单/非法 action 改写为 wait（安全兜底）并保留 reason。

        blocked_actions 缺省取构造时注入的实例黑名单（缺省空集）；action 命中
        黑名单或不在 allowed_actions 时改写为 wait，reason 注明 blocked_actions
        或非法行动。

        focus 为可选项：LLM 自报且合法时才写入结果（省略＝沿用上次焦点），
        以保全"缺省字段不回填"的既有输出形状。

        Args:
            data: 解析出的原始决策字典（可能含非法字段）。
            blocked_actions: 本次调用的黑名单集合；None 时使用 self.blocked_actions。

        Returns:
            对齐 autonomy_action.schema.json 的决策字典。
        """
        blocked = self.blocked_actions if blocked_actions is None else set(blocked_actions)
        action = data.get("action")
        reason = data.get("reason", "")
        if action in blocked:
            note = f"行动 {action!r} 命中 blocked_actions 黑名单，已改写为 wait"
            reason = f"{note}；{reason}" if reason else note
            action = "wait"
        elif action not in self.allowed_actions:
            note = f"非法行动 {action!r} 已改写为 wait"
            reason = f"{note}；{reason}" if reason else note
            action = "wait"
        payload = data.get("payload")
        result: Dict[str, Any] = {
            "action": action,
            "target": data.get("target", ""),
            "payload": payload if isinstance(payload, dict) else {},
            "reason": reason,
            "expected_outcome": data.get("expected_outcome", ""),
        }
        focus = self._normalize_focus(data.get("focus"))
        if focus is not None:
            result["focus"] = focus
        return result

    @staticmethod
    def _normalize_focus(raw: Any) -> Optional[Dict[str, Any]]:
        """规整 LLM 自报的焦点对象；缺失或非法返回 None（调用方省略该键）。

        合法条件：dict 且 topic 去空白后非空；level 非数值按 0.0 处理并 clamp 到 [0,1]。
        """
        if not isinstance(raw, dict):
            return None
        topic = str(raw.get("topic", "") or "").strip()
        if not topic:
            return None
        try:
            level = float(raw.get("level", 0.0))
        except (TypeError, ValueError):
            level = 0.0
        return {"topic": topic, "level": max(0.0, min(1.0, level))}
