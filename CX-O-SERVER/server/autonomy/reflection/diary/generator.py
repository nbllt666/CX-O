"""CX-O-Autonomy 反思层·日记生成器（P1-T7）。

DiaryGenerator 基于当日活动日志（daily_log，可来自 AuditStore.list 返回的
items，每条含 timestamp/action/target/result/trigger_reason 等字段）调用 LLM
生成第一人称日记，并把日记写入长期记忆（memory_actions.write_memory）。

行为语义：
- 组装 system prompt：第一人称角色（人设 persona.system_prompt / description）+
  指令"以第一人称写一篇简洁的今日日记，回顾今天的经历、感受与想法，200字以内，
  中文"；user 消息为日期 + 活动日志
- 调 llm_client.chat 获取日记文本（LLMResponse.content）；LLM 调用失败
  （client 抛错 / LLMResponse.error / 内容为空）返回
  {"diary": "", "memory_id": None, "error": ...}，不向上冒泡
- 写记忆：memory_actions.write_memory(content=日记文本, tags=["#日记", "#经历"],
  type="long_term", permanent=True, importance=5)
- 返回 {"diary": 日记文本, "memory_id": 记忆ID}；记忆写入失败（write_memory
  返回错误结构或抛异常）时 memory_id 为 None 并附带 error 字段，同样不冒泡

本模块无文件 IO，禁止相对路径。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 日记记忆写入参数（对齐 memory_actions.write_memory 语义）
_DIARY_TAGS: List[str] = ["#日记", "#经历"]
_DIARY_TYPE = "long_term"
_DIARY_PERMANENT = True
_DIARY_IMPORTANCE = 5

# LLM 调用失败标记（写入返回 dict 的 error 字段）
_LLM_ERROR = "llm_error"


class DiaryGenerator:
    """LLM 日记生成器：把当日活动日志写成第一人称日记并写入长期记忆。

    Args:
        llm_client: LLMClient 实例（chat 返回 LLMResponse，取 .content 作为日记文本）
        memory_actions: MemoryActions 实例（提供 write_memory）
        persona: 人设字典，可取 persona.system_prompt 或 persona.description
    """

    def __init__(
        self,
        llm_client: Any,
        memory_actions: Any,
        persona: Optional[Dict[str, Any]] = None,
    ) -> None:
        """初始化日记生成器：保存 LLM 客户端、记忆行动与人设。"""
        self.llm_client: Any = llm_client
        self.memory_actions: Any = memory_actions
        self.persona: Dict[str, Any] = persona or {}

    async def generate_diary(
        self,
        daily_log: List[Dict[str, Any]],
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成一篇今日日记并写入长期记忆。

        Args:
            daily_log: 当日活动条目列表，每条含 timestamp/action/target/result/
                trigger_reason 等字段（可来自 AuditStore.list 的 items）
            date: 日期字符串；缺省时以 "今天" 标识

        Returns:
            成功（含记忆写入成功）返回 {"diary": 日记文本, "memory_id": 记忆ID}；
            LLM 调用失败返回 {"diary": "", "memory_id": None, "error": <原因>}；
            记忆写入失败返回 {"diary": 日记文本, "memory_id": None, "error": <原因>}；
            均不向上冒泡。
        """
        messages = self._build_messages(daily_log, date)
        diary_text = await self._fetch_diary_text(messages)
        if not diary_text:
            return {"diary": "", "memory_id": None, "error": _LLM_ERROR}

        memory_result = await self._write_memory(diary_text)
        if isinstance(memory_result, dict):
            # memory_actions 失败返回 {'error': ..., 'memory_id': None}，不冒泡
            return {
                "diary": diary_text,
                "memory_id": None,
                "error": memory_result.get("error") or "memory_write_failed",
            }
        return {"diary": diary_text, "memory_id": memory_result}

    # ================================================================ 提示词组装
    def _build_messages(
        self, daily_log: List[Dict[str, Any]], date: Optional[str]
    ) -> List[Dict[str, str]]:
        """组装 [system, user] 消息列表。"""
        return [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_content(daily_log, date)},
        ]

    def _build_system_prompt(self) -> str:
        """组装 system prompt：第一人称角色（人设）+ 日记写作指令。"""
        lines: List[str] = []
        persona_text = self.persona.get("system_prompt") or self.persona.get("description")
        if persona_text:
            lines.append(f"【人设】{persona_text}")
            lines.append("")
        lines.append("以第一人称写一篇简洁的今日日记，回顾今天的经历、感受与想法，"
                     "200字以内，中文。")
        return "\n".join(lines)

    def _build_user_content(
        self, daily_log: List[Dict[str, Any]], date: Optional[str]
    ) -> str:
        """组装 user 消息：日期 + 活动日志。"""
        label = date or "今天"
        body = json.dumps(daily_log, ensure_ascii=False, indent=2)
        return f"日期：{label}\n今日活动：\n{body}"

    # ================================================================ LLM 调用
    async def _fetch_diary_text(self, messages: List[Dict[str, str]]) -> str:
        """调 llm_client.chat 获取日记文本；失败返回空字符串（不冒泡）。"""
        try:
            response = await self.llm_client.chat(messages=messages)
        except Exception as e:
            logger.error("日记生成 LLM 调用失败: %s", e)
            return ""
        if response.error:
            logger.error("日记生成 LLM 返回错误: %s", response.error)
            return ""
        return (response.content or "").strip()

    # ================================================================ 记忆写入
    async def _write_memory(self, diary_text: str) -> Any:
        """写入日记到长期记忆；返回 memory_id（str）或错误结构（不冒泡）。"""
        try:
            return await self.memory_actions.write_memory(
                content=diary_text,
                tags=list(_DIARY_TAGS),
                type=_DIARY_TYPE,
                permanent=_DIARY_PERMANENT,
                importance=_DIARY_IMPORTANCE,
            )
        except Exception as e:
            logger.error("日记记忆写入失败: %s", e)
            return {"error": str(e), "memory_id": None}
