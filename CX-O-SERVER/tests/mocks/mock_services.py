"""TTS / ASR 服务 mock（CX-O-SERVER 测试基础设施 Phase 1）。

提供 ``MockTTSService`` / ``MockASRService`` —— 轻量替身，不依赖外部模型或网络服务。
方法签名与返回结构对齐：
- ``server/services/tts_service.py`` TTSService.synthesize / synthesize_stream
- ``server/services/asr_service.py`` ASRService.recognize / recognize_base64

提供两种风格：
1. 结构化 mock 类（``MockTTSService`` / ``MockASRService``）—— 可预测的固定返回值
2. ``MagicMock`` 工厂（``create_mock_tts_service`` / ``create_mock_asr_service``）——
   返回 ``unittest.mock.MagicMock``，调用方可按需配置 ``return_value`` / ``side_effect``

注意：当前 ``public/schema/`` 无 TTS/ASR 专用 schema（待 s0201 补全），
mock 返回结构以 server 真实实现为准。
"""

from __future__ import annotations

import base64
from typing import Any, AsyncIterator, Dict, Optional
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# MockTTSService —— 结构化 TTS 服务替身
# ---------------------------------------------------------------------------
class MockTTSService:
    """轻量 TTS 服务替身，返回固定/可配置的模拟音频字节。

    不加载模型、不发起网络请求，适合在测试中替换真实 ``TTSService``。
    """

    def __init__(self, mode: str = "remote", sample_rate: int = 24000) -> None:
        self._mode = mode
        self._sample_rate = sample_rate
        self._call_count = 0

    async def synthesize(
        self,
        text: str,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        ref_audio: Optional[str] = None,
        speed: Optional[float] = None,
        cross_fade_duration: Optional[float] = None,
        **kwargs: Any,
    ) -> bytes:
        """同步合成，返回模拟音频字节。

        签名对齐 ``TTSService.synthesize``。返回固定字节序列（内容可预测，便于断言）。
        """
        self._call_count += 1
        # 生成可识别的占位字节（非真实音频），便于测试断言长度与内容
        marker = f"MOCK_TTS::{text}::end".encode("utf-8")
        padding = b"\x00" * max(0, 64 - len(marker))
        return marker + padding

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """流式合成，yield 多个模拟音频块。

        签名对齐 ``TTSService.synthesize_stream``。
        """
        self._call_count += 1
        # 将文本按 10 字符切块，模拟流式输出
        chunk_size = 10
        for i in range(0, max(1, len(text)), chunk_size):
            chunk_text = text[i : i + chunk_size]
            yield f"MOCK_TTS_CHUNK::{chunk_text}".encode("utf-8")

    @property
    def call_count(self) -> int:
        """返回 synthesize / synthesize_stream 累计调用次数。"""
        return self._call_count

    @property
    def mode(self) -> str:
        return self._mode


# ---------------------------------------------------------------------------
# MockASRService —— 结构化 ASR 服务替身
# ---------------------------------------------------------------------------
class MockASRService:
    """轻量 ASR 服务替身，返回固定/可配置的识别结果。

    不加载模型、不发起网络请求，适合在测试中替换真实 ``ASRService``。
    """

    def __init__(self, mode: str = "remote", language: str = "auto") -> None:
        self._mode = mode
        self._language = language
        self._call_count = 0

    async def recognize(
        self, audio_data: bytes, language: str = "auto", use_itn: bool = True
    ) -> Dict[str, Any]:
        """识别音频字节，返回模拟识别结果。

        签名对齐 ``ASRService.recognize``。返回结构：
        ``{"text": str, "language": str, "segments": list, "timestamp": float}``
        """
        self._call_count += 1
        return {
            "text": "这是模拟的 ASR 识别结果。",
            "language": language or self._language,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "这是模拟的 ASR 识别结果。"},
            ],
            "timestamp": 0.0,
        }

    async def recognize_base64(
        self, audio_base64: str, language: str = "auto", use_itn: bool = True
    ) -> Dict[str, Any]:
        """识别 base64 音频，返回模拟识别结果。

        签名对齐 ``ASRService.recognize_base64``。内部解码 base64 后委托 ``recognize``。
        """
        self._call_count += 1
        try:
            audio_data = base64.b64decode(audio_base64)
        except Exception:
            audio_data = b""
        return await self.recognize(audio_data, language=language, use_itn=use_itn)

    @property
    def call_count(self) -> int:
        """返回 recognize / recognize_base64 累计调用次数。"""
        return self._call_count

    @property
    def mode(self) -> str:
        return self._mode


# ---------------------------------------------------------------------------
# MagicMock 工厂 —— 灵活配置版
# ---------------------------------------------------------------------------
def create_mock_tts_service(
    synthesize_return: Optional[bytes] = None,
) -> MagicMock:
    """创建 TTS 服务的 ``MagicMock`` 替身。

    Args:
        synthesize_return: ``synthesize`` 的默认返回值；默认为 ``b"MOCK_TTS_AUDIO"``

    Returns:
        MagicMock，其 ``synthesize`` / ``synthesize_stream`` 为 AsyncMock，
        调用方可进一步配置 ``return_value`` / ``side_effect``。
    """
    mock = MagicMock()
    mock._mode = "remote"
    mock._sample_rate = 24000
    mock.synthesize = AsyncMock(return_value=synthesize_return or b"MOCK_TTS_AUDIO")
    mock.synthesize_stream = AsyncMock(return_value=iter([b"MOCK_TTS_CHUNK_1"]))
    mock.synthesize_with_emotions = AsyncMock(return_value=b"MOCK_TTS_EMOTION_AUDIO")
    return mock


def create_mock_asr_service(
    recognize_return: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """创建 ASR 服务的 ``MagicMock`` 替身。

    Args:
        recognize_return: ``recognize`` 的默认返回字典；默认为标准模拟结果

    Returns:
        MagicMock，其 ``recognize`` / ``recognize_base64`` 为 AsyncMock。
    """
    mock = MagicMock()
    mock._mode = "remote"
    mock._language = "auto"
    default_return = recognize_return or {
        "text": "这是模拟的 ASR 识别结果。",
        "language": "auto",
        "segments": [],
        "timestamp": 0.0,
    }
    mock.recognize = AsyncMock(return_value=default_return)
    mock.recognize_base64 = AsyncMock(return_value=default_return)
    mock.recognize_file = AsyncMock(return_value=default_return)
    return mock
