"""CX-O-Dream 入睡首步自动摘要（server/autonomy/dream/summarizer.py，Task 3）。

SleepAutoSummarizer 在入睡确认通过、正式进入梦境会话前，对当天未归档的对话
与短程记忆做结构化摘要并写入长期记忆库/日记，形成"入睡首步自动沉淀"。

职责（只读近端 + 只写长期记忆）：
- 提取未归档文本：经 ContextManager 读取近端活跃会话消息 + 经 MemoryManager
  读取短程记忆（short_term），合并为原始语料
- 调用注入的 LLM client（异步）生成结构化摘要；无 LLM 时降级为本地合并摘要
- 持久化：经 MemoryManager.write_memory_async 写入长期记忆（tags 含 自动摘要/日记）
- 防重复：should_summarize 依据来源是否为空、是否已归档（内容指纹匹配）判定
- 任何异常被捕获隔离并记日志，绝不阻断休眠主链路（异常吞掉后仍由调用方继续）

命名/返回结构对齐 dream 模块（collector/consolidator）与 public/interface_stub 风格：
- summarize(agent_id) -> Optional[str]（返回摘要或 None）
- should_summarize(source_text) -> bool

不持有主库写锁、不做任何相对路径文件访问（路径解析均由 MemoryManager 内部完成）。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from datetime import datetime
from typing import Any, Callable, List, Optional

from server.autonomy.dream.config import DreamConfig

logger = logging.getLogger(__name__)

# 摘要写入长期记忆的标签（对齐记忆库日记类检索习惯，兼容 '日记' 与 '#日记'）
_SUMMARY_TAGS = ("自动摘要", "日记")

# 默认摘要角色（排除 system/tool 的指令性内容）
_DEFAULT_EXCLUDED_ROLES = ("system", "tool")

# 本地降级摘要最大字符数
_LOCAL_SUMMARY_MAX_CHARS = 500


class SleepAutoSummarizer:
    """入睡首步自动摘要组件。

    Args:
        context_manager: 可选近端会话管理器（server/core/context/manager.py
            ContextManager）；None 时跳过会话语料采集
        memory_manager: 可选记忆管理器（server/core/memory/manager.py
            MemoryManager）；None 时跳过短程语料采集、且无法持久化（仅返回摘要）
        llm_client: 可选异步 LLM client（.chat(messages, stream=False) -> 有
            .content 或 str 的响应）；None 时降级为本地合并摘要
        parse_msgs: 可选解析回调（接收消息 dict 列表，返回未归档文本行列表）；
            None 时按默认规则过滤（排除 system/tool 角色、摘除空内容）
        config: DreamConfig；None 时使用全默认
    """

    def __init__(
        self,
        context_manager=None,
        memory_manager=None,
        llm_client=None,
        parse_msgs: Optional[Callable[[List[Dict]], List[str]]] = None,
        config: Optional[DreamConfig] = None,
    ):
        self._context_manager = context_manager
        self._memory_manager = memory_manager
        self._llm_client = llm_client
        self._parse_msgs = parse_msgs
        self._config = config or DreamConfig()
        # 防重复记录：上次摘要内容的指纹（内容级去重，Optional dedup）
        self._last_fingerprint: Optional[str] = None
        self._summarized_at: Optional[str] = None

    # -------------------------------------------------------------- 主入口
    async def summarize(self, agent_id: str = "default") -> Optional[str]:
        """执行入睡首步自动摘要：提取→生成→持久化（异常隔离，绝不阻断调用方）。

        依据来源是否为空 / 是否已归档（should_summarize）决定是否执行；任一步骤
        异常被捕获隔离并记日志，返回 None 而非上抛，保证休眠主链路不被阻断。

        Args:
            agent_id: Agent ID

        Returns:
            生成的摘要文本；无需执行或异常时返回 None
        """
        try:
            texts = await self._extract_source_text(agent_id)
            source_text = self._join_texts(texts)
            if not self.should_summarize(source_text):
                logger.info(
                    "入睡自动摘要跳过（来源为空或已归档）: agent=%s, texts=%s",
                    agent_id,
                    len(texts),
                )
                return None

            # 生成摘要：优先 LLM，实在不可用时降级为本地合并
            summary = await self._generate_summary_text(source_text, agent_id)
            if not summary:
                logger.info("入睡自动摘要无可用内容，未持久化: agent=%s", agent_id)
                return None

            await self._persist(summary, agent_id)
            self._last_fingerprint = self._fingerprint(source_text)
            self._summarized_at = datetime.now().isoformat()
            logger.info(
                "入睡自动摘要完成并入库: agent=%s, summary_chars=%s",
                agent_id,
                len(summary),
            )
            return summary
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("入睡自动摘要异常（已隔离，不阻断休眠主链路）: agent=%s, %s", agent_id, e)
            return None

    # -------------------------------------------------------------- 判定
    def should_summarize(self, source_text: str) -> bool:
        """依据来源是否为空或是否已归档判定是否需要执行摘要。

        - 来源为空（无未归档文本）→ False
        - 来源文本指纹与上次已归档指纹一致 → False（防重复，可选哈希记录）
        - 否则 → True
        """
        if not source_text or not source_text.strip():
            return False
        if self._last_fingerprint is not None:
            if self._fingerprint(source_text) == self._last_fingerprint:
                return False
        return True

    # -------------------------------------------------------------- 语料采集
    async def _extract_source_text(self, agent_id: str) -> List[str]:
        """采集未归档语料：近端会话消息 + 短程记忆（各失败降级为空，不互相阻断）。"""
        texts: List[str] = []
        if self._context_manager is not None:
            try:
                texts.extend(await self._recent_session_texts(agent_id))
            except Exception as e:
                logger.warning("入睡自动摘要：会话语料采集失败（降级为空）: %s", e)
        if self._memory_manager is not None:
            try:
                texts.extend(await self._recent_memory_texts(agent_id))
            except Exception as e:
                logger.warning("入睡自动摘要：短程记忆采集失败（降级为空）: %s", e)
        return texts

    async def _recent_session_texts(self, agent_id: str) -> List[str]:
        """读取近端活跃会话消息文本（最多 3 个会话 × 各 100 条，经 parse_msgs 解析）。"""
        rows = self._context_manager.get_sessions(
            workspace_id="default", limit=3, active_only=True
        )
        result = inspect.isawaitable(rows)
        if result:
            rows = await result
        messages: List[Dict[str, Any]] = []
        for session in rows or []:
            sid = self._session_id(session)
            if not sid:
                continue
            msgs = self._context_manager.get_recent_messages(sid, limit=100)
            if inspect.isawaitable(msgs):
                msgs = await msgs
            messages.extend(msgs or [])
        return self._parse_messages(messages)

    async def _recent_memory_texts(self, agent_id: str) -> List[str]:
        """读取短程记忆（short_term）内容作为未归档语料。"""
        rows = self._memory_manager.search_memories_async(
            query=None,
            memory_type="short_term",
            limit=50,
            include_deleted=False,
            agent_id=agent_id,
        )
        if inspect.isawaitable(rows):
            rows = await rows
        return [self._memory_content(m) for m in rows or [] if self._memory_content(m)]

    # -------------------------------------------------------------- 解析
    def _parse_messages(self, messages: List[Dict]) -> List[str]:
        """解析消息列表为未归档文本行（parse_msgs 注入优先，否则走默认过滤）。"""
        if self._parse_msgs is not None:
            try:
                parsed = self._parse_msgs(messages)
                return [str(p).strip() for p in parsed or [] if str(p).strip()]
            except Exception as e:
                logger.warning("入睡自动摘要：parse_msgs 回调异常（回退默认过滤）: %s", e)
        lines = []
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") in _DEFAULT_EXCLUDED_ROLES:
                continue
            content = (msg.get("content") or "").strip()
            if content:
                lines.append(content)
        return lines

    # -------------------------------------------------------------- 生成
    async def _generate_summary_text(self, source_text: str, agent_id: str) -> Optional[str]:
        """生成结构化摘要：优先 LLM client，不可用时降级为本地合并。

        返回摘要文本；生成失败返回 None（由调用方决定是否继续）。
        """
        llm_summary = await self._generate_with_llm(source_text)
        if llm_summary:
            return llm_summary
        logger.info("入睡自动摘要：LLM 不可用或失败，降级为本地合并摘要: agent=%s", agent_id)
        return self._local_summary(source_text)

    async def _generate_with_llm(self, source_text: str) -> Optional[str]:
        """调用注入的 LLM client 生成结构化摘要；无 client / 调用失败返回 None。"""
        if self._llm_client is None:
            return None
        prompt = self._build_summary_prompt(source_text)
        try:
            response = await self._llm_client.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是 CX-O 的睡前记忆整理助手。基于用户近期未归档的对话与短程记忆，"
                            "生成一段简洁、结构化的第一人称日间小结（摘要），涵盖主要事件、情绪变化"
                            "与可沉淀的信息点。以自然的中文段落输出，不要输出 JSON，不要多余解释。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                temperature=0.6,
            )
        except Exception as e:
            logger.warning("入睡自动摘要：LLM 调用失败（降级为本地摘要）: %s", e)
            return None
        return self._response_content(response)

    @staticmethod
    def _build_summary_prompt(source_text: str) -> str:
        """构造摘要输入提示词（对语料做长度截断防超大 prompt）。"""
        truncated = source_text[:6000]
        return f"以下是今天尚未归档的对话与短程记忆原始内容：\n\n{truncated}"

    @staticmethod
    def _response_content(response: Any) -> Optional[str]:
        """从 LLM 响应提取文本：支持带 .content 的对象或纯字符串。"""
        if response is None:
            return None
        if isinstance(response, str):
            return response.strip() or None
        content = getattr(response, "content", None) or getattr(response, "text", None)
        if isinstance(content, str):
            return content.strip() or None
        return None

    @staticmethod
    def _local_summary(source_text: str, max_chars: int = _LOCAL_SUMMARY_MAX_CHARS) -> str:
        """本地降级摘要：将合并语料压缩为前置摘要文本（无 LLM 时的兜底）。"""
        text = "\n".join(line.strip() for line in source_text.splitlines() if line.strip())
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "…"

    # -------------------------------------------------------------- 持久化
    async def _persist(self, summary: str, agent_id: str) -> bool:
        """写入长期记忆库/日记（tags 含 自动摘要/日记），失败仅记日志不阻断。"""
        if self._memory_manager is None:
            logger.info("入睡自动摘要：无 memory_manager，摘要仅返回未入库: agent=%s", agent_id)
            return False
        metadata = {
            "source": "sleep_auto_summary",
            "kind": "日报/摘要",
            "summarized_at": datetime.now().isoformat(),
        }
        try:
            memory_id = await self._memory_manager.write_memory_async(
                content=summary,
                memory_type="long_term",
                importance=4,
                tags=list(_SUMMARY_TAGS),
                metadata=metadata,
                agent_id=agent_id,
            )
            logger.info("入睡自动摘要已写入长期记忆: agent=%s, memory_id=%s", agent_id, memory_id)
            return True
        except Exception as e:
            logger.warning("入睡自动摘要：长期记忆写入失败（已隔离，不阻断）: %s", e)
            return False

    # -------------------------------------------------------------- 内部
    @staticmethod
    def _join_texts(texts: List[str]) -> str:
        """合并语料文本列表为单字符串。"""
        return "\n".join(t for t in texts or [] if t)

    @staticmethod
    def _fingerprint(text: str) -> str:
        """内容指纹（去重用，Optional dedup）。"""
        return hashlib.md5((text or "").encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _session_id(session: Any) -> str:
        if isinstance(session, dict):
            return str(session.get("id") or "")
        return str(getattr(session, "id", "") or "")

    @staticmethod
    def _memory_content(mem: Any) -> str:
        if isinstance(mem, dict):
            return str(mem.get("content") or "").strip()
        return str(getattr(mem, "content", "") or "").strip()