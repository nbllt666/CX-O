#!/usr/bin/env python3
"""
Ollama客户端

功能：
- 与Ollama API通信
- 流式响应处理
- 工具调用支持
"""

from typing import AsyncGenerator, Dict, Any, List, Optional
import json
import logging
import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama客户端"""
    
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2"
    ):
        """
        初始化Ollama客户端
        
        Args:
            host: Ollama服务地址
            model: 模型名称
        """
        self.host = host
        self.api_url = f"{host}/api/chat"
        self.model = model
        
        logger.info(f"Ollama客户端初始化: url={host}, model={model}")
    
    def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        return httpx.AsyncClient(timeout=300.0)
    
    async def is_available(self) -> bool:
        """检查服务是否可用"""
        try:
            async with self._get_client() as client:
                response = await client.get(f"{self.host}/api/tags")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama服务不可用: {e}")
            return False
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        stream: bool = True,
        tools: List[Dict] = None,
        options: Dict = None,
        **extra
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            stream: 是否流式响应
            tools: 工具定义
            options: 模型选项（temperature, seed等）
            **extra: 其他参数
        
        Yields:
            响应片段
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            **extra
        }
        
        if options:
            payload["options"] = options
        
        if tools:
            payload["tools"] = tools
        
        try:
            async with self._get_client() as client:
                async with client.stream(
                    "POST",
                    self.api_url,
                    json=payload
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            chunk = json.loads(line)
                            yield chunk
        
        except Exception as e:
            logger.error(f"Ollama请求失败: {e}")
            raise
    
    async def chat_simple(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        seed: int = None,
        **options
    ) -> str:
        """
        简单聊天请求（非流式）
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度
            seed: 随机种子
            **options: 其他选项
        
        Returns:
            完整响应
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        # 构建选项
        opt = {"temperature": temperature}
        if seed is not None:
            opt["seed"] = seed
        
        full_response = ""
        
        async for chunk in self.chat(
            messages,
            stream=True,
            options=opt if opt else None,
            **options
        ):
            message = chunk.get("message", {})
            content = message.get("content", "")
            if content:
                full_response += content
            
            if chunk.get("done"):
                break
        
        return full_response
    
    async def load_model(self):
        """预加载模型"""
        try:
            async with self._get_client() as client:
                await client.post(
                    self.api_url,
                    json={
                        "model": self.model,
                        "messages": []
                    }
                )
                logger.info(f"模型已加载: {self.model}")
        except Exception as e:
            logger.error(f"加载模型失败: {e}")
    
    async def unload_model(self):
        """卸载模型"""
        try:
            async with self._get_client() as client:
                await client.post(
                    self.api_url,
                    json={
                        "model": self.model,
                        "messages": [],
                        "keep_alive": 0
                    }
                )
                logger.info(f"模型已卸载: {self.model}")
        except Exception as e:
            logger.error(f"卸载模型失败: {e}")
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型"""
        try:
            async with self._get_client() as client:
                response = await client.get(f"{self.host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return data.get("models", [])
                return []
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    async def pull_model(self, model: str, insecure: bool = False):
        """下载模型"""
        try:
            async with self._get_client() as client:
                async with client.post(
                    f"{self.host}/api/pull",
                    json={"name": model, "insecure": insecure},
                    timeout=None  # 下载可能需要很长时间
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            yield json.loads(line)
        except Exception as e:
            logger.error(f"下载模型失败: {e}")
            raise
    
    async def generate(
        self,
        prompt: str,
        system: str = None,
        template: str = None,
        **options
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        使用/generate端点生成（非对话模式）
        
        Args:
            prompt: 提示词
            system: 系统提示
            template: 模板
            **options: 其他选项
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            **options
        }
        
        if system:
            payload["system"] = system
        if template:
            payload["template"] = template
        
        try:
            async with self._get_client() as client:
                async with client.stream(
                    "POST",
                    f"{self.host}/api/generate",
                    json=payload
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            chunk = json.loads(line)
                            yield chunk
        
        except Exception as e:
            logger.error(f"Ollama generate请求失败: {e}")
            raise
    
    async def count_tokens(self, text: str) -> int:
        """
        估算文本token数（简单估算）
        
        Args:
            text: 文本
        
        Returns:
            估算的token数
        """
        # Ollama的tiktoken支持
        try:
            async with self._get_client() as client:
                response = await client.post(
                    f"{self.host}/api/tokens",
                    json={"content": text}
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("count", len(text))
        except:
            pass
        
        # 简单估算：中文约1字=1 token，英文约4字符=1 token
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count + other_count // 4
