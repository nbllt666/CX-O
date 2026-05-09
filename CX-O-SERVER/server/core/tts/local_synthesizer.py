"""
TTS 本地合成服务
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LocalSynthesizer:
    """本地 TTS 合成器"""

    def __init__(
        self,
        model_name: str = "cosyvoice",
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
            if self.model_name == "cosyvoice":
                self._initialize_cosyvoice()
            elif self.model_name == "f5-tts":
                self._initialize_f5tts()
            else:
                logger.warning(f"未知的 TTS 模型: {self.model_name}，使用默认模型")
                self._initialize_cosyvoice()

            self._initialized = True
            logger.info(f"本地 TTS 模型初始化成功: {self.model_name} ({self.device})")
            return True

        except Exception as e:
            logger.error(f"本地 TTS 模型初始化失败: {e}")
            self._initialized = False
            return False

    def _initialize_cosyvoice(self):
        """初始化 CosyVoice 模型"""
        try:
            import torch
            import sys
            sys.path.insert(0, "cosyvoice")

            from cosyvoice.cli.cosyvoice import CosyVoice

            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA 不可用，回退到 CPU")
                self.device = "cpu"

            self._model = CosyVoice(self.model_path, device=self.device)
        except ImportError as e:
            logger.error(f"CosyVoice 模型导入失败: {e}")
            raise

    def _initialize_f5tts(self):
        """初始化 F5-TTS 模型"""
        try:
            import torch
            from f5_tts.api import load_model, get_f5tts

            if self.device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA 不可用，回退到 CPU")
                self.device = "cpu"

            if not load_model():
                raise RuntimeError("Failed to load F5-TTS model")
            self._model = get_f5tts()
        except ImportError as e:
            logger.error(f"F5-TTS 模型导入失败: {e}")
            raise

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
            音频数据（ WAV 格式）
        """
        if not self._initialized:
            raise RuntimeError("TTS 模型未初始化，请先调用 initialize()")

        try:
            if self.model_name == "cosyvoice":
                return self._synthesize_cosyvoice(text, voice, speed)
            elif self.model_name == "f5-tts":
                return self._synthesize_f5tts(text, voice, speed)
            else:
                return self._synthesize_cosyvoice(text, voice, speed)

        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            raise

    def _synthesize_cosyvoice(self, text: str, voice: str, speed: float) -> bytes:
        """使用 CosyVoice 合成"""
        import io
        import wave

        output = io.BytesIO()
        for segment in self._model.inference(text, stream=False):
            if hasattr(segment, 'audio'):
                audio_data = segment.audio
            else:
                audio_data = segment

            if isinstance(audio_data, list):
                audio_data = b"".join(audio_data)
            elif not isinstance(audio_data, bytes):
                import numpy as np
                audio_data = (np.array(audio_data) * 32767).astype(np.int16).tobytes()

            wave_writer = wave.open(output, 'wb')
            wave_writer.setnchannels(1)
            wave_writer.setsampwidth(2)
            wave_writer.setframerate(22050)
            wave_writer.writeframes(audio_data)
            wave_writer.close()

        return output.getvalue()

    def _synthesize_f5tts(self, text: str, voice: str, speed: float) -> bytes:
        """使用 F5-TTS 合成"""
        import io
        import wave
        import numpy as np

        audio_data = self._model.inference(text)

        if isinstance(audio_data, bytes):
            return audio_data

        output = io.BytesIO()
        if isinstance(audio_data, np.ndarray):
            audio_int16 = (audio_data * 32767).astype(np.int16).tobytes()
        else:
            audio_int16 = audio_data

        wave_writer = wave.open(output, 'wb')
        wave_writer.setnchannels(1)
        wave_writer.setsampwidth(2)
        wave_writer.setframerate(24000)
        wave_writer.writeframes(audio_int16)
        wave_writer.close()

        return output.getvalue()

    def is_available(self) -> bool:
        """检查模型是否可用"""
        return self._initialized and self._model is not None

    def close(self):
        """关闭模型"""
        if self._model is not None:
            del self._model
            self._model = None
        self._initialized = False
        logger.info("本地 TTS 模型已关闭")
