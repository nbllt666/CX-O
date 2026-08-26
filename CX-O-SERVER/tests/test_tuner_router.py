"""CXO-Tuner evolution 集成出口路由 + evolution 配置节测试。

覆盖：
  - TunerClient（httpx mock transport）反馈转发成功 / 不可达降级；
  - CX-O 主路由脚本独立于 CX-O 栈，无 Tuner 在线时反馈转发返回 503、stats 返回降级默认，
    核心路由不崩溃；
  - 会话历史导出（无会话返回空列表，结构稳定）；
  - evolution 配置节 auto_fill：越界回退默认、缺省补默认。

运行：python -m pytest tests/test_tuner_router.py -q
"""
import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import tuner
from server.config import _auto_fill_radix_config, CXOTunerConfig, UnifiedConfig


# --------------------------------------------------------------------------- #
# 假配置：控制 get_config().evolution 的 enabled / host 等字段
# --------------------------------------------------------------------------- #
class _FakeLLM:
    host = "http://localhost:11434"
    port = 8000


class _FakeEvolution:
    enabled = True
    host = "http://mock-tuner:8300"
    timeout = 10
    quality_reject_threshold = 0.3
    auto_push = False
    lora_enabled = False

    def model_dump(self):
        return {
            "enabled": self.enabled,
            "host": self.host,
            "timeout": self.timeout,
            "quality_reject_threshold": self.quality_reject_threshold,
            "auto_push": self.auto_push,
            "lora_enabled": self.lora_enabled,
        }


class _FakeConfig:
    def __init__(self, evolution=None):
        self.evolution = evolution or _FakeEvolution()
        self.llm = _FakeLLM()


def _make_client(handler) -> tuner.TunerClient:
    """构造一个挂载 mock transport 的 TunerClient（不发起真实网络）。

    拆查（issue 07 附录）：不调用 TunerClient() 构造函数——其在旧实现中急切构造
    默认 httpx.AsyncClient，该构造本机耗时 ~21s（证书库/代理发现），使每条用例
    变慢 ~27s，合计占全量回归一半。这里用 __new__ 跳过构造函数、只注入
    MockTransport 客户端（构造 0ms）。
    """
    client = tuner.TunerClient.__new__(tuner.TunerClient)
    client.base_url = "http://mock-tuner:8300"
    client.timeout = 10
    client._max_retries = 2
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10)
    client._owns_client = True
    return client


def _build_app(handler, evolution=None) -> TestClient:
    app = FastAPI()
    app.include_router(tuner.router, prefix="/api")
    app.state.tuner_client = _make_client(handler)
    return TestClient(app), _FakeConfig(evolution)


def _ok_handler(request):
    path = request.url.path
    if path.endswith("/api/v1/feedback"):
        return httpx.Response(200, json={"feedback_id": "f1", "accepted": True, "reason": "ok"})
    if path.endswith("/api/v1/dataset/stats"):
        return httpx.Response(
            200,
            json={
                "total": 5,
                "source_breakdown": {"judge": 3, "live_danmaku": 2},
                "positive_ratio": 0.6,
                "negative_ratio": 0.4,
                "anchor_count": 1,
            },
        )
    return httpx.Response(200, json=[])


def _down_handler(request):
    raise httpx.ConnectError("connection refused (mock)", request=request)


def _feedback_payload():
    return {
        "prompt": "hello",
        "response_chosen": "good answer",
        "response_rejected": "bad answer",
        "source": "judge",
        "timestamp": "2026-08-22T02:00:00Z",
        "quality_score": 0.8,
    }


# --------------------------------------------------------------------------- #
# 反馈转发：成功
# --------------------------------------------------------------------------- #
class TestFeedbackForward:
    def test_forward_success(self, monkeypatch):
        client, fake_cfg = _build_app(_ok_handler)
        monkeypatch.setattr(tuner, "get_config", lambda: fake_cfg)
        resp = client.post("/api/v1/tuner/feedback", json=_feedback_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["forwarded"] is True
        assert body["feedback"]["feedback_id"] == "f1"
        assert body["feedback"]["accepted"] is True

    def test_forward_unreachable_503(self, monkeypatch):
        client, fake_cfg = _build_app(_down_handler)
        monkeypatch.setattr(tuner, "get_config", lambda: fake_cfg)
        resp = client.post("/api/v1/tuner/feedback", json=_feedback_payload())
        # Tuner 不可达 → 503，且不抛异常破坏主线程
        assert resp.status_code == 503

    def test_forward_disabled_503(self, monkeypatch):
        ev = _FakeEvolution()
        ev.enabled = False
        client, fake_cfg = _build_app(_ok_handler, evolution=ev)
        monkeypatch.setattr(tuner, "get_config", lambda: fake_cfg)
        resp = client.post("/api/v1/tuner/feedback", json=_feedback_payload())
        assert resp.status_code == 503


# --------------------------------------------------------------------------- #
# 数据集统计：成功返回结构 / 不可达降级默认（不 503，CX-O 核心零影响）
# --------------------------------------------------------------------------- #
class TestStats:
    def test_stats_structure(self, monkeypatch):
        client, fake_cfg = _build_app(_ok_handler)
        monkeypatch.setattr(tuner, "get_config", lambda: fake_cfg)
        resp = client.get("/api/v1/tuner/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        s = body["stats"]
        assert s["total"] == 5
        assert s["source_breakdown"]["judge"] == 3
        assert s["positive_ratio"] == 0.6
        assert "anchor_count" in s

    def test_stats_degraded_default_when_unreachable(self, monkeypatch):
        client, fake_cfg = _build_app(_down_handler)
        monkeypatch.setattr(tuner, "get_config", lambda: fake_cfg)
        resp = client.get("/api/v1/tuner/stats")
        # 无 Tuner 在线时返回 200 + 降级默认结构，而非崩溃
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["stats"]["total"] == 0
        assert body["stats"]["anchor_count"] == 0


# --------------------------------------------------------------------------- #
# 会话历史导出：无会话返回空列表；核心路由不受影响
# --------------------------------------------------------------------------- #
class TestConversations:
    def test_conversations_returns_list(self, monkeypatch):
        client, fake_cfg = _build_app(_ok_handler)
        monkeypatch.setattr(tuner, "get_config", lambda: fake_cfg)
        resp = client.get("/api/v1/tuner/conversations?limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert isinstance(body["conversations"], list)


# --------------------------------------------------------------------------- #
# evolution 配置节 auto_fill
# --------------------------------------------------------------------------- #
class TestEvolutionConfigAutoFill:
    def test_defaults_when_missing(self):
        cfg = CXOTunerConfig()
        assert cfg.enabled is False
        assert cfg.host == "http://127.0.0.1:8300"
        assert cfg.timeout == 10
        assert cfg.quality_reject_threshold == 0.3
        assert cfg.auto_push is False
        assert cfg.lora_enabled is False

    def test_unified_config_auto_fills_evolution(self):
        # 缺省 evolution 节 → UnifiedConfig Pydantic default 补默认
        unified = UnifiedConfig(**{"evolution": {}})
        assert unified.evolution.enabled is False
        assert unified.evolution.timeout == 10
        assert unified.evolution.quality_reject_threshold == 0.3

    def test_out_of_range_timeout_falls_back(self):
        res = _auto_fill_radix_config({"evolution": {"timeout": 5000}})
        assert res["evolution"]["timeout"] == 10

    def test_out_of_range_quality_threshold_falls_back(self):
        res = _auto_fill_radix_config({"evolution": {"quality_reject_threshold": 2.0}})
        assert res["evolution"]["quality_reject_threshold"] == 0.3

    def test_in_range_values_kept(self):
        res = _auto_fill_radix_config(
            {"evolution": {"timeout": 60, "quality_reject_threshold": 0.5}}
        )
        assert res["evolution"]["timeout"] == 60
        assert res["evolution"]["quality_reject_threshold"] == 0.5

    def test_missing_evolution_section_created(self):
        res = _auto_fill_radix_config({})
        assert "evolution" in res