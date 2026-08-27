"""模块五 · MeetingTranscript —— 会议记录（防复读的关键）。

让每个 agent 发言时知道"前面谁说了什么"，避免复读，是"一起开会"而非"各说各的"。

设计基准：《CX-O 多 Agent 语音会议协调器》§8。

策略：
- 注入：``render_context()`` 生成最近 N 轮全量 + 更早摘要，防上下文爆炸。
- 沉淀：``roll_up()`` / ``summarize_older()`` 把会议要点压缩为记忆文本。
"""
from __future__ import annotations

from typing import Callable, List, Optional

from server.core.meeting.models import TranscriptEntry

# 摘要器类型：接收待摘要条目列表，返回压缩后的摘要文本
Summarizer = Callable[[List[TranscriptEntry]], str]

# older_summary 拼接后的总长上限（字符）；超长从头部截断，保留最新尾部
_MAX_SUMMARY_CHARS = 4000


def _default_summarizer(entries: List[TranscriptEntry]) -> str:
    """默认摘要器：逐条拼接说话者+内容（无 LLM 时兜底）。"""
    return "；".join(f"{e.speaker}: {e.text}" for e in entries)


class MeetingTranscript:
    """会议记录。

    用例：

    >>> transcript = MeetingTranscript(max_turns=20, summary_enabled=True)
    >>> transcript.append("user", "user", "周末去哪玩？")
    >>> context = transcript.render_context(max_turns=20)
    """

    def __init__(
        self,
        max_turns: int = 20,
        summary_enabled: bool = True,
        summarizer: Optional[Summarizer] = None,
    ):
        self.entries: List[TranscriptEntry] = []
        self.max_turns: int = int(max_turns)
        self.summary_enabled: bool = bool(summary_enabled)
        self._summarizer: Summarizer = summarizer or _default_summarizer
        # 已压缩的更早摘要（render_context 在此之上 + 最近 N 轮全量）
        self.older_summary: str = ""

    # ---------------------------------------------------------------- 写入
    def append(
        self,
        speaker: str,
        role: str,
        text: str,
        ts: Optional[str] = None,
    ) -> TranscriptEntry:
        """追加一条会议记录，返回该条目。"""
        entry = TranscriptEntry(speaker=speaker, role=role, text=text, ts=ts)
        self.entries.append(entry)
        return entry

    # ---------------------------------------------------------------- 读取
    def recent(self, max_turns: Optional[int] = None) -> List[TranscriptEntry]:
        """返回最近 ``max_turns`` 条全量记录（不含早期摘要条目）。"""
        turns = self.max_turns if max_turns is None else int(max_turns)
        if turns <= 0:
            return list(self.entries)
        return list(self.entries[-turns:])

    def older(self, max_turns: Optional[int] = None) -> List[TranscriptEntry]:
        """返回最近窗口之外更早的记录（供摘要压缩）。"""
        turns = self.max_turns if max_turns is None else int(max_turns)
        if turns <= 0:
            return []
        return list(self.entries[:-turns])

    def render_context(self, max_turns: int = 20) -> str:
        """渲染注入上下文的会议内容。

        最近 ``max_turns`` 轮全量 + 更早条目摘要（若 ``summary_enabled``）。
        """
        recent_entries = self.recent(max_turns)
        parts: List[str] = []

        if self.summary_enabled and self.older_summary:
            parts.append(self.older_summary)

        for e in recent_entries:
            parts.append(self._render_line(e))

        if not parts:
            return "（会议尚未开始）"
        return "\n".join(parts)

    def _render_line(self, entry: TranscriptEntry) -> str:
        """把单条转录按角色渲染为上下文文本。

        - 观众（audience）：speaker 形如 "audience:<用户名>" → 「观众 用户名: 内容」
        - 用户（user）：「用户: 内容」
        - Agent/其他：「<speaker>: 内容」
        """
        if entry.role == "audience":
            name = entry.speaker
            if name.startswith("audience:"):
                name = name[len("audience:"):]
            return f"观众 {name}: {entry.text}"
        if entry.role == "user":
            return f"用户: {entry.text}"
        return f"{entry.speaker}: {entry.text}"

    def summarize_older(
        self,
        max_turns: Optional[int] = None,
        summarizer: Optional[Summarizer] = None,
    ) -> str:
        """把最近窗口之外的更早记录压缩进 ``older_summary``。

        Returns:
            压缩后的摘要文本。
        """
        older_entries = self.older(max_turns)
        if not older_entries:
            return self.older_summary
        fn = summarizer or self._summarizer
        summary_text = fn(older_entries)
        # H3 修复：拼接保留既有 older_summary，不再整体覆盖——
        # 二次压缩时早期的历史要点得以延续，不会随新一轮摘要被永久丢失。
        prev = self.older_summary
        merged = (prev + "\n" + summary_text).strip()
        # 总长限制：超长从头部截断（保留最新拼接的尾部），防 older_summary 无界增长。
        if len(merged) > _MAX_SUMMARY_CHARS:
            merged = merged[-_MAX_SUMMARY_CHARS:]
        self.older_summary = merged
        # 已摘要进 older_summary 的旧条目从 entries 截掉，仅保留窗口内最近 turns 条，
        # 避免 older()/summarize_older() 反复对同一前缀重摘要、entries 无界增长。
        turns = int(max_turns if max_turns is not None else self.max_turns)
        if turns > 0:
            self.entries = self.entries[-turns:]
        return self.older_summary

    def roll_up(self, summarizer: Optional[Summarizer] = None) -> str:
        """把全部会议记录沉淀为一段记忆文本（会议结束调用）。

        H3 修复：``older_summary`` 中沉淀的早期历史也并入本次沉淀——
        以一条伪 entry 插入列表头部交给摘要器，避免整场记忆缺失早前内容。

        Returns:
            整场会议的要点摘要，供写回记忆。
        """
        fn = summarizer or self._summarizer
        entries = list(self.entries)
        if self.older_summary:
            entries.insert(
                0,
                TranscriptEntry(
                    speaker="会议早期摘要",
                    role="summary",
                    text=self.older_summary,
                ),
            )
        if not entries:
            return "（空会议）"
        return fn(entries)

    def __len__(self) -> int:
        """记录条目总数。"""
        return len(self.entries)