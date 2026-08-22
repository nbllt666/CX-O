"""VLLM Dynamic LoRA 支撑单测。

覆盖：
- VLLMClient 的 lora_request 序列化（启用时附加、未启用时空）
- async load_lora_adapter（httpx mock：成功 / HTTP 错误 / 超时）
- ModelRouter.resolve_lora_request 的 scene→adapter 映射（有 / 无）
- ModelRouter 未启用 LoRA 时恒返回 None（向后兼容）
- 向后兼容回归：未启用 lora 字段恒空

运行：python -m pytest tests/test_vllm_lora.py -v
"""
import json

import httpx
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from server.core.llm.client import VLLMClient
from server.core.model_router import ModelRouter


# ---------------------------------------------------------------- 工具
def _mock_shared_client(monkeypatch, status=200, payload=None, stream=False):
    """替换 get_shared_http_client 为捕获 post/stream 的 mock。"""
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = payload or {
        "choices": [{"message": {"content": "lora回复"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 5},
    }
    mock_response.text = "error body"

    async_client = AsyncMock()
    async_client.post.return_value = mock_response

    if stream:
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__ = AsyncMock(return_value=False)
        async_client.stream = MagicMock(return_value=stream_ctx)

    monkeypatch.setattr(
        "server.core.llm.client.get_shared_http_client", lambda: async_client
    )
    return async_client, mock_response


def _settings_with_lora(enabled=True):
    """构造 get_settings 返回的假 Settings 对象（含 evolution.lora_enabled）。"""
    return SimpleNamespace(
        config=SimpleNamespace(evolution=SimpleNamespace(lora_enabled=enabled))
    )


# ---------------------------------------------------------------- lora_request 序列化
class TestLoraRequestSerialization:
    @pytest.mark.asyncio
    async def test_chat_attaches_lora_request(self, monkeypatch):
        """启用 lora_request 时 chat 请求体应附加 lora_request 字段。"""
        lora_req = {"model": "roleplay-adapter", "lora_weight": 1.0}
        c = VLLMClient(lora_request=lora_req)
        async_client, _ = _mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}])
        _, kwargs = async_client.post.call_args
        assert kwargs["json"]["lora_request"] == lora_req

    @pytest.mark.asyncio
    async def test_chat_no_lora_request_by_default(self, monkeypatch):
        """默认无 lora_request 时 chat 请求体不附加 lora_request 字段。"""
        c = VLLMClient()
        async_client, _ = _mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}])
        _, kwargs = async_client.post.call_args
        assert "lora_request" not in kwargs["json"]

    @pytest.mark.asyncio
    async def test_chat_empty_lora_request_is_none(self, monkeypatch):
        """即使传入空 dict，也应归一化为 None（不附加字段，向后兼容）。"""
        c = VLLMClient(lora_request={})
        async_client, _ = _mock_shared_client(monkeypatch)
        await c.chat([{"role": "user", "content": "hi"}])
        _, kwargs = async_client.post.call_args
        assert "lora_request" not in kwargs["json"]

    @pytest.mark.asyncio
    async def test_stream_attaches_lora_request(self, monkeypatch):
        """启用 lora_request 时 stream_chat 请求体应附加 lora_request 字段。"""
        lora_req = {"model": "writing-adapter", "lora_weight": 1.0}
        c = VLLMClient(lora_request=lora_req)
        async_client, _ = _mock_shared_client(monkeypatch, stream=True)
        chunks = [chunk async for chunk in c.stream_chat([{"role": "user", "content": "hi"}])]
        # 无 SSE 数据行 → 无产出，仅验证请求体
        _, kwargs = async_client.stream.call_args
        assert kwargs["json"]["lora_request"] == lora_req

    @pytest.mark.asyncio
    async def test_stream_no_lora_request_by_default(self, monkeypatch):
        """默认无 lora_request 时 stream_chat 请求体不附加 lora_request 字段。"""
        c = VLLMClient()
        async_client, _ = _mock_shared_client(monkeypatch, stream=True)
        chunks = [chunk async for chunk in c.stream_chat([{"role": "user", "content": "hi"}])]
        _, kwargs = async_client.stream.call_args
        assert "lora_request" not in kwargs["json"]


# ---------------------------------------------------------------- load_lora_adapter
class TestLoadLoraAdapter:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        c = VLLMClient()
        async_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        async_client.post.return_value = mock_response
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        result = await c.load_lora_adapter("roleplay-adapter", "/lora/roleplay")
        assert result["ok"] is True
        assert result["adapter_name"] == "roleplay-adapter"
        # 验证端点为 /load_lora_adapter 且请求体符合 vLLM 约定
        url, kwargs = async_client.post.call_args
        assert url[0].endswith("/load_lora_adapter")
        assert kwargs["json"] == {
            "lora_name": "roleplay-adapter",
            "lora_path": "/lora/roleplay",
        }

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        c = VLLMClient()
        async_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "boom"
        async_client.post.return_value = mock_response
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        result = await c.load_lora_adapter("roleplay-adapter", "/lora/roleplay")
        assert result["ok"] is False
        assert result["status_code"] == 500
        assert "HTTP 500" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout(self, monkeypatch):
        c = VLLMClient()
        async_client = AsyncMock()
        async_client.post.side_effect = httpx.TimeoutException("timeout")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        result = await c.load_lora_adapter("roleplay-adapter", "/lora/roleplay")
        assert result["ok"] is False
        assert "超时" in result["error"]

    @pytest.mark.asyncio
    async def test_generic_failure_no_raise(self, monkeypatch):
        c = VLLMClient()
        async_client = AsyncMock()
        async_client.post.side_effect = RuntimeError("connection refused")
        monkeypatch.setattr(
            "server.core.llm.client.get_shared_http_client", lambda: async_client
        )
        result = await c.load_lora_adapter("roleplay-adapter", "/lora/roleplay")
        assert result["ok"] is False
        assert "connection refused" in result["error"]


# ---------------------------------------------------------------- ModelRouter scene→adapter
class TestResolveLoraRequest:
    def _router(self, monkeypatch, enabled):
        r = ModelRouter()
        monkeypatch.setattr(
            "server.core.model_router.get_settings",
            lambda: _settings_with_lora(enabled=enabled),
        )
        return r

    def test_returns_adapter_when_enabled_and_scene_exists(self, monkeypatch):
        r = self._router(monkeypatch, enabled=True)
        req = r.resolve_lora_request("roleplay")
        assert req == {"model": "roleplay-adapter", "lora_weight": 1.0}

    def test_returns_none_when_scene_missing(self, monkeypatch):
        r = self._router(monkeypatch, enabled=True)
        assert r.resolve_lora_request("nonexistent_scene") is None

    def test_bypasses_mapping_when_disabled(self, monkeypatch):
        """未启用 LoRA 时，即使 scene 存在 adapter 也恒返回 None。"""
        r = self._router(monkeypatch, enabled=False)
        assert r.resolve_lora_request("roleplay") is None

    def test_disabled_even_with_empty_mapping(self, monkeypatch):
        r = self._router(monkeypatch, enabled=False)
        r._scene_adapters = {"roleplay": {"model": "x", "lora_weight": 1.0}}
        assert r.resolve_lora_request("roleplay") is None

    def test_custom_mapping_overrides_defaults(self, monkeypatch):
        r = self._router(monkeypatch, enabled=True)
        r._scene_adapters = {"coding": {"model": "code-lora", "lora_weight": 0.8}}
        assert r.resolve_lora_request("coding") == {
            "model": "code-lora",
            "lora_weight": 0.8,
        }
        assert r.resolve_lora_request("roleplay") is None

    def test_override_flag_wins_over_config(self, monkeypatch):
        """override 为 True 时即使 config 为 False 也启用，供测试/注入使用。"""
        r = ModelRouter()
        r._lora_enabled_override = True
        req = r.resolve_lora_request("writing")
        assert req == {"model": "writing-adapter", "lora_weight": 1.0}


# ---------------------------------------------------------------- 向后兼容回归
class TestBackwardCompat:
    def test_resolve_returns_none_without_evolution_config(self, monkeypatch):
        """旧版配置没有 evolution 节时 resolve_lora_request 恒返回 None。"""
        r = ModelRouter()
        monkeypatch.setattr(
            "server.core.model_router.get_settings",
            lambda: SimpleNamespace(config=SimpleNamespace(models=object())),
        )
        assert r.resolve_lora_request("roleplay") is None

    def test_vllm_client_constructor_accepts_no_lora(self):
        """未传 lora_request 时构造正常且 self.lora_request 为 None。"""
        c = VLLMClient()
        assert c.lora_request is None