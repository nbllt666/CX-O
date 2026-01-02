#!/usr/bin/env python3
"""
语音合成（TTS）模块

功能：
- 支持F5-TTS模型
- 支持Edge TTS
- 音频流式输出
"""

from pathlib import Path
from typing import Optional, AsyncGenerator
import logging
import base64
import numpy as np

logger = logging.getLogger(__name__)


class TTSBase:
    """TTS基类"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.sample_rate = 24000
    
    async def synthesize(self, text: str, output_path: str = None) -> bytes:
        """合成语音"""
        raise NotImplementedError
    
    async def synthesize_stream(
        self, 
        text: str
    ) -> AsyncGenerator[bytes, None]:
        """流式合成"""
        raise NotImplementedError


class F5TTS(TTSBase):
    """F5-TTS语音合成"""
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.model = None
        self.device = "cuda" if self.config.get("use_gpu", True) else "cpu"
        self.ref_file = self.config.get("ref_file", None)
        self.ref_text = self.config.get("ref_text", "")
        logger.info("F5-TTS初始化完成")
    
    async def synthesize(self, text: str, output_path: str = None) -> bytes:
        """合成语音"""
        try:
            from f5_tts.api import F5TTS as F5TTS_API
            
            if self.model is None:
                self.model = F5TTS_API(
                    model_type="E2-TTS",
                    ckpt_file="",
                    vocab_file="",
                    device=self.device
                )
            
            if not self.ref_file:
                raise ValueError("F5-TTS需要提供参考音频文件路径 (ref_file)")
            
            # 生成音频
            wav, sr, spect = self.model.infer(
                ref_file=self.ref_file,
                ref_text=self.ref_text,
                gen_text=text,
                file_wave=output_path,
                remove_silence=False
            )
            
            if output_path is None:
                return wav.numpy().tobytes()
            return b""
        
        except ImportError:
            logger.warning("F5-TTS未安装，使用备用方案")
            return await self._fallback_synthesize(text, output_path)
        
        except Exception as e:
            logger.error(f"F5-TTS合成失败: {e}")
            return await self._fallback_synthesize(text, output_path)
    
    def _fallback_synthesize(
        self, 
        text: str, 
        output_path: str = None
    ) -> bytes:
        """备用合成方案"""
        import asyncio
        
        loop = asyncio.new_event_loop()
        asyncio.set_loop(loop)
        try:
            from edge_tts import Communicate
            
            communicate = Communicate(text, "zh-CN-XiaoxiaoNeural")
            
            if output_path:
                loop.run_until_complete(communicate.save(output_path))
                return b""
            else:
                audio_data = bytearray()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])
                return bytes(audio_data)
        except Exception as e:
            logger.error(f"备用TTS失败: {e}")
            return b""


class EdgeTTS(TTSBase):
    """Edge TTS语音合成"""
    
    VOICES = {
        "female": "zh-CN-XiaoxiaoNeural",
        "male": "zh-CN-YunxiNeural",
        "female2": "zh-CN-XiaoyouNeural",
    }
    
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.voice = self.config.get("voice", "zh-CN-XiaoxiaoNeural")
        self.rate = self.config.get("rate", "+0%")
        self.volume = self.config.get("volume", "+0%")
        logger.info(f"Edge TTS初始化完成: voice={self.voice}")
    
    async def synthesize(self, text: str, output_path: str = None) -> bytes:
        """合成语音"""
        try:
            from edge_tts import Communicate
            import asyncio
            
            communicate = Communicate(
                text, 
                self.voice,
                rate=self.rate,
                volume=self.volume
            )
            
            if output_path:
                await communicate.save(output_path)
                
                with open(output_path, "rb") as f:
                    return f.read()
            else:
                audio_data = bytearray()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])
                
                return bytes(audio_data)
        
        except Exception as e:
            logger.error(f"Edge TTS合成失败: {e}")
            return b""
    
    async def synthesize_stream(
        self, 
        text: str
    ) -> AsyncGenerator[bytes, None]:
        """流式合成"""
        try:
            from edge_tts import Communicate
            
            communicate = Communicate(
                text, 
                self.voice,
                rate=self.rate,
                volume=self.volume
            )
            
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        
        except Exception as e:
            logger.error(f"Edge TTS流式合成失败: {e}")


class TTSFactory:
    """TTS工厂类"""
    
    @staticmethod
    def create(provider: str = "edge", config: dict = None) -> TTSBase:
        """创建TTS实例"""
        if provider == "f5-tts" or provider == "f5":
            return F5TTS(config)
        elif provider == "edge":
            return EdgeTTS(config)
        else:
            raise ValueError(f"不支持的TTS提供商: {provider}")


async def synthesize_speech(
    text: str,
    provider: str = "edge",
    config: dict = None,
    output_path: str = None
) -> bytes:
    """
    合成语音
    
    Args:
        text: 要合成的文本
        provider: TTS提供商（f5/edge）
        config: 配置
        output_path: 输出文件路径
    
    Returns:
        音频数据（bytes）
    """
    tts = TTSFactory.create(provider, config)
    return await tts.synthesize(text, output_path)


def encode_audio_base64(audio_data: bytes) -> str:
    """将音频编码为base64"""
    return base64.b64encode(audio_data).decode("utf-8")


def decode_audio_base64(base64_str: str) -> bytes:
    """解码base64音频"""
    return base64.b64decode(base64_str)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="语音合成测试")
    parser.add_argument("text", help="要合成的文本")
    parser.add_argument("--provider", default="edge", help="TTS提供商")
    parser.add_argument("--output", "-o", help="输出文件路径")
    
    args = parser.parse_args()
    
    import asyncio
    
    audio = asyncio.run(synthesize_speech(args.text, args.provider, None, args.output))
    
    if args.output:
        print(f"音频已保存到: {args.output}")
    else:
        print(f"生成音频大小: {len(audio)} bytes")
