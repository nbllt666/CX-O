"""api_server 第六轮 C1 修复单元测试（任务2/3/4）。

api_server 直接 `import funasr`（宿主机一般无 funasr）→ 在 import 前注入 funasr 桩，
asr_container.streaming_engine 同样 import funasr（已被同一桩覆盖）。

覆盖：
  - 任务2：/asr/recognize、/api/v1/asr 的阻塞推理放入 run_in_executor（工作线程执行，不阻塞事件循环）
  - 任务3：WS 文本帧顶层非 dict（合法 JSON）直接忽略，不抛 AttributeError、不断连
  - 任务4：voiceprint/profiles/sync 零摩擦 token 鉴权（仅当 ASR_API_TOKEN 非空时校验）

运行：python -m pytest tests/test_api_server.py -v
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import threading
import types

import numpy as np

# --- 在 import api_server 前注入 funasr 桩 --- #
_funasr = types.ModuleType("funasr")


class _DummyAutoModel:
    def __init__(self, *args, **kwargs):
        pass


_funasr.AutoModel = _DummyAutoModel
sys.modules["funasr"] = _funasr

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402
from fastapi import UploadFile  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api_server as m  # noqa: E402


def _infer_thread_check():
    main_id = threading.get_ident()
    seen = {}

    def fake_infer(audio, language="auto", use_itn=True):
        # 若推理被同步调用（旧 bug），会在事件循环线程执行；run_in_executor
        # 正确实现时在工作线程执行。据此断言非阻塞路径被调用。
        seen["in_worker"] = threading.get_ident() != main_id
        return {"text": "你好", "language": language, "emotion": ""}

    fake_infer._seen = seen
    return main_id, fake_infer


# ================================================================ 任务2：HTTP 推理非阻塞
class TestHttpInferenceNonblock:
    def test_recognize_dispatches_inference_to_executor(self, monkeypatch):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            monkeypatch.setattr(m, "_model", object())
            monkeypatch.setattr(m, "_decode_audio_bytes",
                                lambda b: np.zeros(16, dtype=np.float32))
            main_id, fake_infer = _infer_thread_check()
            monkeypatch.setattr(m, "_run_inference", fake_infer)

            req = m.ASRRequest(audio=base64.b64encode(b"RIFF....WAVE").decode(),
                               language="zh")
            resp = loop.run_until_complete(m.recognize_audio(req))
        finally:
            loop.close()

        assert fake_infer._seen.get("in_worker") is True  # 推理在工作线程 → 未阻塞事件循环
        assert resp.text == "你好"
        assert resp.language == "zh"

    def test_api_v1_asr_dispatches_inference_to_executor(self, monkeypatch):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            monkeypatch.setattr(m, "_model", object())
            monkeypatch.setattr(m, "_decode_audio_bytes",
                                lambda b: np.zeros(8, dtype=np.float32))
            main_id, fake_infer = _infer_thread_check()
            monkeypatch.setattr(m, "_run_inference", fake_infer)

            uf = UploadFile(filename="a.wav", file=io.BytesIO(b"RIFF....WAVE"))
            # 直接调用 coroutine：显式传 use_itn（否则保持 Form 哨兵、无法 .lower()）
            result = loop.run_until_complete(
                m.api_v1_asr(file=uf, language="auto", use_itn="true"))
        finally:
            loop.close()

        assert fake_infer._seen.get("in_worker") is True
        assert result["results"][0]["text"] == "你好"

    def test_recognize_serialized_by_http_lock(self, monkeypatch):
        # 共享 _model 的 GPU 状态：HTTP 推理经 asyncio.Lock 串行化（避免与流式并发竞争）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        import threading as _t
        order = []
        gate = _t.Event()
        try:
            monkeypatch.setattr(m, "_model", object())
            monkeypatch.setattr(m, "_decode_audio_bytes",
                                lambda b: np.zeros(16, dtype=np.float32))

            def slow_infer(audio, language="auto", use_itn=True):
                order.append("start")
                gate.wait(timeout=5)   # 卡住第一个推理，验证第二个并发请求被锁挡住
                order.append("end")
                return {"text": "x", "language": language, "emotion": ""}

            monkeypatch.setattr(m, "_run_inference", slow_infer)

            def _req():
                return m.ASRRequest(audio=base64.b64encode(b"RIFF").decode())

            async def _driver():
                # 第一个请求抢到锁并在 worker 卡住；0.05s 后放行 gate，
                # 期间第二个并发请求 await 同一把锁被串行化，不会交错进入推理。
                t1 = asyncio.create_task(m.recognize_audio(_req()))
                await asyncio.sleep(0.05)
                gate.set()
                await asyncio.gather(t1, m.recognize_audio(_req()))
                return order

            loop.run_until_complete(_driver())
        finally:
            gate.set()
            loop.close()

        # 两段推理被串行化：start/end 交替出现且不交错
        assert order == ["start", "end", "start", "end"]


# ================================================================ 任务3：WS 非 dict 文本帧
class TestWsNonDictFrame:
    def test_nondict_text_frame_ignored_connection_survives(self):
        websockets = pytest.importorskip("websockets")
        with TestClient(m.app) as client:
            with client.websocket_connect("/ws/asr/stream") as ws:
                # 下列合法 JSON 但顶层非 dict 的帧必须被忽略而非断开
                ws.send_text(json.dumps("a-string"))
                ws.send_text(json.dumps([1, 2, 3]))
                ws.send_text(json.dumps(123))
                # 连接仍存活：后续正常 final 帧能被处理并收到响应
                ws.send_text(json.dumps({"action": "final"}))
                data = ws.receive_json()
                assert data.get("is_final") is True


# ================================================================ 任务4：voiceprint profiles/sync 鉴权
class TestProfilesSyncToken:
    def test_token_required_when_configured(self, monkeypatch):
        monkeypatch.setenv("ASR_API_TOKEN", "sekret")
        monkeypatch.setattr(m, "load_profiles", lambda: 3)
        with TestClient(m.app) as client:
            assert client.post("/api/v1/voiceprint/profiles/sync").status_code == 403
            assert client.post(
                "/api/v1/voiceprint/profiles/sync",
                headers={"x-api-token": "wrong"}).status_code == 403
            r = client.post("/api/v1/voiceprint/profiles/sync",
                            headers={"x-api-token": "sekret"})
            assert r.status_code == 200
            assert r.json()["count"] == 3

    def test_no_token_configured_unrestricted(self, monkeypatch):
        monkeypatch.delenv("ASR_API_TOKEN", raising=False)
        monkeypatch.setattr(m, "load_profiles", lambda: 7)
        with TestClient(m.app) as client:
            r = client.post("/api/v1/voiceprint/profiles/sync")  # 无头也放行
            assert r.status_code == 200
            assert r.json()["count"] == 7