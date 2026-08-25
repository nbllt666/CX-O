"""模块六 · AudioRouter —— 音频路由。

管理多路 TTS 输出，避免声音打架，让用户分清"谁在说"。

设计基准：《CX-O 多 Agent 语音会议协调器》§9。

- 串行发言（默认）：仅令牌持有者的 TTS 才能出声（`route` 门控）。
- 音色区分：每个 agent 用不同音色（由 AgentMember.voice 承载）。
- 附和低音量：某 agent 说话时，其他可轻声附和（不占令牌，`mix_backchannel`）。
- 空间音频：进阶，未在本实现落地。
"""
from __future__ import annotations

import logging
from typing import AsyncIterable, Optional

logger = logging.getLogger(__name__)


class AudioRouter:
    """音频路由。

    Args:
        backchannel_enabled: 是否允许"低音量附和"（默认关）。
        backchannel_volume: 附和音量系数（主发言的百分之几，默认 0.2）。
    """

    def __init__(
        self,
        backchannel_enabled: bool = False,
        backchannel_volume: float = 0.2,
    ):
        self.backchannel_enabled = bool(backchannel_enabled)
        self.backchannel_volume = float(backchannel_volume)

    # ---------------------------------------------------------------- 门控
    def is_allowed(self, agent_id: str, room) -> bool:
        """判定某 agent 当前是否被允许出声（仅令牌持有者放行）。"""
        holder = room.token.who_holds()
        return holder is not None and holder == agent_id

    async def route(
        self,
        agent_id: str,
        tts_stream: AsyncIterable,
        room,
    ) -> Optional[AsyncIterable]:
        """路由单路 TTS 流：仅令牌持有者放行，否则返回 None（静音）。

        Returns:
            原样迭代器（若放行），或 None（未持牌 → 静音）。

        使用：

        >>> stream = await router.route("A", chunks, room)
        >>> if stream is None:
        >>>     return  # 静音，非令牌持有者
        >>> async for chunk in stream:
        >>>     yield chunk
        """
        holder = room.token.who_holds()
        if holder is None or holder != agent_id:
            logger.info("AudioRouter 静音 %s（当前持牌=%s）", agent_id, holder)
            return None
        return self._passthrough(tts_stream)

    async def _passthrough(self, tts_stream: AsyncIterable) -> AsyncIterable:
        """直通迭代器：逐块透传（可在此扩展混音逻辑）。"""
        async for chunk in tts_stream:
            yield chunk

    # ---------------------------------------------------------------- 附和
    def mix_backchannel(self, chunk, volume: Optional[float] = None) -> object:
        """把主发言块与低音量附和混合。

        阻塞式示例（真实混音需按音频格式实现，此处返回原块以示契约）。
        音量取 ``backchannel_volume`` 与显式 ``volume`` 的较大配置。
        """
        v = self.backchannel_volume if volume is None else float(volume)
        if not self.backchannel_enabled or v <= 0:
            return chunk
        # 真实实现：将 chunk 乘以 v 混入附和轨道。此处保持透传并记录。
        logger.debug("附和音量系数 v=%.2f", v)
        return chunk
