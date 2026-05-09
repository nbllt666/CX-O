"""
打断管理器
统一管理 ASR 打断和 Agent 打断
"""
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class InterruptManager:
    _instance = None

    def __init__(self):
        self._asr_interrupt: Any = None
        self._agent_interrupt: Any = None
        self._interrupt_callback: Optional[Callable] = None

    @classmethod
    def get_instance(cls) -> "InterruptManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_asr_interrupt(self, asr_interrupt: Any):
        self._asr_interrupt = asr_interrupt

    def set_agent_interrupt(self, agent_interrupt: Any):
        self._agent_interrupt = agent_interrupt

    def set_interrupt_callback(self, callback: Callable):
        self._interrupt_callback = callback

    async def handle_interrupt(self, source: str, text: str, **kwargs):
        logger.info(f"Interrupt from {source}: {text}")

        if self._interrupt_callback:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(self._interrupt_callback):
                    await self._interrupt_callback(source, text, **kwargs)
                else:
                    self._interrupt_callback(source, text, **kwargs)
            except Exception as e:
                logger.error(f"Interrupt callback error: {e}")


def get_interrupt_manager() -> InterruptManager:
    return InterruptManager.get_instance()
