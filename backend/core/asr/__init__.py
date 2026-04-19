"""
ASR 服务模块
支持本地和远程 ASR 识别
"""

from backend.core.asr.local_recognizer import LocalRecognizer
from backend.core.asr.remote_client import RemoteASRClient

__all__ = [
    "LocalRecognizer",
    "RemoteASRClient",
    "ASRService",
]


class ASRService:
    """ASR 服务封装，根据配置自动选择本地或远程模式"""

    def __init__(
        self,
        provider: str = "local",
        model_name: str = "sensevoice",
        device: str = "cpu",
        remote_endpoint: str = "http://localhost:8001/asr",
    ):
        self.provider = provider
        self.model_name = model_name
        self.device = device
        self.remote_endpoint = remote_endpoint
        self._recognizer = None
        self._initialized = False

    def initialize(self) -> bool:
        """初始化 ASR 服务"""
        if self.provider == "local":
            self._recognizer = LocalRecognizer(
                model_name=self.model_name,
                device=self.device,
            )
        else:
            self._recognizer = RemoteASRClient(
                endpoint=self.remote_endpoint,
            )

        try:
            self._initialized = self._recognizer.initialize()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"ASR 服务初始化失败: {e}")
            self._initialized = False

        return self._initialized

    def recognize(self, audio_data: bytes, language: str = "auto") -> str:
        """识别语音"""
        if not self._initialized:
            raise RuntimeError("ASR 服务未初始化")
        return self._recognizer.recognize(audio_data, language)

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._initialized

    def close(self):
        """关闭服务"""
        if self._recognizer:
            self._recognizer.close()
        self._initialized = False
