#!/usr/bin/env python3
"""
语音识别（ASR）模块

功能：
- SenseVoice API服务调用
- Whisper本地模型
- 音频文件/流识别
"""

from pathlib import Path
from typing import Optional, AsyncGenerator
import logging
import asyncio
import base64
import httpx

logger = logging.getLogger(__name__)


class ASRBase:
    """ASR基类"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
    
    async def recognize(self, audio_path: str) -> str:
        """识别音频文件"""
        raise NotImplementedError
    
    async def recognize_stream(self, audio_chunk: bytes) -> AsyncGenerator[str, None]:
        """流式识别"""
        raise NotImplementedError


class SenseVoiceASR(ASRBase):
    """SenseVoice API语音识别（HTTP服务调用）"""
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.api_url = self.config.get("api_url", "http://localhost:50000/api/v1/asr")
        self.language = self.config.get("language", "auto")
        self.use_itn = self.config.get("use_itn", True)
        logger.info(f"SenseVoice ASR初始化完成: {self.api_url}")
    
    async def recognize(self, audio_path: str) -> str:
        """识别音频文件"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                # 读取音频文件
                with open(audio_path, "rb") as f:
                    audio_data = f.read()
                
                # 构建表单数据
                files = {
                    "file": (Path(audio_path).name, audio_data, "audio/wav")
                }
                data = {
                    "language": self.language,
                    "use_itn": str(self.use_itn).lower(),
                    "task": "rich"
                }
                
                # 发送请求
                response = await client.post(
                    self.api_url,
                    files=files,
                    data=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    # 提取识别文本
                    if result.get("results"):
                        return result["results"][0].get("text", "")
                    return ""
                else:
                    logger.error(f"SenseVoice API错误: {response.status_code}")
                    return ""
        
        except Exception as e:
            logger.error(f"SenseVoice识别失败: {e}")
            return ""
    
    async def recognize_base64(self, audio_base64: str) -> str:
        """识别Base64编码的音频"""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                data = {
                    "audio": {
                        "audio_base64": audio_base64
                    },
                    "language": self.language,
                    "use_itn": self.use_itn
                }
                
                response = await client.post(
                    f"{self.api_url}/json",
                    json=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("results"):
                        return result["results"][0].get("text", "")
                    return ""
                else:
                    logger.error(f"SenseVoice API错误: {response.status_code}")
                    return ""
        
        except Exception as e:
            logger.error(f"SenseVoice识别失败: {e}")
            return ""


class WhisperASR(ASRBase):
    """Whisper本地语音识别"""
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.model = None
        self.device = "cuda" if self.config.get("use_gpu", True) else "cpu"
        logger.info("Whisper ASR初始化完成")
    
    async def recognize(self, audio_path: str) -> str:
        """识别音频文件"""
        try:
            import whisper
            
            if self.model is None:
                model_size = self.config.get("model_size", "base")
                self.model = whisper.load_model(model_size, device=self.device)
            
            result = self.model.transcribe(
                audio_path,
                language="Chinese",
                no_timestamps=True
            )
            
            return result["text"].strip()
        
        except Exception as e:
            logger.error(f"Whisper识别失败: {e}")
            return ""


class ASRFactory:
    """ASR工厂类"""
    
    @staticmethod
    def create(provider: str = "sensevoice", config: dict = None) -> ASRBase:
        """创建ASR实例"""
        if provider == "sensevoice":
            return SenseVoiceASR(config)
        elif provider == "whisper":
            return WhisperASR(config)
        else:
            raise ValueError(f"不支持的ASR提供商: {provider}")


async def recognize_audio(
    audio_path: str,
    provider: str = "sensevoice",
    config: dict = None
) -> str:
    """
    识别音频文件
    
    Args:
        audio_path: 音频文件路径
        provider: ASR提供商（sensevoice/whisper）
        config: 配置
    
    Returns:
        识别文本
    """
    asr = ASRFactory.create(provider, config)
    return await asr.recognize(audio_path)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="语音识别测试")
    parser.add_argument("audio", help="音频文件路径")
    parser.add_argument("--provider", default="sensevoice", help="ASR提供商")
    
    args = parser.parse_args()
    
    import asyncio
    
    result = asyncio.run(recognize_audio(args.audio, args.provider))
    print(f"识别结果: {result}")
