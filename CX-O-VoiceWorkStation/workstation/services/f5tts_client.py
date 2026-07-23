"""
F5-TTS 合成客户端

通过 HTTP 调用 CX-O-SERVER 的 f5tts 合成能力（POST /api/tts/synthesize），
VoiceWorkStation 侧不自载 f5_tts 模型。这与 spec 方向一致：
「CX-O-SERVER 侧 f5tts 合成能力保留（情感参考音频消费者 + SVC 训练数据来源之一）」，
也与 orpheus_client 的 HTTP 客户端模式保持一致。

协议形状（复用 CX-O-SERVER 已验证的 /api/tts/synthesize）：
- 请求：{"text": gen_text, "ref_audio": <base64 wav>, "ref_text": ref_text,
          "speed": 1.0, "cross_fade_duration": 0.15}
- 响应：{"status": "success", "audio_data": <base64 wav>, "format": "wav"}
        失败时 {"status": "error", "message": "..."}（HTTP 200 + body 内 error）

f5tts 是声音克隆型 TTS：需要参考音频 + 参考文本，模型据此克隆音色合成目标文本。
参考音频由调用方提供本地路径，本 client 读取后 base64 编码传给 CX-O-SERVER。
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 健康检查端点（轻量、不触发合成）：GET /api/audio/config 返回音频配置
_HEALTH_PATH = "/api/audio/config"
# 合成端点
_SYNTHESIZE_PATH = "/api/tts/synthesize"


class F5TTSError(Exception):
    """F5-TTS 合成/健康检查异常。"""


class F5TTSClient:
    """
    F5-TTS 合成客户端，封装与 CX-O-SERVER 的 HTTP 交互。

    使用独立的 httpx.AsyncClient（lazy 初始化），生命周期由 close() 管理。
    trust_env=False 防止 Windows 系统代理拦截 127.0.0.1 请求。
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:8000",
        timeout: int = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # 内部：httpx.AsyncClient 生命周期管理
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy 初始化 httpx.AsyncClient，避免构造时即创建连接池。"""
        if self._client is None or self._client.is_closed:
            kwargs: dict = {
                "trust_env": False,
                "proxy": None,
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    def _resolve_ref_audio(self, ref_audio_path: str) -> bytes:
        """读取参考音频文件 bytes，拒绝路径穿越以防任意文件读取。

        Args:
            ref_audio_path: 本地参考音频路径（服务端受控路径）

        Returns:
            参考音频文件 bytes

        Raises:
            F5TTSError: 文件不存在或路径非法时
        """
        if not ref_audio_path or not str(ref_audio_path).strip():
            raise F5TTSError("ref_audio_path is required for f5tts synthesis")
        ref = Path(ref_audio_path)
        # 拒绝显式目录穿越（调用方传入的原始路径含 .. 视为非法）
        if ".." in Path(ref_audio_path).parts:
            raise F5TTSError(f"ref_audio_path must not contain traversal: {ref_audio_path!r}")
        try:
            return ref.read_bytes()
        except FileNotFoundError as e:
            raise F5TTSError(f"Reference audio file not found: {ref_audio_path}") from e
        except OSError as e:
            raise F5TTSError(f"Failed to read reference audio {ref_audio_path}: {e}") from e

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        ref_audio_path: str,
        ref_text: str,
        *,
        speed: float = 1.0,
        cross_fade_duration: float = 0.15,
    ) -> bytes:
        """
        非流式合成：读取本地参考音频，POST /api/tts/synthesize，返回完整 WAV bytes。

        f5tts 是声音克隆型 TTS，需参考音频 + 参考文本克隆音色后合成目标文本。

        Args:
            text: 待合成目标文本
            ref_audio_path: 参考音频本地路径（服务端受控路径）
            ref_text: 参考音频对应的文本内容（须与参考音频匹配）
            speed: 语速（默认 1.0）
            cross_fade_duration: 分段交叉淡入时长（秒，默认 0.15）

        Returns:
            完整 WAV bytes

        Raises:
            F5TTSError: 参考音频缺失、服务不可达或合成失败时
        """
        if not text or not str(text).strip():
            raise F5TTSError("text must not be empty for f5tts synthesis")
        if not ref_text or not str(ref_text).strip():
            raise F5TTSError("ref_text is required for f5tts synthesis")

        ref_audio_bytes = self._resolve_ref_audio(ref_audio_path)
        ref_audio_b64 = base64.b64encode(ref_audio_bytes).decode("ascii")

        payload = {
            "text": text,
            "ref_audio": ref_audio_b64,
            "ref_text": ref_text,
            "speed": speed,
            "cross_fade_duration": cross_fade_duration,
        }

        client = self._get_client()
        try:
            response = await client.post(
                f"{self._url}{_SYNTHESIZE_PATH}",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.RequestError as e:
            raise F5TTSError(
                f"F5-TTS 服务不可达 ({self._url}): {e}"
            ) from e

        if response.status_code != 200:
            raise F5TTSError(
                f"F5-TTS 合成失败 (HTTP {response.status_code}): "
                f"{response.text[:200]}"
            )

        data = response.json()
        if data.get("status") != "success":
            msg = data.get("message", "unknown error")
            raise F5TTSError(f"F5-TTS 合成失败: {msg}")

        audio_b64 = data.get("audio_data")
        if not audio_b64:
            raise F5TTSError("F5-TTS 合成返回空音频数据")
        try:
            return base64.b64decode(audio_b64)
        except Exception as e:
            raise F5TTSError(f"F5-TTS 响应音频解码失败: {e}") from e

    async def health_check(self) -> bool:
        """
        轻量健康检查：GET {url}/api/audio/config，返回 True/False。

        使用短超时（5s），仅验证 CX-O-SERVER 可达且音频端点响应，
        不触发任何模型推理，避免加载大模型造成阻塞。
        失败不抛异常，仅返回 False 并记录日志。

        Returns:
            True 表示服务健康，False 表示不可达或返回非 200
        """
        client = self._get_client()
        try:
            response = await client.get(
                f"{self._url}{_HEALTH_PATH}",
                timeout=5.0,
            )
            if response.status_code == 200:
                logger.info(f"F5-TTS 健康检查通过: {self._url}{_HEALTH_PATH}")
                return True
            logger.warning(
                f"F5-TTS 健康检查返回非 200 状态码: {response.status_code}"
            )
            return False
        except Exception as e:
            logger.warning(
                f"F5-TTS 健康检查失败: {self._url}{_HEALTH_PATH} - {e}"
            )
            return False

    async def close(self) -> None:
        """关闭 httpx.AsyncClient，释放连接池资源。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# ----------------------------------------------------------------------
# 单例工厂（与 voxcpm_client / orpheus_client 风格一致）
# ----------------------------------------------------------------------

_client_instance: F5TTSClient | None = None


def get_f5tts_client(
    url: str | None = None,
    timeout: int | None = None,
) -> F5TTSClient:
    """
    获取全局 F5TTSClient 单例。

    首次调用时用传入参数构造，后续调用忽略参数返回已有实例。
    通常从 WorkstationSettings.f5tts 读取配置后传入。
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = F5TTSClient(
            url=url or "http://127.0.0.1:8000",
            timeout=timeout or 300,
        )
    return _client_instance


def reset_f5tts_client() -> None:
    """重置单例（测试用）。"""
    global _client_instance
    _client_instance = None
