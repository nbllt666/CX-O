import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

from server.core.logging_config import get_contextual_logger
from server.core.utils import get_shared_http_client

logger = get_contextual_logger(__name__)


class LLMError(Exception):
    """LLM调用基础错误"""

    def __init__(self, message: str, status_code: int = None, response_text: str = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_text = response_text

    def __str__(self):
        if self.status_code:
            return f"[HTTP {self.status_code}] {self.message}"
        return self.message


@dataclass
class LLMMessage:
    role: str
    content: str
    name: Optional[str] = None


@dataclass
class LLMResponse:
    content: str
    finish_reason: str
    usage: Dict = None
    error: str = None
    error_details: Dict = field(default_factory=dict)
    tool_calls: List[Dict] = field(default_factory=list)
    thinking: Optional[str] = None


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: List[Dict], stream: bool = False, **kwargs) -> LLMResponse:
        pass

    @abstractmethod
    async def stream_chat(self, messages: List[Dict], **kwargs):
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """检查模型是否可用

        Returns:
            是否可用
        """

    @abstractmethod
    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本的向量嵌入

        Args:
            text: 输入文本

        Returns:
            向量列表或None
        """


class OllamaClient(LLMClient):
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        dimension: int = 768,
        api_key: str = None,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.dimension = dimension
        self.api_key = api_key

    def _validate_messages(self, messages: List[Dict]) -> None:
        """验证消息格式"""
        if not messages:
            raise ValueError("消息列表不能为空")

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(f"消息 {i} 必须是字典类型")
            if "role" not in msg:
                raise ValueError(f"消息 {i} 缺少 'role' 字段")
            if "content" not in msg:
                raise ValueError(f"消息 {i} 缺少 'content' 字段")
            if msg["role"] not in ["system", "user", "assistant", "tool"]:
                raise ValueError(f"消息 {i} 的 role 必须是 'system', 'user', 'assistant' 或 'tool'")

    async def chat(self, messages: List[Dict], stream: bool = False, **kwargs) -> LLMResponse:
        """发送聊天请求

        Args:
            messages: 消息列表
            stream: 是否流式响应
            **kwargs: 额外参数，支持 tools (工具列表)

        Returns:
            LLMResponse: 包含响应内容或错误信息
        """
        try:
            # 验证输入
            self._validate_messages(messages)

            # 构建请求体
            request_body = {
                "model": self.model,
                "messages": messages,
                "stream": stream,
                "options": {
                    "temperature": kwargs.get("temperature", self.temperature),
                    "num_predict": kwargs.get("max_tokens", self.max_tokens),
                },
            }

            # 添加工具支持 (如果提供了 tools)
            tools = kwargs.get("tools")
            if tools:
                request_body["tools"] = tools

            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                response = await client.post(f"{self.host}/api/chat", json=request_body)

                if response.status_code == 200:
                    result = response.json()
                    message = result.get("message") or {}

                    # 检查是否有工具调用
                    tool_calls = []
                    if message.get("tool_calls"):
                        tool_calls = message["tool_calls"]

                    # 优先使用 content，thinking 仅作为推理过程不返回
                    content = message.get("content", "")
                    # thinking 字段保留但不作为回复内容，仅用于调试
                    thinking = message.get("thinking", "")
                    if thinking and not content:
                        logger.debug(f"模型返回 thinking 但无 content: {thinking[:100]}...")

                    return LLMResponse(
                        content=content,
                        finish_reason=result.get("done_reason", "stop"),
                        usage={"eval_count": result.get("eval_count", 0)},
                        tool_calls=tool_calls,
                        thinking=thinking if thinking else None,
                    )
                else:
                    # 详细的错误处理
                    error_text = response.text[:500] if response.text else "无响应内容"
                    logger.error(f"Ollama错误: HTTP {response.status_code}, {error_text}")

                    return LLMResponse(
                        content="",
                        finish_reason="error",
                        error=f"HTTP {response.status_code}",
                        error_details={
                            "status_code": response.status_code,
                            "response_text": error_text,
                            "model": self.model,
                            "host": self.host,
                        },
                    )

        except httpx.ConnectError as e:
            error_msg = f"无法连接到Ollama服务器: {self.host}"
            logger.error(f"{error_msg}, {e}")
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e), "host": self.host},
            )
        except httpx.TimeoutException as e:
            error_msg = "Ollama服务器响应超时"
            logger.error(f"{error_msg}, {e}")
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except ValueError as e:
            error_msg = f"请求参数错误: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except Exception as e:
            error_msg = f"Ollama调用失败: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )

    async def stream_chat(self, messages: List[Dict], **kwargs):
        try:
            request_body = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": kwargs.get("temperature", self.temperature),
                    "num_predict": kwargs.get("max_tokens", self.max_tokens),
                },
            }

            if "tools" in kwargs and kwargs["tools"]:
                request_body["tools"] = kwargs["tools"]

            # 添加 Authorization header 如果提供了 API Key
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                async with client.stream(
                    "POST", f"{self.host}/api/chat", json=request_body, headers=headers
                ) as response:
                    async for line in response.aiter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                message = data.get("message", {})

                                # 根据 Ollama 文档正确处理 thinking 和 content
                                thinking = message.get("thinking", "")
                                content = message.get("content", "")

                                # 如果 content 存在，作为最终回复
                                if content:
                                    yield {"type": "content", "content": content}
                                # 如果 content 为空但 thinking 存在，作为思考过程
                                elif thinking:
                                    yield {"type": "thinking", "content": thinking}

                                if data.get("done", False):
                                    break

                                tool_calls = message.get("tool_calls")
                                if tool_calls:
                                    yield {"type": "tool_calls", "tool_calls": tool_calls}
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"Ollama流式调用失败: {e}")
            yield {"type": "error", "content": f"流式调用失败: {e}"}

    @property
    def model_name(self) -> str:
        return f"ollama/{self.model}"

    async def is_available(self) -> bool:
        """检查Ollama模型是否可用"""
        try:
            async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
                response = await client.get(f"{self.host}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """使用Ollama获取文本的向量嵌入"""
        try:
            async with httpx.AsyncClient(timeout=30.0, proxy=None) as client:
                response = await client.post(
                    f"{self.host}/api/embeddings", json={"model": self.model, "prompt": text}
                )

                if response.status_code == 200:
                    result = response.json()
                    return result.get("embedding")
                else:
                    logger.warning(f"Ollama获取embedding失败: HTTP {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Ollama获取embedding失败: {e}")
            return None


class VLLMClient(LLMClient):
    def __init__(
        self,
        host: str = "http://localhost:8000",
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        dimension: int = 768,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        # 防御性 clamp：max_tokens 不能超过 vLLM 模型的 max_model_len（默认 32768）。
        # 配置中若误设 131072 等超大值，vLLM 会返回 400 Bad Request，
        # stream_chat 静默吞掉错误导致 TTS 发空结束标记、用户听不到回复。
        # 32768 是 gemma4-e4b 等模型的常见上限，留余量给 input prompt。
        self.max_tokens = min(int(max_tokens), 32768)
        self.dimension = dimension

    def _validate_messages(self, messages: List[Dict]) -> None:
        """验证消息格式"""
        if not messages:
            raise ValueError("消息列表不能为空")

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(f"消息 {i} 必须是字典类型")
            if "role" not in msg:
                raise ValueError(f"消息 {i} 缺少 'role' 字段")
            if "content" not in msg:
                raise ValueError(f"消息 {i} 缺少 'content' 字段")
            if msg["role"] not in ["system", "user", "assistant", "tool"]:
                raise ValueError(f"消息 {i} 的 role 必须是 'system', 'user', 'assistant' 或 'tool'")

    async def chat(self, messages: List[Dict], stream: bool = False, **kwargs) -> LLMResponse:
        """发送聊天请求

        Args:
            messages: 消息列表
            stream: 是否流式响应
            **kwargs: 额外参数

        Returns:
            LLMResponse: 包含响应内容或错误信息
        """
        try:
            # 验证输入
            self._validate_messages(messages)

            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            # （Windows 上首次构造耗 8s，会让 WS 端到端延迟从 ~10ms 飙到 ~8500ms）
            client = get_shared_http_client()
            # 防御性 clamp max_tokens：调用方可能传入配置中的大值（如 131072），
            # 超过 vLLM 模型 max_model_len（32768）会触发 400 Bad Request；
            # 配置约定 0 表示"不限制"，此时回退到模型上限（vLLM 拒绝 max_tokens=0）
            effective_max_tokens = min(
                int(kwargs.get("max_tokens", self.max_tokens)), 32768
            )
            if effective_max_tokens <= 0:
                effective_max_tokens = 32768
            response = await client.post(
                f"{self.host}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": stream,
                    "temperature": kwargs.get("temperature", self.temperature),
                    "max_tokens": effective_max_tokens,
                },
                timeout=120.0,
            )

            if response.status_code == 200:
                result = response.json()
                choice = result["choices"][0]
                return LLMResponse(
                    content=choice["message"]["content"],
                    finish_reason=choice.get("finish_reason", "stop"),
                    usage=result.get("usage", {}),
                )
            else:
                # 详细的错误处理
                error_text = response.text[:500] if response.text else "无响应内容"
                logger.error(f"VLLM错误: HTTP {response.status_code}, {error_text}")

                return LLMResponse(
                    content="",
                    finish_reason="error",
                    error=f"HTTP {response.status_code}",
                    error_details={
                        "status_code": response.status_code,
                        "response_text": error_text,
                        "model": self.model,
                        "host": self.host,
                    },
                )

        except httpx.ConnectError as e:
            error_msg = f"无法连接到VLLM服务器: {self.host}"
            logger.error(f"{error_msg}, {e}")
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e), "host": self.host},
            )
        except httpx.TimeoutException as e:
            error_msg = "VLLM服务器响应超时"
            logger.error(f"{error_msg}, {e}")
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except (KeyError, IndexError) as e:
            error_msg = f"响应格式错误: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except ValueError as e:
            error_msg = f"请求参数错误: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except Exception as e:
            error_msg = f"VLLM调用失败: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )

    async def stream_chat(self, messages: List[Dict], **kwargs):
        try:
            # 防御性 clamp max_tokens：调用方可能传入配置中的大值（如 131072），
            # 超过 vLLM 模型 max_model_len（32768）会触发 400 Bad Request，
            # 此前 stream_chat 静默吞掉 400 导致 TTS 发空结束标记、用户听不到回复；
            # 配置约定 0 表示"不限制"，此时回退到模型上限（vLLM 拒绝 max_tokens=0）
            effective_max_tokens = min(
                int(kwargs.get("max_tokens", self.max_tokens)), 32768
            )
            if effective_max_tokens <= 0:
                effective_max_tokens = 32768
            request_body = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": effective_max_tokens,
            }

            if "tools" in kwargs and kwargs["tools"]:
                request_body["tools"] = kwargs["tools"]

            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            # （Windows 上首次构造耗 8s，会让 WS 端到端延迟从 ~10ms 飙到 ~8500ms）
            client = get_shared_http_client()
            async with client.stream(
                "POST", f"{self.host}/v1/chat/completions", json=request_body, timeout=120.0
            ) as response:
                # 显式检查状态码：vLLM 在请求体格式错误、模型名不匹配、messages 字段缺失时返回 400
                # 此前缺少此检查导致 400 被静默吞掉（aiter_lines() 不产出，smoother 无输出，TTS 发空结束标记）
                if response.status_code != 200:
                    error_body = await response.aread()
                    error_text = error_body.decode("utf-8", errors="replace")[:1000]
                    logger.error(
                        f"VLLM stream_chat HTTP {response.status_code}: {error_text} | "
                        f"request_body={json.dumps(request_body, ensure_ascii=False)[:500]}"
                    )
                    yield {"type": "error", "content": f"VLLM HTTP {response.status_code}: {error_text}"}
                    return

                # [DIAG-TTFT] 记录第一个 token 产出时间，用于定位 WS 端到端延迟
                _diag_start = time.monotonic()
                _diag_first_token_logged = False
                _diag_token_count = 0
                async for line in response.aiter_lines():
                    if line and line.startswith("data: "):
                        data = line[6:]
                        if data != "[DONE]":
                            try:
                                chunk = json.loads(data)
                                content = chunk["choices"][0]["delta"].get("content", "")

                                if content:
                                    if not _diag_first_token_logged:
                                        _diag_first_token_logged = True
                                        logger.info(
                                            f"[DIAG-TTFT] first token at {(time.monotonic()-_diag_start)*1000:.1f}ms: '{content[:20]}'"
                                        )
                                    _diag_token_count += 1
                                    yield content

                                delta = chunk["choices"][0].get("delta", {})
                                tool_calls = delta.get("tool_calls")
                                if tool_calls:
                                    yield {"tool_calls": tool_calls}
                            except json.JSONDecodeError:
                                continue
                logger.info(
                    f"[DIAG-TTFT] stream done: {_diag_token_count} tokens, "
                    f"total {(time.monotonic()-_diag_start)*1000:.1f}ms"
                )
        except Exception as e:
            logger.error(f"VLLM流式调用失败: {e}")

    @property
    def model_name(self) -> str:
        return f"vllm/{self.model}"

    async def is_available(self) -> bool:
        """检查VLLM模型是否可用"""
        try:
            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            # VLLM 使用 /health 端点检查健康状态
            response = await client.get(f"{self.host}/health", timeout=10.0)
            return response.status_code == 200
        except Exception:
            return False

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """使用VLLM获取文本的向量嵌入

        VLLM 支持通过 /v1/embeddings 端点获取 embedding
        """
        try:
            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.post(
                f"{self.host}/v1/embeddings", json={"model": self.model, "input": text},
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                # OpenAI 格式返回 embedding 在 data[0].embedding
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0].get("embedding")
                return None
            else:
                logger.warning(f"VLLM获取embedding失败: HTTP {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"VLLM获取embedding失败: {e}")
            return None


class TRTLLMClient(LLMClient):
    def __init__(
        self,
        host: str = "http://localhost:8000",
        model: str = "default",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        dimension: int = 768,
        api_key: str = None,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.dimension = dimension
        self.api_key = api_key

    def _validate_messages(self, messages: List[Dict]) -> None:
        if not messages:
            raise ValueError("消息列表不能为空")
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise ValueError(f"消息 {i} 必须是字典类型")
            if "role" not in msg:
                raise ValueError(f"消息 {i} 缺少 'role' 字段")
            if "content" not in msg:
                raise ValueError(f"消息 {i} 缺少 'content' 字段")
            if msg["role"] not in ["system", "user", "assistant", "tool"]:
                raise ValueError(f"消息 {i} 的 role 必须是 'system', 'user', 'assistant' 或 'tool'")

    async def chat(self, messages: List[Dict], stream: bool = False, **kwargs) -> LLMResponse:
        try:
            self._validate_messages(messages)

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                response = await client.post(
                    f"{self.host}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": stream,
                        "temperature": kwargs.get("temperature", self.temperature),
                        "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                    },
                    headers=headers,
                )

                if response.status_code == 200:
                    result = response.json()
                    choice = result["choices"][0]
                    return LLMResponse(
                        content=choice["message"]["content"],
                        finish_reason=choice.get("finish_reason", "stop"),
                        usage=result.get("usage", {}),
                    )
                else:
                    error_text = response.text[:500] if response.text else "无响应内容"
                    logger.error(f"TRT-LLM错误: HTTP {response.status_code}, {error_text}")
                    return LLMResponse(
                        content="",
                        finish_reason="error",
                        error=f"HTTP {response.status_code}",
                        error_details={
                            "status_code": response.status_code,
                            "response_text": error_text,
                            "model": self.model,
                            "host": self.host,
                        },
                    )

        except httpx.ConnectError as e:
            error_msg = f"无法连接到TRT-LLM服务器: {self.host}"
            logger.error(f"{error_msg}, {e}")
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e), "host": self.host},
            )
        except httpx.TimeoutException as e:
            error_msg = "TRT-LLM服务器响应超时"
            logger.error(f"{error_msg}, {e}")
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except (KeyError, IndexError) as e:
            error_msg = f"响应格式错误: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except ValueError as e:
            error_msg = f"请求参数错误: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )
        except Exception as e:
            error_msg = f"TRT-LLM调用失败: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                finish_reason="error",
                error=error_msg,
                error_details={"exception": str(e)},
            )

    async def stream_chat(self, messages: List[Dict], **kwargs):
        try:
            request_body = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            }

            if "tools" in kwargs and kwargs["tools"]:
                request_body["tools"] = kwargs["tools"]

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
                async with client.stream(
                    "POST", f"{self.host}/v1/chat/completions", json=request_body, headers=headers
                ) as response:
                    async for line in response.aiter_lines():
                        if line and line.startswith("data: "):
                            data = line[6:]
                            if data != "[DONE]":
                                try:
                                    chunk = json.loads(data)
                                    content = chunk["choices"][0]["delta"].get("content", "")
                                    if content:
                                        yield content

                                    delta = chunk["choices"][0].get("delta", {})
                                    tool_calls = delta.get("tool_calls")
                                    if tool_calls:
                                        yield {"tool_calls": tool_calls}
                                except json.JSONDecodeError:
                                    continue
        except Exception as e:
            logger.error(f"TRT-LLM流式调用失败: {e}")

    @property
    def model_name(self) -> str:
        return f"trtllm/{self.model}"

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0, proxy=None) as client:
                response = await client.get(f"{self.host}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=30.0, proxy=None) as client:
                response = await client.post(
                    f"{self.host}/v1/embeddings",
                    json={"model": self.model, "input": text},
                    headers=headers,
                )

                if response.status_code == 200:
                    result = response.json()
                    if "data" in result and len(result["data"]) > 0:
                        return result["data"][0].get("embedding")
                    return None
                else:
                    logger.warning(f"TRT-LLM获取embedding失败: HTTP {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"TRT-LLM获取embedding失败: {e}")
            return None


class LLMFactory:
    _clients: Dict[str, LLMClient] = {}

    @classmethod
    def create_client(cls, provider: str = "ollama", **kwargs) -> LLMClient:
        key = f"{provider}:{kwargs.get('model', 'default')}"

        if key in cls._clients:
            return cls._clients[key]

        if provider == "ollama":
            client = OllamaClient(**kwargs)
        elif provider == "vllm":
            client = VLLMClient(**kwargs)
        elif provider == "trtllm":
            client = TRTLLMClient(**kwargs)
        else:
            raise ValueError(f"不支持的LLM提供商: {provider}")

        cls._clients[key] = client
        return client

    @classmethod
    def get_client(cls, provider: str = "ollama", **kwargs) -> LLMClient:
        return cls.create_client(provider, **kwargs)

    @classmethod
    def clear_cache(cls):
        cls._clients.clear()
