"""
模型路由器 - 管理多模型配置和客户端

提供多模型支持，包括主模型、摘要模型、记忆模型等
支持模型默认跟随机制
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from backend.core.llm.client import LLMClient, OllamaClient, VLLMClient
from config.settings import ModelConfig, settings

logger = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    """模型状态信息"""

    name: str
    available: bool
    last_check: str
    error: Optional[str] = None
    latency_ms: Optional[float] = None
    config: Optional[Dict] = None


class ModelRouter:
    """模型路由器 - 管理多模型客户端"""

    def __init__(self):
        self._clients: Dict[str, LLMClient] = {}
        self._status: Dict[str, ModelStatus] = {}
        self._initialized = False

    async def initialize(self):
        """初始化模型路由器"""
        if self._initialized:
            return

        logger.info("初始化模型路由器...")

        # 初始化所有模型客户端
        model_types = ["main", "summary", "memory"]

        for model_type in model_types:
            try:
                client = self._create_client(model_type)
                if client:
                    self._clients[model_type] = client
                    logger.info(f"模型客户端已创建: {model_type}")
            except Exception as e:
                logger.error(f"创建模型客户端失败 {model_type}: {e}")

        # 检查所有模型状态
        await self.check_all_status()

        self._initialized = True
        logger.info("模型路由器初始化完成")

    def _create_client(self, model_type: str) -> Optional[LLMClient]:
        """创建指定类型的模型客户端"""
        config = settings.config.models.get_model_config(model_type)

        if not config:
            logger.warning(f"未找到模型配置: {model_type}")
            return None

        provider = config.provider.lower()

        if provider == "ollama":
            return OllamaClient(
                host=config.host,
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                api_key=getattr(config, "api_key", None),
            )
        elif provider == "vllm":
            return VLLMClient(
                host=config.host,
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        else:
            logger.warning(f"不支持的模型提供商: {provider}")
            return None

    def get_client(self, model_type: str = "main") -> Optional[LLMClient]:
        """获取指定类型的模型客户端

        Args:
            model_type: 模型类型 (main, summary, memory)

        Returns:
            LLMClient实例或None
        """
        model_type = model_type.lower()

        # 检查是否有默认跟随配置
        if model_type in settings.config.models.defaults:
            target = settings.config.models.defaults[model_type]
            if target in self._clients:
                logger.debug(f"模型 {model_type} 跟随 {target}")
                return self._clients[target]

        # 返回指定类型的客户端
        return self._clients.get(model_type)

    def get_config(self, model_type: str = "main") -> Optional[ModelConfig]:
        """获取指定类型的模型配置

        Args:
            model_type: 模型类型 (main, summary, memory)

        Returns:
            ModelConfig实例或None
        """
        return settings.config.models.get_model_config(model_type)

    async def check_status(self, model_type: str) -> ModelStatus:
        """检查指定模型的状态

        Args:
            model_type: 模型类型

        Returns:
            ModelStatus状态对象
        """
        config = self.get_config(model_type)
        if not config:
            status = ModelStatus(
                name=model_type,
                available=False,
                last_check=datetime.now().isoformat(),
                error="配置不存在",
            )
            self._status[model_type] = status
            return status

        start_time = datetime.now()
        error_msg = None
        available = False

        try:
            # 根据提供商检查连接
            provider = config.provider.lower()

            if provider == "ollama":
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"{config.host}/api/tags")
                    available = response.status_code == 200
                    if not available:
                        error_msg = f"HTTP {response.status_code}"

            elif provider == "vllm":
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"{config.host}/health")
                    available = response.status_code == 200
                    if not available:
                        error_msg = f"HTTP {response.status_code}"
            else:
                error_msg = f"不支持的提供商: {provider}"

        except httpx.ConnectError as e:
            error_msg = f"连接失败: {e}"
        except httpx.TimeoutException as e:
            error_msg = f"连接超时"
        except Exception as e:
            error_msg = str(e)

        # 计算延迟
        latency = (datetime.now() - start_time).total_seconds() * 1000

        status = ModelStatus(
            name=model_type,
            available=available,
            last_check=datetime.now().isoformat(),
            error=error_msg,
            latency_ms=round(latency, 2),
            config={"provider": config.provider, "host": config.host, "model": config.model},
        )

        self._status[model_type] = status

        if available:
            logger.info(f"模型 {model_type} 可用 (延迟: {latency:.2f}ms)")
        else:
            logger.warning(f"模型 {model_type} 不可用: {error_msg}")

        return status

    async def check_all_status(self) -> Dict[str, ModelStatus]:
        """检查所有模型的状态

        Returns:
            所有模型状态字典
        """
        model_types = ["main", "summary", "memory"]

        for model_type in model_types:
            await self.check_status(model_type)

        return self._status

    def get_all_status(self) -> Dict[str, ModelStatus]:
        """获取所有模型的当前状态（不重新检查）

        Returns:
            所有模型状态字典
        """
        return self._status

    def is_available(self, model_type: str = "main") -> bool:
        """检查指定模型是否可用

        Args:
            model_type: 模型类型

        Returns:
            是否可用
        """
        status = self._status.get(model_type)
        return status and status.available

    async def chat(
        self, model_type: str, messages: List[Dict], stream: bool = False, **kwargs
    ) -> Dict[str, Any]:
        """使用指定模型进行对话

        Args:
            model_type: 模型类型
            messages: 消息列表
            stream: 是否流式响应
            **kwargs: 额外参数

        Returns:
            对话结果
        """
        client = self.get_client(model_type)

        if not client:
            return {"success": False, "error": f"模型客户端不存在: {model_type}", "content": ""}

        try:
            response = await client.chat(messages, stream, **kwargs)

            return {
                "success": response.finish_reason != "error",
                "content": response.content,
                "finish_reason": response.finish_reason,
                "usage": response.usage,
                "error": getattr(response, "error", None),
                "error_details": getattr(response, "error_details", {}),
            }

        except Exception as e:
            logger.error(f"模型对话失败 {model_type}: {e}")
            return {"success": False, "error": str(e), "content": ""}

    async def get_embedding(self, model_type: str, text: str) -> Optional[List[float]]:
        """获取文本的向量嵌入

        Args:
            model_type: 模型类型（通常是memory模型）
            text: 输入文本

        Returns:
            向量列表或None
        """
        client = self.get_client(model_type)

        if not client:
            logger.warning(f"无法获取embedding，模型客户端不存在: {model_type}")
            return None

        # 检查客户端是否支持get_embedding方法
        if hasattr(client, "get_embedding"):
            try:
                return await client.get_embedding(text)
            except Exception as e:
                logger.error(f"获取embedding失败: {e}")
                return None
        else:
            logger.warning(f"模型客户端不支持get_embedding: {model_type}")
            return None

    def get_model_info(self, model_type: str = "main") -> Dict[str, Any]:
        """获取模型信息

        Args:
            model_type: 模型类型

        Returns:
            模型信息字典
        """
        config = self.get_config(model_type)
        status = self._status.get(model_type)

        if not config:
            return {"error": "配置不存在"}

        info = {
            "type": model_type,
            "provider": config.provider,
            "host": config.host,
            "port": config.port,
            "model": config.model,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout": config.timeout,
        }

        if status:
            info["status"] = {
                "available": status.available,
                "last_check": status.last_check,
                "error": status.error,
                "latency_ms": status.latency_ms,
            }

        # 检查是否跟随其他模型
        if model_type in settings.config.models.defaults:
            target = settings.config.models.defaults[model_type]
            if target != model_type:
                info["follows"] = target

        return info

    def get_all_models_info(self) -> Dict[str, Dict[str, Any]]:
        """获取所有模型信息

        Returns:
            所有模型信息字典
        """
        return {
            "main": self.get_model_info("main"),
            "summary": self.get_model_info("summary"),
            "memory": self.get_model_info("memory"),
        }

    async def close(self):
        """关闭模型路由器"""
        logger.info("关闭模型路由器...")
        self._clients.clear()
        self._status.clear()
        self._initialized = False
        logger.info("模型路由器已关闭")


# 全局模型路由器实例
model_router = ModelRouter()
