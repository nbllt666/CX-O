"""server.services.asr_service (ASRService) 单元测试。

聚焦可隔离测试的逻辑，隔离真实 WebSocket / httpx / SenseVoice / funasr：

- recognize_file / recognize 的远程与嵌入式路由
- _recognize_remote / _recognize_remote_base64：响应解析与错误处理（假 http client + retry）
- send_audio_chunk / receive_result / reset：WebSocket 流式接口全状态机
- receive_result 的 timeout=0 快速路径（get_nowait 同步读取，避免 3.12 wait_for 陷阱）
- _run_inference：SenseVoice 输出的标记清理与 lang/emotion/event 提取

运行：python -m pytest tests/test_asr_service.py -v
"""
import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from server.services import asr_service
from server.services.asr_service import ASRService, StreamingASRResult


class FakeHttpResponse:
    def __init__(self, status_code=200, json_data=None, exc=None):
        self.status_code = status_code
        self._json = json_data or {}
        self._exc = exc

    def json(self):
        if self._exc:
            raise self._exc
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """记录请求的假 httpx client。"""

    def __init__(self, response=None):
        self.response = response
        self.posts = []

    async def post(self, url, **kw):
        self.posts.append((url, kw))
        if callable(self.response):
            return self.response(url, kw)
        return self.response


class FakeWS:
    """可注入 ASRService._ws 的假 WebSocket。"""

    def __init__(self):
        self.sent = []
        self.connected = True

    async def send(self, data):
        self.sent.append(data)


# ================================================================ 构造与路由
class TestRouting:
    def test_mode_property(self):
        assert ASRService(mode="remote").mode == "remote"
        assert ASRService(mode="embedded").mode == "embedded"

    @pytest.mark.asyncio
    async def test_initialize_remote(self):
        s = ASRService(mode="remote")
        await s.initialize()
        assert s._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_embedded_with_model(self, monkeypatch):
        asr_service._model_instance = object()
        s = ASRService(mode="embedded")
        await s.initialize()
        assert s._initialized is True
        asr_service._model_instance = None

    @pytest.mark.asyncio
    async def test_initialize_embedded_fallback_to_remote(self, monkeypatch):
        asr_service._model_instance = None
        # from_pretrained 抛异常 → 回退 remote
        def boom(*a, **k):
            raise RuntimeError("no model")

        sensevoice = SimpleNamespace(SenseVoiceSmall=SimpleNamespace(from_pretrained=staticmethod(boom)))
        monkeypatch.setitem(sys.modules, "sensevoice", SimpleNamespace(model=sensevoice))
        s = ASRService(mode="embedded", remote_url="http://r:8001")
        await s.initialize()
        assert s.mode == "remote"
        assert s._initialized is True
        asr_service._model_instance = None

    @pytest.mark.asyncio
    async def test_shutdown_resets(self, monkeypatch):
        asr_service._model_instance = object()
        s = ASRService(mode="embedded")
        s._initialized = True
        await s.shutdown()
        assert s._initialized is False
        assert asr_service._model_instance is None


# ================================================================ recognize 路由
class TestRecognize:
    @pytest.mark.asyncio
    async def test_recognize_file_missing(self, tmp_path):
        s = ASRService()
        with pytest.raises(FileNotFoundError):
            await s.recognize_file(str(tmp_path / "no.wav"))

    @pytest.mark.asyncio
    async def test_recognize_file_reads_and_remote(self, tmp_path, monkeypatch):
        p = tmp_path / "a.wav"
        p.write_bytes(b"\x00\x01")
        s = ASRService(mode="remote")
        captured = {}

        async def fake_recognize(audio, lang, itn):
            captured["audio"] = audio
            return {"text": "ok"}

        monkeypatch.setattr(s, "_recognize_remote", fake_recognize)
        assert await s.recognize_file(str(p)) == {"text": "ok"}
        assert captured["audio"] == b"\x00\x01"

    @pytest.mark.asyncio
    async def test_recognize_remote_mode_calls_remote(self, monkeypatch):
        s = ASRService(mode="remote")
        called = {}

        async def fake_remote(audio, lang, itn):
            called["audio"] = audio
            return {"text": "ok"}

        monkeypatch.setattr(s, "_recognize_remote", fake_remote)
        assert await s.recognize(b"\x00", "zh", True) == {"text": "ok"}
        assert called["audio"] == b"\x00"

    @pytest.mark.asyncio
    async def test_recognize_base64_embedded(self, monkeypatch):
        asr_service._model_instance = object()
        import base64
        s = ASRService(mode="embedded")
        got = {}

        async def fake_embed(audio, lang, itn):
            got["audio"] = audio
            return {"text": "ok"}

        monkeypatch.setattr(s, "_recognize_embedded", fake_embed)
        await s.recognize_base64(base64.b64encode(b"\x00\x01").decode())
        assert got["audio"] == b"\x00\x01"
        asr_service._model_instance = None


# ================================================================ _recognize_remote
class TestRecognizeRemote:
    @pytest.mark.asyncio
    async def test_success_parses_first_result(self, monkeypatch):
        client = FakeClient(response=FakeHttpResponse(200, {
            "results": [{"text": "你好", "language": "zh", "emotion": "HAPPY", "event": "Speech"}],
        }))
        monkeypatch.setattr(asr_service, "get_shared_http_client", lambda: client)
        s = ASRService(mode="remote", remote_url="http://r:8001")
        res = await s._recognize_remote(b"\x00", "zh", True)
        assert res["text"] == "你好"
        assert res["emotion"] == "HAPPY"
        assert res["event"] == "Speech"
        assert client.posts[0][0] == "http://r:8001/api/v1/asr"

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self, monkeypatch):
        client = FakeClient(response=FakeHttpResponse(500))
        monkeypatch.setattr(asr_service, "get_shared_http_client", lambda: client)
        s = ASRService(mode="remote")
        res = await s._recognize_remote(b"\x00", "zh", True)
        assert res["text"] == ""
        assert "error" in res


# ================================================================ WebSocket 流式
class TestStreaming:
    @pytest.mark.asyncio
    async def test_send_chunk_not_initialized(self):
        s = ASRService(mode="remote")
        assert await s.send_audio_chunk(b"\x00") is False

    @pytest.mark.asyncio
    async def test_send_chunk_normal(self):
        s = ASRService(mode="remote")
        s._initialized = True
        ws = FakeWS()
        s._ws = ws  # 已设置 _ws → _ensure_ws 直接返回 True
        assert await s.send_audio_chunk(b"\x00") is True
        assert ws.sent == [b"\x00"]

    @pytest.mark.asyncio
    async def test_send_chunk_last_sends_final(self):
        s = ASRService(mode="remote")
        s._initialized = True
        ws = FakeWS()
        s._ws = ws
        assert await s.send_audio_chunk(b"\x00", is_last=True) is True
        assert ws.sent == [b"\x00", json.dumps({"action": "final"})]

    @pytest.mark.asyncio
    async def test_send_chunk_send_error_clears_ws(self):
        s = ASRService(mode="remote")
        s._initialized = True
        ws = FakeWS()
        ws.send = _raise_send
        s._ws = ws
        assert await s.send_audio_chunk(b"\x00") is False
        assert s._ws is None

    @pytest.mark.asyncio
    async def test_ensure_ws_connect_fail(self, monkeypatch):
        s = ASRService(mode="remote")
        monkeypatch.setattr(
            asr_service.websockets, "connect",
            lambda *a, **k: (_ for _ in ()).throw(OSError("no ws")),
        )
        assert await s._ensure_ws() is False
        assert s._ws is None

    @pytest.mark.asyncio
    async def test_receive_result_timeout_zero_gets(self):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        s._ws_recv_queue.put_nowait(json.dumps({"text": "你好", "is_final": True, "language": "zh"}))
        r = await s.receive_result(timeout=0)
        assert isinstance(r, StreamingASRResult)
        assert r.text == "你好"
        assert r.is_final is True
        assert s._ws_final_received is True

    @pytest.mark.asyncio
    async def test_receive_result_timeout_zero_empty(self):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        assert await s.receive_result(timeout=0) is None

    @pytest.mark.asyncio
    async def test_receive_result_waits(self):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        # 预置消息，wait_for 立即返回
        s._ws_recv_queue.put_nowait(json.dumps({"text": "partial", "is_final": False}))
        r = await s.receive_result(timeout=1.0)
        assert r.text == "partial"
        assert r.is_final is False

    @pytest.mark.asyncio
    async def test_receive_result_timeout_returns_none(self):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        # 空队列 + wait_for 超时 → None
        r = await s.receive_result(timeout=0.001)
        assert r is None

    @pytest.mark.asyncio
    async def test_receive_result_ignores_bytes(self):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        s._ws_recv_queue.put_nowait(b"\x00\x01")
        assert await s.receive_result(timeout=0) is None

    @pytest.mark.asyncio
    async def test_receive_result_invalid_json(self):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        s._ws_recv_queue.put_nowait("{bad")
        assert await s.receive_result(timeout=0) is None

    @pytest.mark.asyncio
    async def test_reset_clears_queue(self):
        s = ASRService(mode="remote")
        s._ws_final_received = True
        s._ws_recv_queue.put_nowait("a")
        s._ws_recv_queue.put_nowait("b")
        await s.reset()
        assert s._ws_recv_queue.empty()
        assert s._ws_final_received is False


# ================================================================ _run_inference
class TestRunInference:
    def test_cleans_tags_and_extracts(self, monkeypatch):
        model = SimpleNamespace(inference=lambda **k: [
            [{"text": "<|zh|><|HAPPY|><|Speech|>你好<|end|>"}]
        ])
        asr_service._model_instance = model
        asr_service._model_kwargs = {}
        fake_mod = types.ModuleType("funasr.utils.postprocess_utils")
        fake_mod.rich_transcription_postprocess = lambda raw: "你好"
        monkeypatch.setitem(sys.modules, "funasr.utils.postprocess_utils", fake_mod)
        monkeypatch.setitem(sys.modules, "funasr", types.ModuleType("funasr"))
        s = ASRService(mode="embedded")
        res = s._run_inference([object()], "zh", use_itn=True)
        assert res["text"] == "你好"
        assert res["language"] == "zh"
        assert res["emotion"] == "HAPPY"
        assert res["event"] == "Speech"
        asr_service._model_instance = None

    def test_empty_result(self, monkeypatch):
        model = SimpleNamespace(inference=lambda **k: [])
        asr_service._model_instance = model
        asr_service._model_kwargs = {}
        fake_mod = types.ModuleType("funasr.utils.postprocess_utils")
        fake_mod.rich_transcription_postprocess = lambda raw: raw
        monkeypatch.setitem(sys.modules, "funasr.utils.postprocess_utils", fake_mod)
        monkeypatch.setitem(sys.modules, "funasr", types.ModuleType("funasr"))
        s = ASRService(mode="embedded")
        res = s._run_inference([], "zh", use_itn=False)
        assert res == {"text": "", "language": "", "emotion": "", "event": ""}
        asr_service._model_instance = None

    def test_use_itn_false_uses_clean_text(self, monkeypatch):
        model = SimpleNamespace(inference=lambda **k: [
            [{"text": "<|zh|>你好"}]  # use_itn=False → 用 clean_text（去标签）
        ])
        asr_service._model_instance = model
        asr_service._model_kwargs = {}
        fake_mod = types.ModuleType("funasr.utils.postprocess_utils")
        fake_mod.rich_transcription_postprocess = lambda raw: raw
        monkeypatch.setitem(sys.modules, "funasr.utils.postprocess_utils", fake_mod)
        monkeypatch.setitem(sys.modules, "funasr", types.ModuleType("funasr"))
        s = ASRService(mode="embedded")
        res = s._run_inference([], "zh", use_itn=False)
        assert res["text"] == "你好"
        assert res["language"] == "zh"
        asr_service._model_instance = None


async def _raise_send(data):
    raise RuntimeError("send fail")
