"""
ASR 远程客户端
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RemoteASRClient:
    """远程 ASR 客户端"""

    def __init__(
        self,
        endpoint: str = "http://localhost:8001/asr",
        timeout: int = 30,
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self._initialized = False

    def initialize(self) -> bool:
        """初始化客户端"""
        try:
            import httpx
            self._client = httpx.Client(timeout=self.timeout)
            self._initialized = True
            logger.info(f"远程 ASR 客户端初始化成功: {self.endpoint}")
            return True
        except Exception as e:
            logger.error(f"远程 ASR 客户端初始化失败: {e}")
            self._initialized = False
            return False

    def recognize(self, audio_data: bytes, language: str = "auto") -> str:
        """识别语音

        Args:
            audio_data: 音频数据（字节）
            language: 语言代码

        Returns:
            识别文本
        """
        if not self._initialized:
            raise RuntimeError("远程 ASR 客户端未初始化")

        try:
            import httpx

            with httpx.Client(timeout=self.timeout) as client:
                files = {"audio": ("audio.wav", audio_data, "audio/wav")}
                data = {"language": language}
                response = client.post(self.endpoint, files=files, data=data)
                response.raise_for_status()
                result = response.json()
                return result.get("text", "")

        except Exception as e:
            logger.error(f"远程 ASR 调用失败: {e}")
            raise

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._initialized

    def close(self):
        """关闭客户端"""
        if hasattr(self, "_client"):
            self._client.close()
        self._initialized = False
        logger.info("远程 ASR 客户端已关闭")
