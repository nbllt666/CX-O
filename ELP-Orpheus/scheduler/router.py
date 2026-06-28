"""
语义感知分块 Router
===================
ELP-Orpheus FT 引擎的中央调度器组件。

接收 LLM（Gemma 4 E4B）流式输出的文本/token，按语义切分成 Chunk 再喂给
Orpheus TTS 引擎（经 ZeroMQ IPC 传递给 FasterTransformer 后端）。

切分规则（兼顾自然度与速度）:
    - 遇到中文标点（，。！？）立即切分 → 保证语义落在自然停顿处，TTS 合成韵律自然
    - 累积达到 max_chunk_tokens（默认 20）仍未遇标点 → 强制切分 → 控制延迟，
      避免 LLM 长时间不输出标点时 TTS 一直空等

这样既能按自然停顿切分（提升自然度），又能用最大长度兜底（控制首包延迟），
二者结合使 TTS 可在 LLM 仍在生成时即开工合成，显著降低端到端延迟。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol


class TokenizerLike(Protocol):
    """Tokenizer 协议：split_tokens 仅依赖 decode 方法判定标点边界。

    兼容 HuggingFace transformers 的 tokenizer（其 decode 接受 list[int]），
    测试时可用任意实现了 decode 的对象（mock）替代，无需引入外部依赖。
    """

    def decode(self, token_ids: list[int]) -> str: ...


class SemanticRouter:
    """语义感知分块 Router：按标点或最大长度切分 LLM 输出文本。"""

    def __init__(
        self,
        max_chunk_tokens: int = 20,
        split_punctuation: str = "，。！？",
    ) -> None:
        self._max_chunk_tokens: int = max_chunk_tokens
        # 用 frozenset 做 O(1) 标点命中判定
        self._split_punctuation_set: frozenset[str] = frozenset(split_punctuation)

    def split_text(self, text: str) -> list[str]:
        """对完整文本进行切分，返回 Chunk 列表。

        遍历每个字符：
            - 遇到切分标点 → 当前 buffer（含标点）作为一个 Chunk 输出
            - buffer 长度达到 max_chunk_tokens → 强制切分（兜底防延迟）
            - 文本结束 → 剩余非空 buffer 作为最后一个 Chunk
        """
        if not text:
            return []

        chunks: list[str] = []
        buffer: list[str] = []

        for char in text:
            buffer.append(char)
            # 优先按标点切分：保证语义落在自然停顿处，TTS 韵律更自然
            if char in self._split_punctuation_set:
                chunks.append("".join(buffer))
                buffer = []
                continue
            # 标点兜底：达到最大长度强制切分，避免无标点长串拖延首包
            if len(buffer) >= self._max_chunk_tokens:
                chunks.append("".join(buffer))
                buffer = []

        # 收尾：剩余内容作为最后一个 Chunk
        if buffer:
            chunks.append("".join(buffer))

        return chunks

    async def split_stream(
        self, token_stream: AsyncIterator[str]
    ) -> AsyncIterator[str]:
        """对接 LLM 流式输出，async generator 逐块 yield Chunk。

        逻辑：
            1. 累积 LLM 流式 token 到 buffer
            2. 遇到 split_punctuation 中的标点 → 立即切分 yield 当前 buffer（含标点）
            3. buffer 达到 max_chunk_tokens 长度仍未遇标点 → 强制切分 yield
            4. 流结束时若 buffer 非空 → yield 剩余

        实时切分（不等整句）能让 TTS 在 LLM 还在生成时就开工合成，
        兼顾自然度（标点处停顿）与速度（最大长度兜底防阻塞）。
        """
        buffer: list[str] = []

        async for token_text in token_stream:
            # LLM 一次可能吐出多字符（一个 token 解码后可能是多字），逐字符判定边界
            for char in token_text:
                buffer.append(char)
                # 标点即切：自然停顿处立即交付给 TTS，兼顾自然度
                if char in self._split_punctuation_set:
                    yield "".join(buffer)
                    buffer = []
                    continue
                # 长度兜底：防止无标点长串阻塞，控制首包延迟
                if len(buffer) >= self._max_chunk_tokens:
                    yield "".join(buffer)
                    buffer = []

        # 流结束，刷出剩余 buffer
        if buffer:
            yield "".join(buffer)

    def split_tokens(
        self, tokens: list[int], tokenizer: Any
    ) -> list[list[int]]:
        """对 token id 列表进行切分（基于 tokenizer 解码判定标点边界）。

        用于直接传递 Token ID 数组给 FT 引擎（经 ZeroMQ IPC）。

        判定方式：每追加一个 token 后解码当前 buffer，若解码文本以切分标点结尾，
        则视为语义边界并切分；否则当 buffer 长度达到 max_chunk_tokens 时强制切分。

        注：每次解码整个 buffer 是 O(n²)，但 chunk 规模小（≤ max_chunk_tokens），
        开销可忽略；同时整段解码能正确处理 BPE 跨 token 合并，避免在合并字符
        中间误切，保证 token 数组本身的完整性（FT 引擎要求连续 token id）。
        """
        if not tokens:
            return []

        chunks: list[list[int]] = []
        buffer: list[int] = []

        for token_id in tokens:
            buffer.append(token_id)
            # 解码当前 buffer 文本，依据末字符判定是否到达标点边界
            decoded = tokenizer.decode(buffer)
            if decoded and decoded[-1] in self._split_punctuation_set:
                chunks.append(buffer[:])
                buffer = []
                continue
            # 长度兜底：达到上限强制切分
            if len(buffer) >= self._max_chunk_tokens:
                chunks.append(buffer[:])
                buffer = []

        if buffer:
            chunks.append(buffer[:])

        return chunks
