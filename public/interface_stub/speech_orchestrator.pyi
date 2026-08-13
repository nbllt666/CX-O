"""统一 Qwen3 TTS 语音编排接口契约存根（零实现，仅签名）。

源真理: public/schema/speech_synthesis_request.schema.json + qwen3_tts_error_codes.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。

职责：将普通 REST、WebSocket 双流、直播音频与工作站试听收敛到统一 Qwen3 编排入口。
保留打断、取消、静音过滤、音频块顺序与前端播放协议。
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from qwen3_tts_provider import AudioChunk, SynthesisRequest, SynthesisResponse
from ref_audio_store import RefAudioAsset
from emotion_instruction_service import EmotionInstruction

__all__ = [
    "SpeechOrchestrator",
    "OrchestratorOptions",
]


class OrchestratorOptions:
    """编排选项：默认音色、默认语言、默认输出格式、超时、取消回调。"""
    voice: str
    language: Optional[str]
    output_format: str
    timeout_seconds: float
    cancel_event: Optional[object]  # asyncio.Event


class SpeechOrchestrator:
    """统一语音编排入口。"""

    async def synthesize_text(
        self,
        text: str,
        refs: Optional[list[str]] = None,
        tts_instruction: Optional[EmotionInstruction] = None,
        options: Optional[OrchestratorOptions] = None,
    ) -> SynthesisResponse:
        """普通非流式合成。"""
        ...

    async def synthesize_stream_text(
        self,
        text: str,
        refs: Optional[list[str]] = None,
        tts_instruction: Optional[EmotionInstruction] = None,
        options: Optional[OrchestratorOptions] = None,
    ) -> AsyncIterator[AudioChunk]:
        """流式合成（实时双流/直播/工作站试听）。支持打断与取消。"""
        ...

    async def interrupt(self) -> None:
        """打断当前合成并清理资源。"""
        ...

    async def close(self) -> None:
        """关闭编排器与底层 Provider。"""
        ...