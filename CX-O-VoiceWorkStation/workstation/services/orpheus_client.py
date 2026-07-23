"""
Orpheus TTS 客户端

直调 docker 里的 vLLM 服务（OpenAI 兼容 API），支持流式与非流式两种合成模式。

协议形状复用 CX-O-SERVER/server/services/tts_service.py 的已验证实现：
- 非流式：POST {orpheus_url}/v1/audio/speech，body {"input": "{voice}: {text}", "voice": voice, "stream": false}
- 流式：  POST {orpheus_url}/v1/audio/speech，body {"input": "{voice}: {text}", "voice": voice, "stream": true, "response_format": "wav"}
- 健康检查：GET {orpheus_url}/health

emotion 标签（<laugh>/<giggle> 等 XML 标签）原样透传，不解析不剥离，
以保留 Orpheus 原生情感控制能力。
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

# Orpheus 流式响应的 WAV header 固定大小（data_size=0 占位头）
_WAV_HEADER_SIZE = 44


class OrpheusError(Exception):
    """Orpheus TTS 合成/健康检查异常。"""


class OrpheusClient:
    """
    Orpheus TTS 客户端，封装与 docker vLLM 服务的 HTTP 交互。

    使用独立的 httpx.AsyncClient（lazy 初始化），生命周期由 close() 管理。
    trust_env=False 防止 Windows 系统代理拦截 127.0.0.1 请求。
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:5060",
        voice: str = "tara",
        timeout: int = 60,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._voice = voice
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

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        """
        非流式合成：POST /v1/audio/speech（stream=false），返回完整 WAV bytes。

        Orpheus 使用预设音色（tara/leo 等），通过 voice 参数选择。
        请求体格式：{"input": "{voice}: {text}", "voice": voice, "stream": false}
        text 中的 <laugh>、<giggle> 等情感标签原样透传，不做解析或剥离。

        Args:
            text: 待合成文本（含可选 emotion 标签）
            voice: Orpheus 预设音色，None 则用构造时默认音色

        Returns:
            完整 WAV bytes（24000Hz 16-bit PCM）

        Raises:
            OrpheusError: 服务不可达或返回非 2xx 状态码时
        """
        selected_voice = voice or self._voice
        orpheus_input = f"{selected_voice}: {text}"

        client = self._get_client()
        try:
            response = await client.post(
                f"{self._url}/v1/audio/speech",
                json={
                    "input": orpheus_input,
                    "voice": selected_voice,
                    "stream": False,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            raise OrpheusError(
                f"Orpheus 非流式合成失败 (HTTP {e.response.status_code}): "
                f"{e.response.text[:200]}"
            ) from e
        except httpx.RequestError as e:
            raise OrpheusError(
                f"Orpheus 服务不可达 ({self._url}): {e}"
            ) from e

    async def synthesize_stream(
        self, text: str, voice: str | None = None
    ) -> AsyncGenerator[bytes, None]:
        """
        流式合成：POST /v1/audio/speech（stream=true + response_format=wav），
        跳过 44 字节 WAV header，逐块 yield PCM chunks。

        利用 vLLM chunked prefill + prefix caching 优化，首个 PCM chunk
        在 ~500ms 内到达（对比非流式需等待 ~3-8s 完整合成）。

        Orpheus 流式响应：第一块为 44 字节 WAV header（data_size=0），
        后续为 raw PCM int16 bytes（24000Hz mono）。
        本方法跳过 WAV header，仅 yield 后续 PCM bytes。

        Args:
            text: 待合成文本（含可选 emotion 标签，原样透传）
            voice: Orpheus 预设音色，None 则用构造时默认音色

        Yields:
            24000Hz 16-bit mono PCM chunks（不含 WAV header）

        Raises:
            OrpheusError: 服务不可达或返回非 2xx 状态码时
        """
        selected_voice = voice or self._voice
        orpheus_input = f"{selected_voice}: {text}"

        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                f"{self._url}/v1/audio/speech",
                json={
                    "input": orpheus_input,
                    "voice": selected_voice,
                    "stream": True,
                    "response_format": "wav",
                },
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()

                # 跳过 44 字节 WAV header，仅 yield PCM 数据
                # httpx aiter_bytes 可能以任意边界切分，需用累积变量精确跳过 header
                bytes_received = 0

                async for chunk in response.aiter_bytes():
                    if bytes_received < _WAV_HEADER_SIZE:
                        skip = min(_WAV_HEADER_SIZE - bytes_received, len(chunk))
                        chunk = chunk[skip:]
                        bytes_received += skip
                        if not chunk:
                            continue

                    bytes_received += len(chunk)
                    if chunk:
                        yield chunk
        except httpx.HTTPStatusError as e:
            raise OrpheusError(
                f"Orpheus 流式合成失败 (HTTP {e.response.status_code}): "
                f"{e.response.text[:200]}"
            ) from e
        except httpx.RequestError as e:
            raise OrpheusError(
                f"Orpheus 服务不可达 ({self._url}): {e}"
            ) from e

    async def health_check(self) -> bool:
        """
        健康检查：GET {url}/health，返回 True/False。

        使用短超时（5s），避免健康检查长时间阻塞。
        失败不抛异常，仅返回 False 并记录日志。

        Returns:
            True 表示服务健康，False 表示不可达或返回非 200
        """
        client = self._get_client()
        try:
            response = await client.get(
                f"{self._url}/health",
                timeout=5.0,
            )
            if response.status_code == 200:
                logger.info(f"Orpheus TTS 健康检查通过: {self._url}/health")
                return True
            else:
                logger.warning(
                    f"Orpheus TTS 健康检查返回非 200 状态码: {response.status_code}"
                )
                return False
        except Exception as e:
            logger.warning(
                f"Orpheus TTS 健康检查失败: {self._url}/health - {e}"
            )
            return False

    async def close(self) -> None:
        """关闭 httpx.AsyncClient，释放连接池资源。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# ----------------------------------------------------------------------
# 单例工厂（与 voxcpm_client 风格一致）
# ----------------------------------------------------------------------

_client_instance: OrpheusClient | None = None


def get_orpheus_client(
    url: str | None = None,
    voice: str | None = None,
    timeout: int | None = None,
) -> OrpheusClient:
    """
    获取全局 OrpheusClient 单例。

    首次调用时用传入参数构造，后续调用忽略参数返回已有实例。
    通常从 WorkstationSettings.orpheus 读取配置后传入。
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = OrpheusClient(
            url=url or "http://127.0.0.1:5060",
            voice=voice or "tara",
            timeout=timeout or 60,
        )
    return _client_instance


def reset_orpheus_client() -> None:
    """重置单例（测试用）。"""
    global _client_instance
    _client_instance = None
