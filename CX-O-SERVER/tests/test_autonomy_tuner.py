"""CX-O-Autonomy P3-T2 蒸馏接入 + Tuner 反馈闭环单测。

覆盖：
① FeedbackEvaluator 无 tuner_provider → submitted False
② 有 tuner_provider 且成功返回 → submitted True（含 dict 返回 provider 与
   make_tuner_provider + 200 桥接两个子场景）
③ submit_to_tuner / build_tuner_feedback 构造 body 对齐 FeedbackIn：
   source="judge"、metadata.origin="autonomy"、含 prompt/response_chosen/
   response_rejected/timestamp/quality_score
④ Tuner 返回 4xx / 5xx / 连接失败 → submitted False 不冒泡（submit_to_tuner
   直接调用 + FeedbackEvaluator 全链路两个层级）
⑤ Consolidator 无蒸馏 provider → {"consolidated": N, "distilled": False}
⑥ Consolidator 有 provider → 返回 provider 结果；另覆盖蒸馏服务实例注入路径
   （start→finalize 真实调用、服务异常降级不冒泡、服务优先于 provider）

运行：python -m pytest tests/test_autonomy_tuner.py -q
"""
import httpx
import pytest

import server.autonomy.reflection.feedback.evaluator as evaluator_mod
from server.autonomy.reflection import Consolidator, FeedbackEvaluator
from server.autonomy.reflection.feedback.evaluator import (
    build_tuner_feedback,
    make_tuner_provider,
    submit_to_tuner,
)
from types import SimpleNamespace


# ================================================================ fake 依赖
class FakeResponse:
    """httpx.Response 替身：可配置 status / text / content，json() 为 async。"""

    def __init__(self, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content

    def json(self):
        """httpx.Response.json 为同步方法（对齐真实行为，避免泄漏协程）。"""
        return {"feedback_id": "fb-1", "accepted": True, "reason": "accepted"}


class FakeHTTPClient:
    """httpx.AsyncClient 替身：记录 POST 调用；按预设 status 或异常响应。

    - error 非 None 时 post 抛该异常（模拟连接失败/超时）
    - status_code >= 400 时返回 4xx/5xx 响应
    - 否则返回 200
    """

    def __init__(self, status_code=200, error=None):
        self.status_code = status_code
        self.error = error
        self.calls = []

    async def post(self, url, json=None, **kwargs):
        self.calls.append({"url": url, "json": json, **kwargs})
        if self.error is not None:
            raise self.error
        if self.status_code >= 400:
            return FakeResponse(self.status_code, text=f"err {self.status_code}")
        return FakeResponse(
            self.status_code,
            content=b'{"feedback_id":"fb-1","accepted":true,"reason":"accepted"}',
        )


class FakeDistillationService:
    """DistillationService 替身：记录 start/finalize 调用参数，可注入异常。"""

    def __init__(self, start_error=None, finalize_error=None):
        self.start_error = start_error
        self.finalize_error = finalize_error
        self.start_calls = []
        self.finalize_calls = []

    async def start_distillation(
        self, source_type, source_ref, template_id, max_turns, ask_user_on_ambiguity
    ):
        self.start_calls.append(
            {
                "source_type": source_type,
                "source_ref": source_ref,
                "template_id": template_id,
                "max_turns": max_turns,
                "ask_user_on_ambiguity": ask_user_on_ambiguity,
            }
        )
        if self.start_error is not None:
            raise self.start_error
        return SimpleNamespace(
            session_id="sess-1", initial_state="S_PREREAD", preread_summary="summary"
        )

    async def finalize_distillation(self, session_id, override_decision):
        self.finalize_calls.append(
            {"session_id": session_id, "override_decision": override_decision}
        )
        if self.finalize_error is not None:
            raise self.finalize_error
        return SimpleNamespace(
            stored=True,
            location="memories",
            memory_id=1,
            metadata={"source": "text"},
            reason="ok",
        )


@pytest.fixture
def fake_client(monkeypatch):
    """把 evaluator 模块内的 get_shared_http_client 替换为可控 FakeHTTPClient。"""

    def _install(client):
        monkeypatch.setattr(evaluator_mod, "get_shared_http_client", lambda: client)
        return client

    return _install


@pytest.fixture(autouse=True)
def _tuner_url_env(monkeypatch):
    """固定 Tuner 地址，避免测试依赖本机配置状态。"""
    monkeypatch.setenv("CXO_TUNER_URL", "http://tuner.test:8300")
    yield


# ================================================================ ① 无 provider → submitted False
class TestEvaluatorNoProvider:
    @pytest.mark.asyncio
    async def test_submitted_false_without_provider(self):
        ev = FeedbackEvaluator()  # 无 tuner_provider
        for r in ("success", "failed", "blocked", "skipped"):
            result = await ev.evaluate({"action": "x", "result": r})
            assert result["submitted"] is False


# ================================================================ ② 有 provider 且成功 → submitted True
class TestEvaluatorWithProvider:
    @pytest.mark.asyncio
    async def test_provider_dict_submitted_true(self):
        async def provider(signal, action_result):
            return {"submitted": True}

        ev = FeedbackEvaluator(tuner_provider=provider)
        result = await ev.evaluate({"action": "write_memory", "result": "success"})

        assert result["submitted"] is True
        assert result["signal"] == "positive"

    @pytest.mark.asyncio
    async def test_make_tuner_provider_http_200_submitted_true(self, fake_client):
        client = fake_client(FakeHTTPClient(status_code=200))
        ev = FeedbackEvaluator(tuner_provider=make_tuner_provider())
        result = await ev.evaluate({"action": "write_memory", "result": "success"})

        assert result["submitted"] is True
        # 桥接 provider 实际发起了 POST
        assert len(client.calls) == 1
        assert client.calls[0]["url"].endswith("/api/v1/feedback")


# ================================================================ ③ body 对齐 FeedbackIn
class TestSubmitToTunerBody:
    @pytest.mark.asyncio
    async def test_submit_to_tuner_builds_feedbackin_aligned_body(self, fake_client):
        client = fake_client(FakeHTTPClient(status_code=200))
        result = await submit_to_tuner(
            {
                "prompt": "请写一条日记",
                "response_chosen": "今天收获满满。",
                "response_rejected": "（无响应）",
            }
        )

        assert result["submitted"] is True
        body = client.calls[0]["json"]
        # 必填字段齐全
        assert body["prompt"] == "请写一条日记"
        assert body["response_chosen"] == "今天收获满满。"
        assert body["response_rejected"] == "（无响应）"
        # 自主评估来源用枚举内 "judge"，metadata 标注 origin="autonomy"
        assert body["source"] == "judge"
        assert body["metadata"]["origin"] == "autonomy"
        assert "timestamp" in body and body["timestamp"]
        assert 0.0 <= body["quality_score"] <= 1.0

    def test_build_tuner_feedback_shape(self):
        fb = build_tuner_feedback(
            "positive", {"action": "write_memory", "result": "success"}
        )

        assert fb["source"] == "judge"
        assert fb["metadata"]["origin"] == "autonomy"
        assert fb["metadata"]["action"] == "write_memory"
        assert fb["metadata"]["signal"] == "positive"
        assert fb["prompt"] and fb["response_chosen"] and fb["response_rejected"]
        assert fb["timestamp"]
        assert fb["quality_score"] == 1.0  # success → 1.0

    @pytest.mark.asyncio
    async def test_submit_to_tuner_missing_required_does_not_post(self, fake_client):
        client = fake_client(FakeHTTPClient(status_code=200))
        result = await submit_to_tuner({"prompt": "只有 prompt"})

        assert result["submitted"] is False
        assert "error" in result
        assert client.calls == []  # 未发请求


# ================================================================ ④ 4xx/5xx/连接失败 → submitted False 不冒泡
class TestSubmitToTunerFailures:
    @pytest.mark.asyncio
    async def test_http_400_not_submitted(self, fake_client):
        fake_client(FakeHTTPClient(status_code=400))
        result = await submit_to_tuner(
            {"prompt": "p", "response_chosen": "c", "response_rejected": "r"}
        )
        assert result["submitted"] is False
        assert result["error"] == "tuner_http_400"

    @pytest.mark.asyncio
    async def test_http_500_not_submitted(self, fake_client):
        fake_client(FakeHTTPClient(status_code=500))
        result = await submit_to_tuner(
            {"prompt": "p", "response_chosen": "c", "response_rejected": "r"}
        )
        assert result["submitted"] is False
        assert result["error"] == "tuner_http_500"

    @pytest.mark.asyncio
    async def test_connection_failure_not_submitted(self, fake_client):
        fake_client(FakeHTTPClient(error=httpx.ConnectError("connection refused")))
        result = await submit_to_tuner(
            {"prompt": "p", "response_chosen": "c", "response_rejected": "r"}
        )
        assert result["submitted"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_evaluator_does_not_bubble_on_http_500(self, fake_client):
        # Tuner 不可达/服务端错误 → evaluator.submitted False，且 evaluate 不抛异常
        fake_client(FakeHTTPClient(status_code=500))
        ev = FeedbackEvaluator(tuner_provider=make_tuner_provider())
        result = await ev.evaluate({"action": "write_memory", "result": "success"})

        assert result["submitted"] is False
        assert result["score"] == 1.0

    @pytest.mark.asyncio
    async def test_evaluator_does_not_bubble_on_connection_failure(self, fake_client):
        fake_client(FakeHTTPClient(error=httpx.ConnectError("refused")))
        ev = FeedbackEvaluator(tuner_provider=make_tuner_provider())
        result = await ev.evaluate({"action": "write_memory", "result": "success"})

        assert result["submitted"] is False


# ================================================================ ⑤ Consolidator 无蒸馏 provider
class TestConsolidatorNoProvider:
    @pytest.mark.asyncio
    async def test_returns_distilled_false(self):
        c = Consolidator()
        result = await c.consolidate([{"a": 1}, {"b": 2}, {"c": 3}])

        assert result == {"consolidated": 3, "distilled": False}


# ================================================================ ⑥ Consolidator 有 provider / 服务注入
class TestConsolidatorWithProvider:
    @pytest.mark.asyncio
    async def test_returns_provider_result(self):
        def provider(entries):
            return {"consolidated": len(entries), "distilled": True, "summary": "ok"}

        c = Consolidator(distillation_provider=provider)
        result = await c.consolidate([{"a": 1}])

        assert result["distilled"] is True
        assert result["summary"] == "ok"


class TestConsolidatorWithService:
    @pytest.mark.asyncio
    async def test_service_start_finalize_closed_loop(self):
        svc = FakeDistillationService()
        c = Consolidator(distillation_service=svc)
        result = await c.consolidate(
            [{"action": "write_memory", "result": "success"}]
        )

        assert result["distilled"] is True
        assert result["session_id"] == "sess-1"
        assert result["finalized"] is True
        assert result["location"] == "memories"
        assert result["memory_id"] == 1
        # start 被调用且 source_type 对齐蒸馏服务 text 模态
        assert len(svc.start_calls) == 1
        assert svc.start_calls[0]["source_type"] == "text"
        assert "write_memory" in svc.start_calls[0]["source_ref"]
        # finalize 用 start 返回的 session_id 调用
        assert len(svc.finalize_calls) == 1
        assert svc.finalize_calls[0]["session_id"] == "sess-1"
        assert svc.finalize_calls[0]["override_decision"] is None

    @pytest.mark.asyncio
    async def test_service_error_degrades_without_bubble(self):
        svc = FakeDistillationService(start_error=RuntimeError("distill down"))
        c = Consolidator(distillation_service=svc)
        result = await c.consolidate([{"a": 1}])

        assert result["distilled"] is False
        assert result["consolidated"] == 1
        assert "error" in result

    @pytest.mark.asyncio
    async def test_service_priority_over_provider(self):
        svc = FakeDistillationService()

        def provider(entries):
            return {"distilled": True, "via": "provider"}

        c = Consolidator(
            distillation_service=svc, distillation_provider=provider
        )
        result = await c.consolidate([{"a": 1}])

        # 注入蒸馏服务实例时优先走真实服务，而非 provider 回调
        assert result["distilled"] is True
        assert result["session_id"] == "sess-1"
        assert "via" not in result
