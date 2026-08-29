"""统一 TTS 服务对外编排面契约存根（零实现，仅签名）。

源真理: server/services/tts_service.py
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。
契约版本: 2.0.0（MAJOR）

修订说明：原契约声明的 SpeechOrchestrator 全库无任何实现（幽灵契约）；统一 Qwen3 TTS
编排职能实际由 server/services/tts_service.py 的 TTSService 承担，本存根为其对外编排面
契约（路由与语音管线实际调用的公开方法，G4-B 契约对齐修订，实现为源真理）。

职责：非流式/流式/细粒度流式合成、情感合成、音色枚举、健康检查与生命周期管理；
统一 in-flight 信号量背压（wait 排队 / drop 丢弃）；Qwen3 未启用或 Provider 缺失时
三条合成入口统一抛 TTSServiceUnavailableError（router 层据此映射 HTTP 502）。
打断（interrupt）不在本服务公开面：由语音管线会话层（DualStreamSession）负责。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

__all__ = [
    "TTSService",
    "TTSServiceUnavailableError",
    "get_tts_service",
]


class TTSServiceUnavailableError(RuntimeError):
    """Qwen3 TTS 未启用或 Provider 缺失时合成入口抛出的明确异常（H10）。"""


class TTSService:
    """统一 TTS 服务，Qwen3 TTS 唯一合成入口。"""

    def __init__(
        self,
        mode: str = "remote",
        device: str = "cuda",
        remote_url: str = "http://127.0.0.1:5000",
        ref_audio_path: str = "",
        ref_text: str = "",
        speed: float = 1.0,
        cross_fade_duration: float = 0.15,
        effects_dir: str | Path | None = None,
        gateway_url: str | None = None,
        qwen3_enabled: bool = False,
        qwen3_provider: Any = None,
        emotion_instruction_enabled: bool = True,
    ) -> None:
        """构造统一 TTS 服务。

        Raises:
            ValueError: qwen3_enabled=True 但 qwen3_provider 为 None（组装错误，拒绝构造）。
        """
        ...

    @property
    def mode(self) -> str:
        """当前运行模式（remote/local）。"""
        ...

    async def initialize(self) -> None:
        """初始化服务（lifespan 启动时调用）。"""
        ...

    async def shutdown(self) -> None:
        """关闭服务（lifespan 关闭时调用）。"""
        ...

    async def synthesize(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        ref_audio: str | None = None,
        speed: float | None = None,
        cross_fade_duration: float | None = None,
        **kwargs: Any,
    ) -> bytes:
        """非流式合成：Qwen3 TTS 唯一合成路径，返回完整音频 bytes。受统一 in-flight 信号量约束。

        Raises:
            TTSServiceUnavailableError: Qwen3 未启用或 Provider 缺失（502）。
        """
        ...

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式合成：逐块 yield {text_segment, audio_data, chunk_index, is_final}。受统一 in-flight 信号量约束。

        Raises:
            TTSServiceUnavailableError: Qwen3 未启用或 Provider 缺失（502）。
        """
        ...

    async def split_text_streaming(
        self,
        token_stream: AsyncGenerator[str, None],
        char_threshold: int = 4,
    ) -> AsyncGenerator[str, None]:
        """细粒度流式分块器：「字数阈值 + 停顿标点」双重触发切片，压缩首包音频延迟。"""
        ...

    async def synthesize_stream_fine(
        self,
        token_stream: AsyncGenerator[str, None],
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        char_threshold: int = 3,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """细粒度流式合成：LLM token 流 → 切片 → 逐段 Qwen3 流式合成。受统一 in-flight 信号量约束。

        Raises:
            TTSServiceUnavailableError: Qwen3 未启用或 Provider 缺失（502）。
        """
        ...

    async def synthesize_with_emotions(
        self,
        text: str,
        **kwargs: Any,
    ) -> bytes:
        """带情感标注的非流式合成：情感由内嵌 tts_instruction 承载。"""
        ...

    async def synthesize_stream_with_emotions(
        self,
        text: str,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """带情感标注的流式合成：情感由内嵌 tts_instruction 承载。受统一 in-flight 信号量约束。

        Raises:
            TTSServiceUnavailableError: Qwen3 未启用或 Provider 缺失（502）。
        """
        ...

    async def get_voices(self) -> list[dict[str, Any]]:
        """列出可用音色：参考音频资产优先，保留 default 兜底。"""
        ...

    async def health_check(self) -> bool:
        """TTS 远端健康探测（GET {remote_url}/health，轻量连通性检查）。"""
        ...


def get_tts_service() -> TTSService:
    """获取全局唯一的 TTSService 单例，按配置惰性初始化。"""
    ...
