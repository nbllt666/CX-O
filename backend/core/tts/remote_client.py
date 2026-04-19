"""
TTS 远程客户端
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RemoteTTSClient:
    """远程 TTS 客户端"""

    def __init__(
        self,
        endpoint: str = "http://localhost:8002/tts",
        timeout: int = 60,
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self._initialized = False

    def initialize(self) -> bool:
        """初始化客户端"""
        try:
            self._initialized = True
            logger.info(f"远程 TTS 客户端初始化成功: {self.endpoint}")
            return True
        except Exception as e:
            logger.error(f"远程 TTS 客户端初始化失败: {e}")
            self._initialized = False
            return False

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
    ) -> bytes:
        """合成语音

        Args:
            text: 文本内容
            voice: 声音选择
            speed: 语速

        Returns:
            音频数据（字节）
        """
        if not self._initialized:
            raise RuntimeError("远程 TTS 客户端未初始化")

        try:
            import httpx

            with httpx.Client(timeout=self.timeout) as client:
                payload = {
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                }
                response = client.post(self.endpoint, json=payload)
                response.raise_for_status()
                return response.content

        except Exception as e:
            logger.error(f"远程 TTS 调用失败: {e}")
            raise

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._initialized

    def close(self):
        """关闭客户端"""
        self._initialized = False
        logger.info("远程 TTS 客户端已关闭")
