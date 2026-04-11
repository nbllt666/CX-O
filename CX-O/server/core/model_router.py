import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from server.core.llm.client import LLMClient, OllamaClient, VLLMClient

logger = logging.getLogger(__name__)


@dataclass
class ModelStatus:
    name: str
    available: bool
    last_check: str
    error: Optional[str] = None
    latency_ms: Optional[float] = None
    config: Optional[Dict] = None


class ModelRouter:
    def __init__(self):
        self._clients: Dict[str, LLMClient] = {}
        self._status: Dict[str, ModelStatus] = {}
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return
        logger.info("初始化模型路由器...")
        model_types = ["main", "summary", "memory"]
        for model_type in model_types:
            try:
                client = self._create_client(model_type)
                if client:
                    self._clients[model_type] = client
                    logger.info(f"模型客户端已创建: {model_type}")
            except Exception as e:
                logger.error(f"创建模型客户端失败 {model_type}: {e}")
        await self.check_all_status()
        await self.warmup_models()
        self._initialized = True
        logger.info("模型路由器初始化完成")

    async def warmup_models(self):
        logger.info("开始预热模型...")
        for model_type, client in self._clients.items():
            if client:
                try:
                    logger.info(f"预热模型 {model_type} ({client.model_name})...")
                    result = await client.chat(messages=[{"role": "user", "content": "hi"}], stream=False)
                    if result.error:
                        logger.warning(f"模型 {model_type} 预热失败: {result.error}")
                    else:
                        logger.info(f"模型 {model_type} 预热成功")
                except Exception as e:
                    logger.warning(f"模型 {model_type} 预热异常: {e}")
        logger.info("模型预热完成")

    def _create_client(self, model_type: str) -> Optional[LLMClient]:
        import os
        provider = os.getenv(f"{model_type.upper()}_PROVIDER", "ollama")
        host = os.getenv(f"{model_type.upper()}_HOST", "http://localhost:11434")
        model = os.getenv(f"{model_type.upper()}_MODEL", "llama3.2")
        temperature = float(os.getenv(f"{model_type.upper()}_TEMPERATURE", "0.7"))
        max_tokens = int(os.getenv(f"{model_type.upper()}_MAX_TOKENS", "4096"))
        if provider == "ollama":
            return OllamaClient(host=host, model=model, temperature=temperature, max_tokens=max_tokens)
        elif provider == "vllm":
            return VLLMClient(host=host, model=model, temperature=temperature, max_tokens=max_tokens)
        return None

    def get_client(self, model_type: str = "main") -> Optional[LLMClient]:
        model_type = model_type.lower()
        return self._clients.get(model_type)

    async def check_status(self, model_type: str) -> ModelStatus:
        config = self.get_client(model_type)
        start_time = datetime.now()
        error_msg = None
        available = False
        try:
            if config and hasattr(config, 'host'):
                async with httpx.AsyncClient(timeout=10.0) as client:
                    if isinstance(config, OllamaClient):
                        response = await client.get(f"{config.host}/api/tags")
                        available = response.status_code == 200
                        if not available:
                            error_msg = f"HTTP {response.status_code}"
        except Exception as e:
            error_msg = str(e)
        latency = (datetime.now() - start_time).total_seconds() * 1000
        status = ModelStatus(name=model_type, available=available, last_check=datetime.now().isoformat(), error=error_msg, latency_ms=round(latency, 2))
        self._status[model_type] = status
        return status

    async def check_all_status(self) -> Dict[str, ModelStatus]:
        for model_type in ["main", "summary", "memory"]:
            await self.check_status(model_type)
        return self._status

    def get_all_status(self) -> Dict[str, ModelStatus]:
        return self._status

    def is_available(self, model_type: str = "main") -> bool:
        status = self._status.get(model_type)
        return status and status.available

    async def chat(self, model_type: str, messages: List[Dict], stream: bool = False, **kwargs) -> Dict[str, Any]:
        client = self.get_client(model_type)
        if not client:
            return {"success": False, "error": f"模型客户端不存在: {model_type}", "content": ""}
        try:
            response = await client.chat(messages, stream, **kwargs)
            return {"success": response.finish_reason != "error", "content": response.content, "finish_reason": response.finish_reason, "usage": getattr(response, "usage", {}), "error": getattr(response, "error", None)}
        except Exception as e:
            logger.error(f"模型对话失败 {model_type}: {e}")
            return {"success": False, "error": str(e), "content": ""}

    async def get_embedding(self, model_type: str, text: str) -> Optional[List[float]]:
        client = self.get_client(model_type)
        if not client:
            return None
        if hasattr(client, "get_embedding"):
            try:
                return await client.get_embedding(text)
            except Exception as e:
                logger.error(f"获取embedding失败: {e}")
                return None
        return None

    async def close(self):
        logger.info("关闭模型路由器...")
        self._clients.clear()
        self._status.clear()
        self._initialized = False
        logger.info("模型路由器已关闭")


model_router = ModelRouter()