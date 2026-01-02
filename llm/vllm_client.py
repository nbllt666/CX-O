#!/usr/bin/env python3
"""
vLLM客户端

功能：
- 与vLLM OpenAI兼容API通信
- 流式响应处理
- 工具调用支持
"""

from typing import AsyncGenerator, Dict, Any, List, Optional
import json
import logging
import httpx

logger = logging.getLogger(__name__)


class VLLMClient:
    """vLLM客户端"""
    
    def __init__(
        self,
        base_url: str = "localhost",
        port: int = 8000,
        model: str = "Qwen2.5-7B-Instruct",
        api_key: str = "EMPTY"
    ):
        """
        初始化vLLM客户端
        
        Args:
            base_url: vLLM服务地址
            port: vLLM服务端口
            model: 模型名称
            api_key: API密钥
        """
        self.base_url = f"http://{base_url}:{port}/v1"
        self.model = model
        self.api_key = api_key
        
        logger.info(f"vLLM客户端初始化: url={self.base_url}, model={model}")
    
    def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        return httpx.AsyncClient(timeout=120.0)
    
    async def is_available(self) -> bool:
        """检查服务是否可用"""
        try:
            async with self._get_client() as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"vLLM服务不可用: {e}")
            return False
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        stream: bool = True,
        tools: List[Dict] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **options
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            stream: 是否流式响应
            tools: 工具定义
            max_tokens: 最大生成token数
            temperature: 温度
            **options: 其他选项
        
        Yields:
            响应片段
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
            **options
        }
        
        if tools:
            payload["tools"] = tools
        
        try:
            async with self._get_client() as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"}
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip() and line.startswith("data: "):
                            data = line[6:]  # 去掉 "data: " 前缀
                            if data != "[DONE]":
                                chunk = json.loads(data)
                                yield chunk
        
        except Exception as e:
            logger.error(f"vLLM请求失败: {e}")
            raise
    
    async def chat_simple(
        self,
        prompt: str,
        system_prompt: str = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **options
    ) -> str:
        """
        简单聊天请求（非流式）
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            max_tokens: 最大生成token数
            temperature: 温度
            **options: 其他选项
        
        Returns:
            完整响应
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        full_response = ""
        
        async for chunk in self.chat(
            messages,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
            **options
        ):
            if chunk.get("choices") and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_response += content
        
        return full_response
    
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        获取文本嵌入向量
        
        Args:
            texts: 文本列表
        
        Returns:
            嵌入向量列表
        """
        try:
            async with self._get_client() as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json={
                        "model": self.model,
                        "input": texts
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return [item["embedding"] for item in result.get("data", [])]
                else:
                    logger.error(f"获取嵌入失败: {response.text}")
                    return []
        
        except Exception as e:
            logger.error(f"获取嵌入失败: {e}")
            return []
    
    async def count_tokens(self, text: str) -> int:
        """
        估算文本token数（简单估算）
        
        Args:
            text: 文本
        
        Returns:
            估算的token数
        """
        # 简单估算：中文约1字=1 token，英文约4字符=1 token
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count + other_count // 4
