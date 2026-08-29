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
from server.services.asr_service import (
    ASRService,
    StreamingASRResult,
    get_recent_spk_embedding,
)


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

    @pytest.mark.asyncio
    async def test_recv_loop_exception_cleans_state(self):
        # 第六轮 C1-1：接收循环被服务端断开/超时异常退出时，finally 必须
        # 排空 recv_queue 并复位 final_received（与 send_audio_chunk 发送失败清理一致），
        # 否则重连复用同一队列会读到旧残留结果、final 判定被跳过。
        s = ASRService(mode="remote")
        st = s._stream_accessor("c1")
        st.recv_queue.put_nowait("stale-1")
        st.recv_queue.put_nowait("stale-2")
        st.final_received = True

        class _BrokenWS:
            def __aiter__(self):
                async def _gen():
                    yield "msg1"
                    raise ConnectionError("server closed")
                return _gen()

        st.ws = _BrokenWS()

        await s._ws_recv_loop(st)
        assert st.ws is None
        assert st.recv_queue.empty()       # 队列已排空（含异常前收到的 msg1）
        assert st.final_received is False  # final 标记已复位


# ================================================================ M：shutdown 流式会话释放 / executor 阻塞
class TestShutdownReleasesStreamSessions:
    """M：shutdown 先遍历释放全部 per-client 流式会话，再关 executor。"""

    @pytest.mark.asyncio
    async def test_shutdown_releases_all_sessions(self, monkeypatch):
        released = []
        s = ASRService(mode="remote")

        async def fake_release(cid):
            s._stream_sessions.pop(cid, None)  # 模拟真实 release 的注册表移除
            released.append(cid)

        monkeypatch.setattr(s, "release_streaming_session", fake_release)
        s._stream_sessions["c1"] = types.SimpleNamespace()
        s._stream_sessions["c2"] = types.SimpleNamespace()
        s._initialized = True
        asr_service._model_instance = object()  # 触发 reset 路径

        await s.shutdown()

        assert sorted(released) == ["c1", "c2"]
        assert s._stream_sessions == {}
        assert asr_service._model_instance is None
        assert s._initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_single_session_failure_not_blocking(self, monkeypatch):
        # 单个会话释放失败不阻断整体关闭（其余仍被释放，executor 照常关闭）
        released = []

        s = ASRService(mode="remote")

        async def fake_release(cid):
            if cid == "bad":
                raise RuntimeError("close failed")
            s._stream_sessions.pop(cid, None)
            released.append(cid)

        monkeypatch.setattr(s, "release_streaming_session", fake_release)
        s._stream_sessions["bad"] = types.SimpleNamespace()
        s._stream_sessions["good"] = types.SimpleNamespace()

        await s.shutdown()

        assert released == ["good"]

    @pytest.mark.asyncio
    async def test_recognize_file_runs_io_off_event_loop(self, tmp_path, monkeypatch):
        # L：recognize_file 的同步 open/read 挪入线程池（run_in_executor），
        # 识别结果路径与 FileNotFoundError 契约不变。
        f = tmp_path / "a.wav"
        f.write_bytes(b"RIFF-fake-audio")

        s = ASRService(mode="remote")
        called = {}

        async def fake_recognize(audio_data, language="auto", use_itn=True):
            called["data"] = audio_data
            return {"text": "ok", "language": language}

        monkeypatch.setattr(s, "recognize", fake_recognize)

        result = await s.recognize_file(f, language="zh")
        assert result == {"text": "ok", "language": "zh"}
        assert called["data"] == b"RIFF-fake-audio"

        # FileNotFoundError 契约保持（executor 内抛出后正常向上传播）
        with pytest.raises(FileNotFoundError):
            await s.recognize_file(tmp_path / "missing.wav")


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


# ================================================================ spk 补充消息 & speaker_status
class TestSpeakerSpk:
    @staticmethod
    def _svc_with_msg(msg):
        s = ASRService(mode="remote")
        s._ws = FakeWS()
        s._ws_recv_queue.put_nowait(json.dumps(msg))
        return s

    @pytest.mark.asyncio
    async def test_spk_message_result_fields(self):
        """spk 消息 → 返回空文本结果，speaker_status=ready，speaker 字段正确。"""
        s = self._svc_with_msg({
            "type": "spk", "speaker_id": "spk-9", "speaker_registered": True,
            "speaker_conf": 0.95, "speaker_name": "阿明",
            "em_embedding": [0.1, 0.2, 0.3],
        })
        r = await s.receive_result(timeout=0)
        assert isinstance(r, StreamingASRResult)
        assert r.text == ""
        assert r.is_final is False
        assert r.speaker_status == "ready"
        assert r.speaker_id == "spk-9"
        assert r.speaker_name == "阿明"
        assert r.speaker_registered is True
        assert r.speaker_conf == 0.95

    @pytest.mark.asyncio
    async def test_spk_message_backfills_recent(self):
        """spk 消息回填 recent_speaker 与 recent_spk_embedding（per-client 路径）。"""
        s = ASRService(mode="remote")
        s._stream_accessor("c1").recv_queue.put_nowait(json.dumps({
            "type": "spk", "speaker_id": "spk-1", "speaker_registered": False,
            "speaker_conf": 0.6, "em_embedding": [0.5, -0.5],
        }))
        r = await s.receive_result(timeout=0, client_id="c1")
        assert r.speaker_status == "ready"
        st = s._stream_accessor("c1")
        assert st.recent_speaker == ("spk-1", False, 0.6)
        assert st.recent_spk_embedding == [0.5, -0.5]

    @pytest.mark.asyncio
    async def test_get_recent_spk_embedding_returns_list(self, monkeypatch):
        """get_recent_spk_embedding(client_id) 返回最近 spk 消息的 embedding 列表。"""
        s = ASRService(mode="remote")
        s._stream_accessor("u-1").recv_queue.put_nowait(json.dumps({
            "type": "spk", "speaker_id": "spk-1", "em_embedding": [1.0, 2.0, 3.0, 4.0],
        }))
        await s.receive_result(timeout=0, client_id="u-1")
        monkeypatch.setattr(asr_service, "get_asr_service", lambda: s)
        assert get_recent_spk_embedding("u-1") == [1.0, 2.0, 3.0, 4.0]
        # 默认会话未收到过 spk 消息 → None
        assert get_recent_spk_embedding(None) is None

    @pytest.mark.asyncio
    async def test_final_speaker_status_pending_passthrough(self):
        """普通 final 消息带 speaker_status=pending → 透传 pending。"""
        s = self._svc_with_msg({
            "text": "你好", "is_final": True, "speaker_id": "spk-2",
            "speaker_status": "pending",
        })
        r = await s.receive_result(timeout=0)
        assert r.speaker_status == "pending"
        assert r.text == "你好"
        # pending 不回填 recent_speaker
        assert s._recent_speaker == ()

    @pytest.mark.asyncio
    async def test_old_format_defaults(self):
        """旧格式消息（无 type/speaker_status/em_embedding）→ 解析正常，speaker_status 缺省 ready。"""
        s = self._svc_with_msg({"text": "hi", "is_final": True})
        r = await s.receive_result(timeout=0)
        assert r.text == "hi"
        assert r.is_final is True
        assert r.speaker_status == "ready"
        assert r.speaker_id == ""
        assert r.speaker_registered is False
        assert r.speaker_conf == 0.0

    @pytest.mark.asyncio
    async def test_final_ready_backfills_recent(self):
        """final 消息含非空 speaker_id 且 ready → 回填 recent_speaker。"""
        s = self._svc_with_msg({
            "text": "hi", "is_final": True, "speaker_id": "spk-3",
            "speaker_registered": True, "speaker_conf": 0.88, "speaker_status": "ready",
        })
        await s.receive_result(timeout=0)
        assert s._recent_speaker == ("spk-3", True, 0.88)

    @pytest.mark.asyncio
    async def test_per_client_embedding_isolation(self):
        """per-client 隔离：不同 client_id 的 embedding 互不串扰。"""
        s = ASRService(mode="remote")
        s._stream_accessor("A").recv_queue.put_nowait(json.dumps({
            "type": "spk", "speaker_id": "spk-A", "em_embedding": [0.1, 0.2],
        }))
        await s.receive_result(timeout=0, client_id="A")
        assert s._stream_accessor("A").recent_spk_embedding == [0.1, 0.2]
        # 客户端 B 未收到 spk 消息 → embedding 为 None
        assert s._stream_accessor("B").recent_spk_embedding is None


# ================================================================ 只读访问器：_peek_stream_state 不落册
class TestPeekStreamStateNoRegistration:
    """get_recent_spk_embedding 纯读语义：未知 client_id 不得为查询落册 _StreamState。

    修复：_stream_accessor 读路径对未知 client_id 会插入含锁+队列的 _StreamState
    注册项（泄漏）；新增 _peek_stream_state（dict.get 不落册）供只读调用方使用，
    写路径（receive_result 等）落册行为保持不变。
    """

    def test_unknown_client_not_registered(self, monkeypatch):
        s = ASRService(mode="remote")
        monkeypatch.setattr(asr_service, "get_asr_service", lambda: s)
        # 未知 client_id：返回 None 快照，且注册表不新增条目
        assert get_recent_spk_embedding("ghost-client") is None
        assert "ghost-client" not in s._stream_sessions

    def test_default_session_reads_instance_attr(self, monkeypatch):
        """client_id=None：读默认会话实例属性，行为与旧实现一致。"""
        s = ASRService(mode="remote")
        monkeypatch.setattr(asr_service, "get_asr_service", lambda: s)
        assert get_recent_spk_embedding(None) is None
        s._recent_spk_embedding = [0.5, 0.6]
        assert get_recent_spk_embedding(None) == [0.5, 0.6]

    def test_existing_session_read_via_peek(self, monkeypatch):
        """已存在会话：走只读访问器取状态值。"""
        s = ASRService(mode="remote")
        monkeypatch.setattr(asr_service, "get_asr_service", lambda: s)
        st = s._stream_accessor("c-exist")  # 写路径显式落册
        st.recent_spk_embedding = [0.7]
        assert get_recent_spk_embedding("c-exist") == [0.7]
        assert set(s._stream_sessions) == {"c-exist"}  # 查询不额外落册

    def test_peek_returns_none_for_missing_but_accessor_registers(self):
        """_peek_stream_state 与 _stream_accessor 落册行为对照。"""
        s = ASRService(mode="remote")
        assert s._peek_stream_state("nope") is None          # 只读：不落册
        assert "nope" not in s._stream_sessions
        assert s._peek_stream_state(None) is None            # 默认会话无独立 state
        s._stream_accessor("yes")                            # 写路径：落册
        assert "yes" in s._stream_sessions
        assert s._peek_stream_state("yes") is s._stream_sessions["yes"]


async def _raise_send(data):
    raise RuntimeError("send fail")
