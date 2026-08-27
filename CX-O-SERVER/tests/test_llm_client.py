"""server.core.llm.client (LLM 客户端) 单元测试。

通过 mock httpx.AsyncClient 隔离网络，覆盖 OllamaClient 的消息校验、
chat 成功/错误/超时/连接失败、stream_chat 流式解析、is_available、
get_embedding、model_name 等核心逻辑。

运行：python -m pytest tests/test_llm_client.py -v
"""
import json

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from server.core.llm.client import LLMResponse, OllamaClient, TRTLLMClient, VLLMClient


@pytest.fixture
def client():
    return OllamaClient(host="http://localhost:11434", model="qwen3:latest")


# ---------------------------------------------------------------- 消息校验
class TestValidateMessages:
    def test_empty_messages(self, client):
        with pytest.raises(ValueError, match="不能为空"):
            client._validate_messages([])

    def test_non_dict_message(self, client):
        with pytest.raises(ValueError, match="必须是字典类型"):
            client._validate_messages(["not a dict"])

    def test_missing_role(self, client):
        with pytest.raises(ValueError, match="缺少 'role'"):
            client._validate_messages([{"content": "hi"}])

    def test_missing_content(self, client):
        with pytest.raises(ValueError, match="缺少 'content'"):
            client._validate_messages([{"role": "user"}])

    def test_invalid_role(self, client):
        with pytest.raises(ValueError, match="role 必须是"):
            client._validate_messages([{"role": "admin", "content": "hi"}])

    def test_valid_messages(self, client):
        # 不应抛异常
        client._validate_messages(
            [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "tool", "content": "result"},
            ]
        )


# ---------------------------------------------------------------- chat
class TestChat:
    def _mock_post(self, monkeypatch, status=200, payload=None):
        """替换 get_shared_http_client().post 为返回指定响应的 mock。"""
        mock_response = MagicMock()
        mock_response.status_code = status
        mock_response.json.return_value = payload or {
            "message": {"content": "你好", "thinking": "思考"},
            "done_reason": "stop",
            "eval_count": 10,
        }
        mock_response.text = "error body"

        async_client = AsyncMock()
        async_client.post.return_value = mock_response

        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        return async_client, mock_response

    @pytest.mark.asyncio
    async def test_chat_success(self, monkeypatch, client):
        async_client, mock_response = self._mock_post(monkeypatch)
        resp = await client.chat([{"role": "user", "content": "hi"}])
        assert isinstance(resp, LLMResponse)
        assert resp.content == "你好"
        assert resp.finish_reason == "stop"
        assert resp.usage == {"eval_count": 10}
        # 请求体应包含模型与消息
        _, kwargs = async_client.post.call_args
        assert kwargs["json"]["model"] == "qwen3:latest"

    @pytest.mark.asyncio
    async def test_chat_non_200_returns_error(self, monkeypatch, client):
        _, mock_response = self._mock_post(monkeypatch, status=500)
        resp = await client.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert resp.error == "HTTP 500"
        assert resp.error_details["status_code"] == 500

    @pytest.mark.asyncio
    async def test_chat_connect_error(self, monkeypatch, client):
        async_client = AsyncMock()
        async_client.post.side_effect = httpx.ConnectError("refused")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        resp = await client.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert "无法连接" in resp.error

    @pytest.mark.asyncio
    async def test_chat_timeout_error(self, monkeypatch, client):
        async_client = AsyncMock()
        async_client.post.side_effect = httpx.TimeoutException("timeout")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        resp = await client.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert "超时" in resp.error

    @pytest.mark.asyncio
    async def test_chat_invalid_messages(self, monkeypatch, client):
        # 不触发网络，直接因校验失败返回错误
        resp = await client.chat([])
        assert resp.finish_reason == "error"
        assert "请求参数错误" in resp.error

    @pytest.mark.asyncio
    async def test_chat_with_tools(self, monkeypatch, client):
        async_client, _ = self._mock_post(monkeypatch)
        await client.chat(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "calc"}}],
        )
        _, kwargs = async_client.post.call_args
        assert kwargs["json"]["tools"] == [{"type": "function", "function": {"name": "calc"}}]

    @pytest.mark.asyncio
    async def test_chat_top_p_injected_when_set(self, monkeypatch, client):
        async_client, _ = self._mock_post(monkeypatch)
        client.top_p = 0.9
        await client.chat([{"role": "user", "content": "hi"}])
        _, kwargs = async_client.post.call_args
        assert kwargs["json"]["options"]["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_chat_top_p_omitted_when_none(self, monkeypatch, client):
        async_client, _ = self._mock_post(monkeypatch)
        await client.chat([{"role": "user", "content": "hi"}])
        _, kwargs = async_client.post.call_args
        assert "top_p" not in kwargs["json"]["options"]

    @pytest.mark.asyncio
    async def test_chat_top_p_kwargs_override(self, monkeypatch, client):
        async_client, _ = self._mock_post(monkeypatch)
        client.top_p = 0.9
        await client.chat([{"role": "user", "content": "hi"}], top_p=0.5)
        _, kwargs = async_client.post.call_args
        assert kwargs["json"]["options"]["top_p"] == 0.5


# ---------------------------------------------------------------- stream_chat
class TestStreamChat:
    @pytest.mark.asyncio
    async def test_stream_yields_content_and_thinking(self, monkeypatch, client):
        lines = [
            json.dumps({"message": {"thinking": "推理..."}, "done": False}),
            json.dumps({"message": {"content": "你好"}, "done": False}),
            json.dumps({"message": {"content": "世界"}, "done": True}),
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def _aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = _aiter_lines

        async_client = AsyncMock()
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        async_client.stream = MagicMock(return_value=stream_ctx)
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )

        chunks = [chunk async for chunk in client.stream_chat([{"role": "user", "content": "hi"}])]
        types = [(c["type"], c["content"]) for c in chunks]
        assert types == [
            ("thinking", "推理..."),
            ("content", "你好"),
            ("content", "世界"),
        ]

    @pytest.mark.asyncio
    async def test_stream_top_p_injected_when_set(self, monkeypatch, client):
        """stream_chat 路径：配置 top_p 时注入 options，未配置时省略。"""
        lines = [json.dumps({"message": {"content": "ok"}, "done": True})]
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def _aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = _aiter_lines

        async_client = AsyncMock()
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        async_client.stream = MagicMock(return_value=stream_ctx)
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )

        client.top_p = 0.9
        _ = [c async for c in client.stream_chat([{"role": "user", "content": "hi"}])]
        _, kwargs = async_client.stream.call_args
        assert kwargs["json"]["options"]["top_p"] == 0.9

        client.top_p = None
        _ = [c async for c in client.stream_chat([{"role": "user", "content": "hi"}])]
        _, kwargs = async_client.stream.call_args
        assert "top_p" not in kwargs["json"]["options"]

    @pytest.mark.asyncio
    async def test_stream_skips_bad_json(self, monkeypatch, client):
        lines = ["not json", json.dumps({"message": {"content": "ok"}, "done": True})]
        mock_response = MagicMock()

        async def _aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = _aiter_lines
        async_client = AsyncMock()
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        async_client.stream = MagicMock(return_value=stream_ctx)
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        chunks = [c async for c in client.stream_chat([{"role": "user", "content": "hi"}])]
        assert [c["content"] for c in chunks] == ["ok"]

    @pytest.mark.asyncio
    async def test_stream_non_2xx_yields_error(self, monkeypatch, client):
        """非 2xx 状态码应产出 error 块而非静默无输出（与 VLLMClient 对齐）。"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.aread = AsyncMock(return_value=b"internal boom")
        async_client = AsyncMock()
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        async_client.stream = MagicMock(return_value=stream_ctx)
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        chunks = [c async for c in client.stream_chat([{"role": "user", "content": "hi"}])]
        assert len(chunks) == 1
        assert chunks[0]["type"] == "error"
        assert "Ollama HTTP 500" in chunks[0]["content"]


# ---------------------------------------------------------------- 属性与可用性
class TestMisc:
    def test_model_name(self, client):
        assert client.model_name == "ollama/qwen3:latest"

    @pytest.mark.asyncio
    async def test_is_available_true(self, monkeypatch, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        async_client = AsyncMock()
        async_client.get.return_value = mock_response
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        assert await client.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false_on_exception(self, monkeypatch, client):
        async_client = AsyncMock()
        async_client.get.side_effect = Exception("down")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        assert await client.is_available() is False

    @pytest.mark.asyncio
    async def test_get_embedding_success(self, monkeypatch, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1, 0.2]}
        async_client = AsyncMock()
        async_client.post.return_value = mock_response
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        assert await client.get_embedding("text") == [0.1, 0.2]

    @pytest.mark.asyncio
    async def test_get_embedding_failure(self, monkeypatch, client):
        async_client = AsyncMock()
        async_client.post.side_effect = Exception("down")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        assert await client.get_embedding("text") is None


# ---------------------------------------------------------------- VLLMClient
class TestVLLMClient:
    def test_constructor_clamps_max_tokens(self):
        """超大 max_tokens 被防御性 clamp 到 32768。"""
        c = VLLMClient(max_tokens=131072)
        assert c.max_tokens == 32768

    def test_constructor_keeps_normal_max_tokens(self):
        c = VLLMClient(max_tokens=2048)
        assert c.max_tokens == 2048

    def _mock_shared_client(self, monkeypatch, status=200, payload=None):
        mock_response = MagicMock()
        mock_response.status_code = status
        mock_response.json.return_value = payload or {
            "choices": [{"message": {"content": "vllm回复"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 5},
        }
        mock_response.text = "error body"
        shared = AsyncMock()
        shared.post.return_value = mock_response
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: shared
        )
        return shared, mock_response

    @pytest.mark.asyncio
    async def test_chat_success(self, monkeypatch):
        c = VLLMClient()
        shared, _ = self._mock_shared_client(monkeypatch)
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.content == "vllm回复"
        assert resp.finish_reason == "stop"
        assert resp.usage == {"total_tokens": 5}
        _, kwargs = shared.post.call_args
        assert kwargs["json"]["model"] == c.model

    @pytest.mark.asyncio
    async def test_chat_clamps_max_tokens_in_request(self, monkeypatch):
        c = VLLMClient()
        shared, _ = self._mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}], max_tokens=131072)
        _, kwargs = shared.post.call_args
        assert kwargs["json"]["max_tokens"] == 32768

    @pytest.mark.asyncio
    async def test_chat_zero_max_tokens_falls_back(self, monkeypatch):
        c = VLLMClient()
        shared, _ = self._mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}], max_tokens=0)
        _, kwargs = shared.post.call_args
        assert kwargs["json"]["max_tokens"] == 32768

    @pytest.mark.asyncio
    async def test_chat_http_error(self, monkeypatch):
        c = VLLMClient()
        self._mock_shared_client(monkeypatch, status=500)
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert resp.error == "HTTP 500"

    @pytest.mark.asyncio
    async def test_chat_connect_error(self, monkeypatch):
        c = VLLMClient()
        shared = AsyncMock()
        shared.post.side_effect = httpx.ConnectError("refused")
        monkeypatch.setattr("server.core.llm.client.get_shared_http_client", lambda: shared)
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert "无法连接" in resp.error

    @pytest.mark.asyncio
    async def test_chat_malformed_response(self, monkeypatch):
        c = VLLMClient()
        self._mock_shared_client(monkeypatch, payload={"choices": []})
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert "响应格式错误" in resp.error

    @pytest.mark.asyncio
    async def test_chat_top_p_injected_when_set(self, monkeypatch):
        c = VLLMClient(top_p=0.9)
        shared, _ = self._mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}])
        _, kwargs = shared.post.call_args
        assert kwargs["json"]["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_chat_top_p_omitted_when_none(self, monkeypatch):
        c = VLLMClient()
        shared, _ = self._mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}])
        _, kwargs = shared.post.call_args
        assert "top_p" not in kwargs["json"]

    @pytest.mark.asyncio
    async def test_stream_top_p_injected_when_set(self, monkeypatch):
        """VLLM stream_chat 路径：配置 top_p 时注入请求体，未配置时省略。"""
        lines = [
            "data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
            "data: [DONE]",
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def _aiter_lines():
            for line in lines:
                yield line

        mock_response.aiter_lines = _aiter_lines

        shared = AsyncMock()
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        shared.stream = MagicMock(return_value=stream_ctx)
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: shared
        )

        c = VLLMClient(top_p=0.9)
        _ = [chunk async for chunk in c.stream_chat([{"role": "user", "content": "hi"}])]
        _, kwargs = shared.stream.call_args
        assert kwargs["json"]["top_p"] == 0.9

        c2 = VLLMClient()
        _ = [chunk async for chunk in c2.stream_chat([{"role": "user", "content": "hi"}])]
        _, kwargs = shared.stream.call_args
        assert "top_p" not in kwargs["json"]


# ---------------------------------------------------------------- TRTLLMClient
class TestTRTLLMClient:
    def test_model_name(self):
        c = TRTLLMClient(model="trt-model")
        assert c.model_name == "trtllm/trt-model"

    def _mock_post(self, monkeypatch, status=200, payload=None):
        mock_response = MagicMock()
        mock_response.status_code = status
        mock_response.json.return_value = payload or {
            "choices": [{"message": {"content": "trt回复"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 3},
        }
        mock_response.text = "error body"
        async_client = AsyncMock()
        async_client.post.return_value = mock_response
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        return async_client

    @pytest.mark.asyncio
    async def test_chat_success(self, monkeypatch):
        c = TRTLLMClient()
        self._mock_post(monkeypatch)
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.content == "trt回复"
        assert resp.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_http_error(self, monkeypatch):
        c = TRTLLMClient()
        self._mock_post(monkeypatch, status=500)
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert resp.error == "HTTP 500"

    @pytest.mark.asyncio
    async def test_chat_connect_error(self, monkeypatch):
        c = TRTLLMClient()
        async_client = AsyncMock()
        async_client.post.side_effect = httpx.ConnectError("refused")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        resp = await c.chat([{"role": "user", "content": "hi"}])
        assert resp.finish_reason == "error"
        assert "无法连接" in resp.error

    @pytest.mark.asyncio
    async def test_chat_includes_api_key_header(self, monkeypatch):
        c = TRTLLMClient(api_key="secret")
        async_client = self._mock_post(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}])
        _, kwargs = async_client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer secret"


class TestTRTLLMStreamNon200:
    """TRTLLM stream_chat 非 200 显式错误分支（与 VLLMClient 对齐，M 修复）。"""

    @pytest.mark.asyncio
    async def test_stream_non_200_yields_error_block(self, monkeypatch):
        from types import SimpleNamespace

        class _Resp:
            status_code = 502
            text = ""

            async def aread(self):
                return b'{"error":"upstream gone"}'

            async def aiter_lines(self):  # pragma: no cover —— 走到这里即为缺陷
                raise AssertionError("非 200 响应不应进入 SSE 流解析")
                yield  # noqa: unreachable（使本函数成为生成器）

        class _Ctx:
            def __init__(self, r):
                self.r = r

            async def __aenter__(self):
                return self.r

            async def __aexit__(self, *exc):
                return False

        fake_client = SimpleNamespace(stream=lambda *a, **k: _Ctx(_Resp()))
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: fake_client
        )
        c = TRTLLMClient(model="trt-m")
        chunks = [ch async for ch in c.stream_chat([{"role": "user", "content": "hi"}])]
        # 失败不再被当作"空回复"静默结束：必须产出显式 error 终态块
        assert len(chunks) == 1
        assert chunks[0]["type"] == "error"
        assert "HTTP 502" in chunks[0]["content"]
        assert "upstream gone" in chunks[0]["content"]


class TestLLMFactoryCacheKey:
    """工厂缓存键并入 host / lora_request（M 修复：不同 host 不再错误命中同一实例）。"""

    def setup_method(self):
        from server.core.llm.client import LLMFactory

        LLMFactory.clear_cache()

    def teardown_method(self):
        from server.core.llm.client import LLMFactory

        LLMFactory.clear_cache()

    def test_same_args_hit_same_instance(self):
        from server.core.llm.client import LLMFactory

        a = LLMFactory.create_client("vllm", model="m", host="http://a")
        b = LLMFactory.create_client("vllm", model="m", host="http://a")
        assert a is b

    def test_different_host_creates_distinct_instances(self):
        from server.core.llm.client import LLMFactory

        a = LLMFactory.create_client("vllm", model="m", host="http://a")
        b = LLMFactory.create_client("vllm", model="m", host="http://b")
        assert a is not b
        assert a.host == "http://a"
        assert b.host == "http://b"

    def test_different_lora_request_creates_distinct_instances(self):
        from server.core.llm.client import LLMFactory

        plain = LLMFactory.create_client("vllm", model="m", host="http://a")
        adapted = LLMFactory.create_client(
            "vllm", model="m", host="http://a", lora_request={"model": "adapter-x"}
        )
        again = LLMFactory.create_client(
            "vllm", model="m", host="http://a", lora_request={"model": "adapter-x"}
        )
        assert plain is not adapted
        assert adapted is again

    def test_lora_dict_key_order_insensitive_hits_same_cache(self):
        """同内容不同插入序的 lora_request dict 必须命中同一缓存实例。

        历史缺陷：缓存键直接 str(dict) 拼接，键序不稳定导致语义相同的配置
        碎片化为多个键，缓存永不命中（外部类型审查项 20260827）。
        """
        from server.core.llm.client import LLMFactory

        a = LLMFactory.create_client(
            "vllm", model="m", host="http://a",
            lora_request={"model": "adapter-x", "weight": 1.0},
        )
        b = LLMFactory.create_client(
            "vllm", model="m", host="http://a",
            lora_request={"weight": 1.0, "model": "adapter-x"},  # 键序不同
        )
        assert a is b

    def test_lora_empty_dict_same_key_as_absent(self):
        """空 dict 与未传 lora_request 语义等价（VLLMClient falsy → None），应同键。"""
        from server.core.llm.client import LLMFactory

        plain = LLMFactory.create_client("vllm", model="m", host="http://a")
        empty = LLMFactory.create_client(
            "vllm", model="m", host="http://a", lora_request={}
        )
        assert plain is empty

    def test_lora_non_json_object_does_not_raise(self):
        """不可 JSON 化对象经 default=repr 兜底，构造不抛异常且同对象同键。"""
        from server.core.llm.client import LLMFactory

        class _SdkLora:  # 模拟 vLLM SDK LoRARequest 之类非 dict 对象
            def __init__(self, name):
                self.name = name

        sdk = _SdkLora("adapter-x")
        a = LLMFactory.create_client("vllm", model="m", host="http://a", lora_request=sdk)
        b = LLMFactory.create_client("vllm", model="m", host="http://a", lora_request=sdk)
        assert a is b