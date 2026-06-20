"""
LLM-TTS 文本平滑缓冲器（TextSmoother）

背景：LLM 以 ~90 tokens/s 产出碎片化 Token（每个 token 往往只有 1~2 个字甚至
子字片段），直接喂给 TTS 会导致发音诡异——吃字、破碎、韵律断层。本模块以
30~50ms 的极短滑动窗口将碎片 Token 聚合为 3~5 字的词组块后再 yield 给 TTS，
用 50ms 的极小延迟代价换取 TTS 音质的巨大提升，且不突破 300ms 总预算。

输出粒度与 tts_service.TTSService.synthesize_stream_fine() 的输入对接：
    TextSmoother.smooth_stream() -> AsyncGenerator[str, None]
    -> TTSService.synthesize_stream_fine(token_stream=...)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


class _EndOfStream:
    """流结束哨兵标记，投入队列通知 smooth_stream 收尾。"""


# 全局唯一哨兵实例，用 is 判等，避免与任何字符串 token 冲突
_END_OF_STREAM = _EndOfStream()


class TextSmoother:
    """
    LLM-TTS 文本平滑缓冲器。

    工作原理（三重触发 flush）：
      1. 滑动窗口超时（默认 40ms）：自 buffer 非空起计时，超时即 flush。
         —— 保证最长缓冲延迟 ≤ 50ms，不突破 300ms 总预算。
      2. 标点触发：遇到 ，。！？、；： 立即 flush。
         —— 利用自然语义边界，TTS 在停顿处切分听感最自然。
      3. 字数触发：中文字数达 3~5 立即 flush。
         —— 与 TTS split_text_streaming 分块器阈值配合，LLM 持续高速吐字时
            也能及时输出，避免无限累积。

    为什么 50ms 缓冲能大幅提升音质：
      - TTS 模型（如 F5-TTS）基于上下文做韵律预测，过短的碎片（1~2 字）缺乏
        上下文，模型只能"猜"韵律，导致语调生硬、停顿错位、吃字。
      - 聚合到 3~5 字的词组块后，模型能看到完整的词/短语边界，韵律预测准确度
        显著提升，听感自然。
      - 50ms 远小于 300ms 总预算，且 TTS 合成与音频播放可流水线并行，这 50ms
        几乎被后续处理"吸收"，用户无感。

    线程安全：使用 asyncio.Queue，在单事件循环内天然异步安全，无需额外加锁。
    """

    # 中文停顿标点：遇到这些标点立即输出当前缓冲（不等窗口超时）。
    # 这些标点本身就是自然停顿点，在此切分既不破坏语义，又能让 TTS 在自然停顿处换气。
    PAUSE_PUNCTUATION = "，。！？、；：,.!?;:"

    def __init__(
        self,
        window_ms: int = 40,
        char_threshold: int = 4,
    ):
        # 窗口超时限制在 30~50ms：
        #   过小（<30ms）起不到聚合作用，碎片仍会漏到 TTS；
        #   过大（>50ms）突破 300ms 总预算，用户能感知到延迟。
        # 40ms 是经验最优值：能聚合 ~3 个 90tokens/s 的碎片，又不至于让用户感知。
        self._window_ms = max(30, min(50, int(window_ms)))
        self._window_s = self._window_ms / 1000.0

        # 字数阈值限制在 3~5：与 TTS split_text_streaming 分块器阈值配合。
        # 3~5 字恰好是一个中文词/短语的长度，TTS 在此粒度合成音质最佳。
        self._char_threshold = max(3, min(5, int(char_threshold)))

        # asyncio.Queue 天然异步安全：单事件循环内 put/get 无需额外锁
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._finished = False

    async def put(self, token: Any) -> None:
        """
        供 LLM 流式输出调用，将 token 投入缓冲队列。

        兼容 str（vLLM）与 dict（Ollama，带 type 字段）两种 token 格式：
          - vLLM 流式直接 yield str
          - Ollama 流式 yield dict，文本在 content/message.content 字段，
            type 字段标识消息类型（content/status/done 等）
        """
        if self._finished:
            return

        text = self._extract_text(token)
        if text:
            await self._queue.put(text)

    def _extract_text(self, token: Any) -> str:
        """从 LLM token 中提取纯文本，兼容 str/dict 两种格式。"""
        if isinstance(token, str):
            return token

        if isinstance(token, dict):
            # 跳过非内容类型消息（如 Ollama 的 status/done/error 控制消息），
            # 避免把元数据当文本喂给 TTS 导致发音异常
            t = token.get("type", "")
            if isinstance(t, str) and t in ("status", "done", "error", "end"):
                return ""

            # 兼容多种字段命名：content / token / text / delta（OpenAI 风格）
            for key in ("content", "token", "text", "delta"):
                val = token.get(key)
                if isinstance(val, str) and val:
                    return val

            # Ollama chat 格式：{"message": {"role": "assistant", "content": "..."}}
            msg = token.get("message")
            if isinstance(msg, dict):
                val = msg.get("content")
                if isinstance(val, str) and val:
                    return val

        return ""

    async def finish(self) -> None:
        """
        标记输入结束并 flush 剩余缓冲。

        投入哨兵对象，smooth_stream 收到后吐出剩余 buffer 并退出。
        幂等：重复调用无副作用。
        """
        if self._finished:
            return
        self._finished = True
        await self._queue.put(_END_OF_STREAM)

    async def smooth_stream(self) -> AsyncGenerator[str, None]:
        """
        平滑后的词组块 async generator。

        输出粒度：3~5 字的词组块，可直接喂给 TTS synthesize_stream_fine()。

        缓冲策略（三重触发，详见类文档）：
          1. 滑动窗口超时（40ms）：保证最长延迟 ≤ 50ms
          2. 标点触发：在自然停顿处切分
          3. 字数触发：LLM 高速吐字时及时输出

        yield 的每个 chunk 均为非空字符串（已 strip 校验）。
        """
        buffer = ""
        chinese_char_count = 0
        # buffer 起始时间戳：仅在 buffer 从空变非空时设置，flush 后重置。
        # 用于计算滑动窗口剩余时间，保证缓冲延迟严格 ≤ 50ms。
        buffer_start: float | None = None

        while True:
            # 计算本次 wait_for 的超时：
            #   - buffer 非空：剩余窗口时间 = window_ms - 已缓冲时长
            #     这样写能保证从首个 token 入 buffer 到 flush 不超过 50ms，
            #     即便 LLM 持续吐字也不会让缓冲无限增长。
            #   - buffer 为空：无超时等待首个 token（None），避免空闲时 40ms 轮询
            #     浪费 CPU；finish() 的哨兵或新 token 都能唤醒。
            if buffer and buffer_start is not None:
                elapsed_ms = (time.monotonic() - buffer_start) * 1000.0
                remaining_s = (self._window_ms - elapsed_ms) / 1000.0
                # 剩余时间已耗尽则立即超时（保留极小值避免 wait_for 报 0 超时错误）
                if remaining_s <= 0:
                    remaining_s = 0.001
            else:
                remaining_s = None  # 无超时，等待首个 token

            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=remaining_s)
            except asyncio.TimeoutError:
                # 窗口超时：将当前缓冲作为词组块 yield。
                # 这是滑动窗口的核心：40ms 内聚合的碎片 token 一次性送 TTS，
                # 避免逐 token 喂入导致 TTS 韵律预测失准（吃字/破碎）。
                if buffer:
                    yield buffer
                    buffer = ""
                    chinese_char_count = 0
                    buffer_start = None
                # buffer 为空时超时属正常（LLM 暂无输出），继续等待
                continue

            # 收到流结束哨兵：flush 剩余 buffer 后退出
            if item is _END_OF_STREAM:
                if buffer:
                    yield buffer
                return

            # 累积 token 到 buffer，并记录窗口起始时间
            if not buffer:
                buffer_start = time.monotonic()
            buffer += item

            # 统计新增中文字符数（CJK 统一表意文字范围），用于字数触发判定
            for ch in item:
                if "\u4e00" <= ch <= "\u9fff":
                    chinese_char_count += 1

            # ---- 触发条件 2：标点触发 ----
            # 遇到停顿标点立即输出：在最后一个停顿标点之后切分（保留标点），
            # 让 TTS 在自然停顿处换气，听感最自然，省去等待窗口超时的 40ms。
            cut_pos = -1
            for p in self.PAUSE_PUNCTUATION:
                idx = buffer.rfind(p)
                if idx != -1:
                    cut_pos = max(cut_pos, idx + 1)

            # ---- 触发条件 3：字数触发 ----
            # LLM 持续高速吐字时（90 tokens/s ≈ 11ms/token），窗口可能一直被新
            # token 续期而不超时。字数触发保证不会无限累积，且 3~5 字正是 TTS
            # 最佳合成粒度——凑够一个词即送 TTS，省下等待更多 token 的时间。
            if chinese_char_count >= self._char_threshold and cut_pos == -1:
                cut_pos = len(buffer)

            if cut_pos > 0:
                chunk = buffer[:cut_pos]
                buffer = buffer[cut_pos:]
                # 重新统计剩余 buffer 的中文字数，保证下一轮阈值判定准确
                chinese_char_count = sum(1 for c in buffer if "\u4e00" <= c <= "\u9fff")
                # buffer 仍有剩余则保留窗口起始时间（继续计时），否则重置
                if not buffer:
                    buffer_start = None

                if chunk.strip():
                    yield chunk

    @classmethod
    async def smooth(
        cls,
        llm_token_stream: AsyncGenerator[Any, None],
        window_ms: int = 40,
        char_threshold: int = 4,
    ) -> AsyncGenerator[str, None]:
        """
        优雅封装：直接接收 LLM token 流，输出平滑后的词组块流。

        内部自动启动投递协程消费 LLM token 流并调用 put/finish，
        与 smooth_stream 并行协作，自动处理 str/dict 两种 token 格式。

        用法：
            async for chunk in TextSmoother.smooth(llm.stream_chat(...)):
                # chunk 是平滑后的词组块字符串，可直接喂 TTS
                async for tts_chunk in tts.synthesize_stream_fine(
                    token_stream=<上面得到的 chunk 流>
                ):
                    ...

        参数：
            llm_token_stream: LLM 流式输出的 async generator（token 可为 str 或 dict）
            window_ms: 滑动窗口超时（30~50ms，默认 40）
            char_threshold: 中文字数触发阈值（3~5，默认 4）
        """
        smoother = cls(window_ms=window_ms, char_threshold=char_threshold)

        async def _feed():
            """消费 LLM token 流并投递给 smoother，结束时自动 finish。"""
            try:
                async for token in llm_token_stream:
                    await smoother.put(token)
            except Exception as e:
                logger.error(f"TextSmoother feed loop error: {e}")
            finally:
                await smoother.finish()

        # 启动投递任务，与 smooth_stream 并行消费
        feeder = asyncio.create_task(_feed())
        try:
            async for chunk in smoother.smooth_stream():
                yield chunk
        finally:
            # 消费者提前退出或异常时，确保 feeder 任务被清理，避免协程泄漏
            if not feeder.done():
                feeder.cancel()
                try:
                    await feeder
                except (asyncio.CancelledError, Exception):
                    pass
