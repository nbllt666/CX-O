#!/usr/bin/env python3
"""
LLM客户端工厂

功能：
- 创建vLLM客户端
- 创建Ollama客户端
- 统一的LLM接口
"""

from typing import Dict, Any, Optional, Union
import logging

from .vllm_client import VLLMClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class LLMFactory:
    """LLM客户端工厂"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化LLM工厂
        
        Args:
            config: 全局配置
        """
        self.config = config
        self._vllm_client: Optional[VLLMClient] = None
        self._ollama_client: Optional[OllamaClient] = None
        
        # 初始化客户端
        self._init_clients()
    
    def _init_clients(self):
        """初始化客户端"""
        system_config = self.config.get('system', {})
        
        # 初始化vLLM客户端
        vllm_config = system_config.get('vllm', {})
        if vllm_config.get('host'):
            try:
                self._vllm_client = VLLMClient(
                    base_url=vllm_config.get('host', 'localhost'),
                    port=vllm_config.get('port', 8000),
                    model=vllm_config.get('model', 'Qwen2.5-7B-Instruct'),
                    api_key=vllm_config.get('api_key', 'EMPTY')
                )
                logger.info(f"vLLM客户端初始化成功: {vllm_config.get('host')}:{vllm_config.get('port')}")
            except Exception as e:
                logger.error(f"vLLM客户端初始化失败: {e}")
        
        # 初始化Ollama客户端
        ollama_config = system_config.get('ollama', {})
        if ollama_config.get('host'):
            try:
                self._ollama_client = OllamaClient(
                    host=ollama_config.get('host', 'http://localhost:11434')
                )
                logger.info(f"Ollama客户端初始化成功: {ollama_config.get('host')}")
            except Exception as e:
                logger.error(f"Ollama客户端初始化失败: {e}")
    
    def get_client(self, provider: str = None) -> Union[VLLMClient, OllamaClient]:
        """
        获取指定提供商的客户端
        
        Args:
            provider: 提供商标识 ('vllm' | 'ollama')
        
        Returns:
            LLM客户端实例
        """
        if provider is None:
            provider = self.config.get('system', {}).get('llm_provider', 'vllm')
        
        if provider == 'vllm':
            if self._vllm_client is None:
                raise RuntimeError("vLLM客户端未初始化，请检查配置")
            return self._vllm_client
        elif provider == 'ollama':
            if self._ollama_client is None:
                raise RuntimeError("Ollama客户端未初始化，请检查配置")
            return self._ollama_client
        else:
            raise ValueError(f"不支持的LLM提供商: {provider}")
    
    def get_vllm_client(self) -> Optional[VLLMClient]:
        """获取vLLM客户端"""
        return self._vllm_client
    
    def get_ollama_client(self) -> Optional[OllamaClient]:
        """获取Ollama客户端"""
        return self._ollama_client
    
    def is_available(self, provider: str = None) -> bool:
        """
        检查指定提供商是否可用
        
        Args:
            provider: 提供商标识
        """
        try:
            client = self.get_client(provider)
            return client.is_available()
        except:
            return False
    
    async def chat(
        self,
        messages: list,
        provider: str = None,
        stream: bool = True,
        tools: list = None,
        **options
    ):
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            provider: 提供商标识
            stream: 是否流式响应
            tools: 工具定义
            **options: 其他选项
        """
        client = self.get_client(provider)
        return await client.chat(messages, stream, tools, **options)
    
    async def chat_simple(
        self,
        prompt: str,
        provider: str = None,
        **options
    ) -> str:
        """
        简单聊天（非流式）
        
        Args:
            prompt: 提示词
            provider: 提供商标识
            **options: 其他选项
        """
        client = self.get_client(provider)
        return await client.chat_simple(prompt, **options)
    
    def get_model_name(self, provider: str = None) -> str:
        """
        获取模型名称
        
        Args:
            provider: 提供商标识
        """
        if provider is None:
            provider = self.config.get('system', {}).get('llm_provider', 'vllm')
        
        if provider == 'vllm' and self._vllm_client:
            return self._vllm_client.model
        elif provider == 'ollama' and self._ollama_client:
            return self._ollama_client.model
        else:
            return "unknown"
