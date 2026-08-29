"""server.api.routers.multimodal 路由测试。

用 FastAPI TestClient + 注入假 MultimodalPipeline（monkeypatch _get_pipeline），
隔离真实 MultimodalPipeline。覆盖 preprocess / artifact / provider / health 端点
及异常映射（ValueError→422, FileNotFoundError→404, ConnectionError→503,
TimeoutError→504, RuntimeError→500）。

运行：python -m pytest tests/test_multimodal_router.py -v
"""
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import multimodal as mm_router_mod


# --------------------------------------------------------------------------- #
# 假 Pipeline —— 记录调用 + 可配置异常
# --------------------------------------------------------------------------- #
class FakeArtifact:
    def __init__(self, overrides: Dict[str, Any]):
        self._overrides = overrides

    def model_dump(self) -> Dict[str, Any]:
        base = {
            "artifact_id": "a1",
            "type": "text",
            "source": "src",
            "text_content": "内容",
            "native_decode_used": False,
            "extra_metadata": {},
            "confidence": 1.0,
            "vision_degraded": False,
            "processing_time_ms": 10,
            "created_at": "2026-08-09T00:00:00",
        }
        base.update(self._overrides)
        return base


class FakePipeline:
    def __init__(self):
        self.preprocess_calls = []
        self.errors: Dict[str, Exception] = {}
        self.artifact = FakeArtifact({})
        self.provider = "vllm"
        self._vllm_native_enabled = True
        self._enabled_modalities = {"text", "image"}
        self._worker_pool_size = 2

    def preprocess(self, source_type, source_ref):
        self.preprocess_calls.append((source_type, source_ref))
        if "preprocess" in self.errors:
            raise self.errors["preprocess"]
        return self.artifact

    def _get_llm_provider(self):
        if "provider" in self.errors:
            raise self.errors["provider"]
        return self.provider


@pytest.fixture
def client(monkeypatch):
    pipeline = FakePipeline()
    monkeypatch.setattr(mm_router_mod, "_get_pipeline", lambda: pipeline)
    app = FastAPI()
    app.include_router(mm_router_mod.router)
    return TestClient(app), pipeline


# --------------------------------------------------------------------------- #
# preprocess 端点
# --------------------------------------------------------------------------- #
class TestPreprocess:
    def test_success(self, client):
        c, pipeline = client
        r = c.post("/multimodal/preprocess", json={
            "source_type": "text", "source_ref": "hello"})
        assert r.status_code == 200
        body = r.json()
        assert body["artifact_id"] == "a1"
        assert body["type"] == "text"
        assert (("text", "hello") in pipeline.preprocess_calls)

    def test_value_error_422(self, client):
        c, pipeline = client
        pipeline.errors["preprocess"] = ValueError("bad source_type")
        r = c.post("/multimodal/preprocess", json={
            "source_type": "unknown", "source_ref": "x"})
        assert r.status_code == 422

    def test_file_not_found_404(self, client):
        c, pipeline = client
        pipeline.errors["preprocess"] = FileNotFoundError("no file")
        r = c.post("/multimodal/preprocess", json={
            "source_type": "image", "source_ref": "/nope.png"})
        assert r.status_code == 404

    def test_connection_error_503(self, client):
        c, pipeline = client
        pipeline.errors["preprocess"] = ConnectionError("vllm down")
        r = c.post("/multimodal/preprocess", json={
            "source_type": "image", "source_ref": "x"})
        assert r.status_code == 503

    def test_timeout_error_504(self, client):
        c, pipeline = client
        pipeline.errors["preprocess"] = TimeoutError("timeout")
        r = c.post("/multimodal/preprocess", json={
            "source_type": "video", "source_ref": "x"})
        assert r.status_code == 504

    def test_runtime_error_500(self, client):
        c, pipeline = client
        pipeline.errors["preprocess"] = RuntimeError("ocr fail")
        r = c.post("/multimodal/preprocess", json={
            "source_type": "image", "source_ref": "x"})
        assert r.status_code == 500

    def test_generic_error_500(self, client):
        c, pipeline = client
        pipeline.errors["preprocess"] = Exception("mystery")
        r = c.post("/multimodal/preprocess", json={
            "source_type": "audio", "source_ref": "x"})
        assert r.status_code == 500


# --------------------------------------------------------------------------- #
# artifact 查询（占位端点）
# --------------------------------------------------------------------------- #
class TestArtifactQuery:
    def test_placeholder(self, client):
        c, pipeline = client
        r = c.get("/multimodal/artifact/abc123")
        assert r.status_code == 200
        body = r.json()
        assert body["artifact_id"] == "abc123"
        assert body["status"] == "not_persisted"


# --------------------------------------------------------------------------- #
# provider / health 端点
# --------------------------------------------------------------------------- #
class TestProvider:
    def test_success(self, client):
        c, pipeline = client
        r = c.get("/multimodal/provider")
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "vllm"
        assert body["vllm_native_enabled"] is True
        assert set(body["enabled_modalities"]) == {"text", "image"}


class TestHealth:
    def test_healthy(self, client):
        c, pipeline = client
        r = c.get("/multimodal/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["pipeline_initialized"] is True
        assert body["worker_pool_size"] == 2

    def test_unhealthy(self, client, monkeypatch):
        c, pipeline = client
        pipeline.errors["provider"] = RuntimeError("init fail")
        r = c.get("/multimodal/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "unhealthy"
        assert body["pipeline_initialized"] is False
        assert "init fail" in body["error"]


# --------------------------------------------------------------------------- #
# preprocess to_thread 卸载回归（第九轮 G2：重型同步 preprocess 异步化）
# --------------------------------------------------------------------------- #
class TestPreprocessToThread:
    def test_preprocess_offloads_from_event_loop(self, client, monkeypatch):
        """修复回归：preprocess 经 asyncio.to_thread 在事件循环外线程执行。

        直接以事件循环驱动端点协程，对比「事件循环线程 id」与「preprocess
        实际执行线程 id」：修复前 async 端点直调同步 preprocess（内含 OCR/
        视频解码）两者相同 → 阻塞全站；修复后 to_thread 线程池不同。
        """
        import asyncio
        import threading

        c, pipeline = client
        loop_thread_ids = []
        call_thread_ids = []
        original_preprocess = pipeline.preprocess

        def spy_preprocess(source_type, source_ref):
            call_thread_ids.append(threading.get_ident())
            return original_preprocess(source_type, source_ref)

        # 实例属性替换优先于类方法，端点内 pipeline.preprocess(...) 走 spy
        monkeypatch.setattr(pipeline, "preprocess", spy_preprocess)

        async def probe():
            loop_thread_ids.append(threading.get_ident())
            request = mm_router_mod.PreprocessRequest(source_type="text", source_ref="hello")
            return await mm_router_mod.preprocess(request)

        resp = asyncio.run(probe())
        assert resp.artifact_id == "a1"
        # spy 生效且参数正确透传
        assert pipeline.preprocess_calls == [("text", "hello")]
        # 关键断言：preprocess 执行线程 != 事件循环线程
        assert call_thread_ids[0] != loop_thread_ids[0]