"""LLM 客户端抽象与 HTTP 实现。

定义统一的 LLMClient 抽象基类、OpenAI 兼容 HTTP 客户端及请求/响应数据
结构，供聊天管线与各类服务调用模型，通过 get_shared_http_client 复用连接池
以避免逐请求建连。
"""
import json
import threading
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
class LLMResponse:
    """LLM 调用结果数据类：封装响应内容、结束原因、用量与错误信息。"""

    content: str
    finish_reason: str
    usage: Dict = None
    error: str = None
    error_details: Dict = field(default_factory=dict)
    tool_calls: List[Dict] = field(default_factory=list)
    thinking: Optional[str] = None


class LLMClient(ABC):
    """LLM 客户端抽象基类：定义聊天、流式聊天、模型名、可用性与嵌入的统一接口。"""

    @abstractmethod
    async def chat(self, messages: List[Dict], stream: bool = False, **kwargs) -> LLMResponse:
        """发送聊天请求并返回响应。"""
        pass

    @abstractmethod
    async def stream_chat(self, messages: List[Dict], **kwargs):
        """流式聊天：逐块产出内容。"""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前模型的标识名称。"""
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
    """Ollama 客户端：通过 Ollama HTTP API 实现聊天、流式聊天与嵌入。"""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        dimension: int = 768,
        api_key: str = None,
        top_p: Optional[float] = None,
    ):
        """初始化 Ollama 客户端，保存服务地址与模型参数。"""
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.dimension = dimension
        self.api_key = api_key
        # 核采样参数：None 表示不启用，请求体中不注入
        self.top_p = top_p

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

            # 核采样参数：仅当配置或调用方显式提供时注入
            top_p = kwargs.get("top_p", self.top_p)
            if top_p is not None:
                request_body["options"]["top_p"] = top_p

            # 添加工具支持 (如果提供了 tools)
            tools = kwargs.get("tools")
            if tools:
                request_body["tools"] = tools

            # A7: 与 stream_chat 对齐补鉴权头（api_key 存在时加 Authorization）
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            client = get_shared_http_client()
            response = await client.post(
                f"{self.host}/api/chat", json=request_body, headers=headers, timeout=120.0
            )

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
        """流式聊天：逐块产出内容、思考过程或工具调用。"""
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

            # 核采样参数：仅当配置或调用方显式提供时注入
            top_p = kwargs.get("top_p", self.top_p)
            if top_p is not None:
                request_body["options"]["top_p"] = top_p

            if "tools" in kwargs and kwargs["tools"]:
                request_body["tools"] = kwargs["tools"]

            # 添加 Authorization header 如果提供了 API Key
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            client = get_shared_http_client()
            async with client.stream(
                "POST", f"{self.host}/api/chat", json=request_body, headers=headers
            ) as response:
                # 显式检查状态码：非 2xx 时 aiter_lines() 不产出，此前被静默吞掉
                # 导致调用方无任何输出，无法与"空输出"区分。参照 VLLMClient 做法。
                # 仅对真实 int 状态码做判定（测试用之 lenient MagicMock 无 status_code 视为成功）。
                if isinstance(response.status_code, int) and response.status_code != 200:
                    error_body = await response.aread()
                    error_text = error_body.decode("utf-8", errors="replace")[:1000]
                    logger.error(
                        f"Ollama stream_chat HTTP {response.status_code}: {error_text}"
                    )
                    yield {
                        "type": "error",
                        "content": f"Ollama HTTP {response.status_code}: {error_text}",
                    }
                    return
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

                            # A2: tool_calls 提取必须先于 done 判断——Ollama 在收尾
                            # 分片（done=true）携带 tool_calls，先 break 会永久丢失
                            tool_calls = message.get("tool_calls")
                            if tool_calls:
                                yield {"type": "tool_calls", "tool_calls": tool_calls}

                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Ollama流式调用失败: {e}")
            yield {"type": "error", "content": f"流式调用失败: {e}"}

    @property
    def model_name(self) -> str:
        """返回 Ollama 模型标识。"""
        return f"ollama/{self.model}"

    async def is_available(self) -> bool:
        """检查Ollama模型是否可用"""
        try:
            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.get(f"{self.host}/api/tags", timeout=10.0)
            return response.status_code == 200
        except Exception:
            return False

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """使用Ollama获取文本的向量嵌入"""
        try:
            # A7: 与 stream_chat 对齐补鉴权头（api_key 存在时加 Authorization）
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model, "prompt": text},
                headers=headers,
                timeout=30.0,
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
    """VLLM 客户端：通过 vLLM 的 OpenAI 兼容接口实现聊天、流式聊天与嵌入。"""

    def __init__(
        self,
        host: str = "http://localhost:8000",
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        dimension: int = 768,
        lora_request: Optional[Dict] = None,
        top_p: Optional[float] = None,
    ):
        """初始化 VLLM 客户端，并对 max_tokens 做防御性上限钳制。

        Args:
            lora_request: 可选 vLLM /v1/chat/completions 的 lora_request 结构
                （如 {"model": "adapter", "lora_weight": 1.0}）。为 None 或空时
                恒不附加 lora_request 字段 → 向后兼容。
        """
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        # 核采样参数：None 表示不启用，请求体中不注入
        self.top_p = top_p
        self.lora_request = lora_request or None
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
            # 组装请求体；仅当配置了 lora_request 才附加该字段（向后兼容）
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": stream,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": effective_max_tokens,
            }
            # 核采样参数：仅当配置或调用方显式提供时注入
            top_p = kwargs.get("top_p", self.top_p)
            if top_p is not None:
                payload["top_p"] = top_p
            if self.lora_request:
                payload["lora_request"] = self.lora_request
            response = await client.post(
                f"{self.host}/v1/chat/completions",
                json=payload,
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
        """流式聊天：逐块产出内容或工具调用，并记录首 token 延迟。"""
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

            # 核采样参数：仅当配置或调用方显式提供时注入
            top_p = kwargs.get("top_p", self.top_p)
            if top_p is not None:
                request_body["top_p"] = top_p

            if "tools" in kwargs and kwargs["tools"]:
                request_body["tools"] = kwargs["tools"]

            # 仅当配置了 lora_request 才附加该字段（向后兼容）
            if self.lora_request:
                request_body["lora_request"] = self.lora_request

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
                                    yield {"type": "tool_calls", "tool_calls": tool_calls}
                            except json.JSONDecodeError:
                                continue
                logger.info(
                    f"[DIAG-TTFT] stream done: {_diag_token_count} tokens, "
                    f"total {(time.monotonic()-_diag_start)*1000:.1f}ms"
                )
        except Exception as e:
            logger.error(f"VLLM流式调用失败: {e}")
            # #1（CX-O问题汇总报告）: 顶层异常曾静默吞掉不产出任何块，调用方
            # 无法区分「空输出」与「调用失败」，TTS 等下游会发空结束标记。
            # 与 OllamaClient 对齐：显式产出 error 块结束流。
            yield {"type": "error", "content": f"VLLM流式调用失败: {e}"}

    @property
    def model_name(self) -> str:
        """返回 VLLM 模型标识。"""
        return f"vllm/{self.model}"

    async def load_lora_adapter(self, adapter_name: str, lora_path: str) -> Dict:
        """调用 vLLM /load_lora_adapter 端点在运行时加载 LoRA adapter。

        Args:
            adapter_name: LoRA adapter 名称（在后续 lora_request.model 中引用）
            lora_path: LoRA 权重目录/文件路径

        Returns:
            结果字典：{"ok": True, "adapter_name": ..., "status_code": 200} 表示成功；
            失败返回 {"ok": False, "adapter_name": ..., "status_code"/"error": ...}，
            超时/连接失败同样以可读 error 返回，不抛异常。
        """
        payload = {"lora_name": adapter_name, "lora_path": lora_path}
        try:
            # 预热好的 shared HTTP client；LoRA 加载通常耗时较长，放宽超时
            client = get_shared_http_client()
            response = await client.post(
                f"{self.host}/load_lora_adapter", json=payload, timeout=300.0
            )
            if response.status_code == 200:
                return {"ok": True, "adapter_name": adapter_name, "status_code": 200}
            error_text = response.text[:500] if response.text else "load_lora_adapter failed"
            logger.error(
                f"VLLM load_lora_adapter HTTP {response.status_code}: {error_text}"
            )
            return {
                "ok": False,
                "adapter_name": adapter_name,
                "status_code": response.status_code,
                "error": f"HTTP {response.status_code}: {error_text}",
            }
        except httpx.TimeoutException as e:
            return {"ok": False, "adapter_name": adapter_name, "error": f"加载超时: {e}"}
        except Exception as e:
            logger.error(f"VLLM load_lora_adapter 调用失败: {e}")
            return {"ok": False, "adapter_name": adapter_name, "error": str(e)}

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
    """TRT-LLM 客户端：通过 TensorRT-LLM 的 OpenAI 兼容接口实现聊天、流式聊天与嵌入。"""

    def __init__(
        self,
        host: str = "http://localhost:8000",
        model: str = "default",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        dimension: int = 768,
        api_key: str = None,
    ):
        """初始化 TRT-LLM 客户端，保存服务地址与模型参数。"""
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.dimension = dimension
        self.api_key = api_key

    def _validate_messages(self, messages: List[Dict]) -> None:
        """验证消息列表的角色与必填字段格式。"""
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
        """发送聊天请求。"""
        try:
            self._validate_messages(messages)

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
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
        """流式聊天：逐块产出内容或工具调用。"""
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

            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            async with client.stream(
                "POST", f"{self.host}/v1/chat/completions", json=request_body, headers=headers
            ) as response:
                # 显式检查状态码（与 VLLMClient.stream_chat 对齐）：此前缺少该检查，
                # 非 200 响应体没有 SSE data 行，aiter_lines() 零产出，失败被当作
                # "空回复"继续走播报链路，用户只听到静音结束标记而无错误提示。
                if response.status_code != 200:
                    error_body = await response.aread()
                    error_text = error_body.decode("utf-8", errors="replace")[:1000]
                    logger.error(
                        f"TRT-LLM stream_chat HTTP {response.status_code}: {error_text} | "
                        f"request_body={json.dumps(request_body, ensure_ascii=False)[:500]}"
                    )
                    yield {"type": "error", "content": f"TRT-LLM HTTP {response.status_code}: {error_text}"}
                    return

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
                                    yield {"type": "tool_calls", "tool_calls": tool_calls}
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"TRT-LLM流式调用失败: {e}")
            # #29（差异审查登记）: 顶层异常静默吞掉，调用方无法区分「空输出」与
            # 「失败」；与 Ollama/VLLM 对齐，显式产出 error 块结束流。
            yield {"type": "error", "content": f"TRT-LLM流式调用失败: {e}"}

    @property
    def model_name(self) -> str:
        """返回 TRT-LLM 模型标识。"""
        return f"trtllm/{self.model}"

    async def is_available(self) -> bool:
        """检查 TRT-LLM 模型是否可用。"""
        try:
            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.get(f"{self.host}/health", timeout=10.0)
            return response.status_code == 200
        except Exception:
            return False

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """使用 TRT-LLM 获取文本的向量嵌入。"""
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # 使用预热好的 shared HTTP client，避免每次调用都重新构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.post(
                f"{self.host}/v1/embeddings",
                json={"model": self.model, "input": text},
                headers=headers,
                timeout=30.0,
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
    """LLM 客户端工厂：按 provider 创建并缓存客户端实例。"""

    _clients: Dict[str, LLMClient] = {}
    # A10: 类级锁保护 _clients 读写（参照 EmbeddingFactory._lock 模式），
    # 防止并发 create_client 重复创建实例
    _lock = threading.Lock()

    @classmethod
    def create_client(cls, provider: str = "ollama", **kwargs) -> LLMClient:
        """按 provider 创建 LLM 客户端，命中缓存直接返回。

        Args:
            provider: 提供商（ollama / vllm / trtllm）
            **kwargs: 客户端初始化参数（含 model 用于缓存键）

        Returns:
            LLMClient: 客户端实例

        Raises:
            ValueError: 不支持的提供商
        """
        # 缓存键并入 host 与 lora_request：此前仅 provider:model，同一模型指向不同
        # host（或同 host 不同 LoRA 适配）时会错误命中第一个实例的缓存。
        # lora_request 为 dict（见 VLLMClient.__init__ 声明），直接 str() 拼接存在两个
        # 缺陷：①同内容不同插入序的 dict 生成不同键 → 缓存碎片化永不命中；②若为
        # 非 dict 自定义对象（如 vLLM SDK LoRARequest），str() 含内存地址 → 永不命中。
        # 故以 sort_keys 的 JSON 序列化生成稳定键段，不可 JSON 化对象以 repr 兜底；
        # None/空容器保持 falsy → ""，与 VLLMClient「空配置恒不附加 lora」语义一致。
        lora = kwargs.get("lora_request")
        if lora:
            try:
                lora_key = json.dumps(lora, sort_keys=True, ensure_ascii=False, default=repr)
            except (TypeError, ValueError):
                lora_key = repr(lora)
        else:
            lora_key = ""
        # A10: 缓存键并入 temperature/max_tokens/api_key——同一模型但不同采样
        # 参数或不同凭据的实例不得互串缓存；api_key 参与键但不写日志（避免凭据泄露）
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 4096)
        api_key = kwargs.get("api_key") or ""
        key = "{}:{}:{}:{}:{}:{}:{}".format(
            provider,
            kwargs.get("model", "default"),
            kwargs.get("host", "") or "",
            lora_key,
            temperature,
            max_tokens,
            api_key,
        )

        with cls._lock:
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
    def clear_cache(cls):
        """清空已缓存的客户端实例。"""
        with cls._lock:
            cls._clients.clear()
