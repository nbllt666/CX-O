"""
ASR 本地推理服务
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LocalRecognizer:
    """本地 ASR 识别器"""

    def __init__(
        self,
        model_name: str = "sensevoice",
        device: str = "cpu",
        model_path: Optional[str] = None,
    ):
        self.model_name = model_name
        self.device = device
        self.model_path = model_path
        self._model = None
        self._initialized = False

    def initialize(self) -> bool:
        """初始化模型"""
        try:
            if self.model_name == "sensevoice":
                self._initialize_sensevoice()
            elif self.model_name == "whisper":
                self._initialize_whisper()
            else:
                logger.warning(f"未知的 ASR 模型: {self.model_name}，使用默认模型")
                self._initialize_sensevoice()

            self._initialized = True
            logger.info(f"本地 ASR 模型初始化成功: {self.model_name} ({self.device})")
            return True

        except Exception as e:
            logger.error(f"本地 ASR 模型初始化失败: {e}")
            self._initialized = False
            return False

    def _initialize_sensevoice(self):
        """初始化 SenseVoice 模型"""
        try:
            import torch
            from sensevoice.model import SenseVoiceModel

            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA 不可用，回退到 CPU")
                self.device = "cpu"

            self._model = SenseVoiceModel(
                model_path=self.model_path,
                device=self.device,
            )
        except ImportError as e:
            logger.error(f"SenseVoice 模型导入失败: {e}")
            raise

    def _initialize_whisper(self):
        """初始化 Whisper 模型"""
        try:
            import torch
            import whisper

            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA 不可用，回退到 CPU")
                self.device = "cpu"

            self._model = whisper.load_model("base", device=self.device)
        except ImportError as e:
            logger.error(f"Whisper 模型导入失败: {e}")
            raise

    def recognize(self, audio_data: bytes, language: str = "auto") -> str:
        """识别语音

        Args:
            audio_data: 音频数据（字节）
            language: 语言代码，auto 表示自动检测

        Returns:
            识别文本
        """
        if not self._initialized:
            raise RuntimeError("ASR 模型未初始化，请先调用 initialize()")

        try:
            import numpy as np
            import tempfile
            import wave

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name

            if self.model_name == "sensevoice":
                result = self._recognize_sensevoice(temp_path, language)
            elif self.model_name == "whisper":
                result = self._recognize_whisper(temp_path, language)
            else:
                result = self._recognize_sensevoice(temp_path, language)

            return result

        except Exception as e:
            logger.error(f"ASR 识别失败: {e}")
            raise

    def _recognize_sensevoice(self, audio_path: str, language: str) -> str:
        """使用 SenseVoice 识别"""
        result = self._model.inference(audio_path)
        return result.get("text", "")

    def _recognize_whisper(self, audio_path: str, language: str) -> str:
        """使用 Whisper 识别"""
        import whisper

        options = {}
        if language != "auto":
            options["language"] = language

        result = self._model.transcribe(audio_path, **options)
        return result.get("text", "").strip()

    def is_available(self) -> bool:
        """检查模型是否可用"""
        return self._initialized and self._model is not None

    def close(self):
        """关闭模型"""
        if self._model is not None:
            del self._model
            self._model = None
        self._initialized = False
        logger.info("本地 ASR 模型已关闭")
