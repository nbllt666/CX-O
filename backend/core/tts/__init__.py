"""
TTS 服务模块
支持本地和远程 TTS 合成
"""

from backend.core.tts.local_synthesizer import LocalSynthesizer
from backend.core.tts.remote_client import RemoteTTSClient

__all__ = [
    "LocalSynthesizer",
    "RemoteTTSClient",
    "TTSService",
]


class TTSService:
    """TTS 服务封装，根据配置自动选择本地或远程模式"""

    def __init__(
        self,
        provider: str = "local",
        model_name: str = "cosyvoice",
        device: str = "cpu",
        remote_endpoint: str = "http://localhost:8002/tts",
    ):
        self.provider = provider
        self.model_name = model_name
        self.device = device
        self.remote_endpoint = remote_endpoint
        self._synthesizer = None
        self._initialized = False

    def initialize(self) -> bool:
        """初始化 TTS 服务"""
        if self.provider == "local":
            self._synthesizer = LocalSynthesizer(
                model_name=self.model_name,
                device=self.device,
            )
        else:
            self._synthesizer = RemoteTTSClient(
                endpoint=self.remote_endpoint,
            )

        try:
            self._initialized = self._synthesizer.initialize()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"TTS 服务初始化失败: {e}")
            self._initialized = False

        return self._initialized

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
    ) -> bytes:
        """合成语音"""
        if not self._initialized:
            raise RuntimeError("TTS 服务未初始化")
        return self._synthesizer.synthesize(text, voice, speed)

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return self._initialized

    def close(self):
        """关闭服务"""
        if self._synthesizer:
            self._synthesizer.close()
        self._initialized = False
