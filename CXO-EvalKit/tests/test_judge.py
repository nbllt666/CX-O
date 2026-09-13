"""judge 单测：httpx MockTransport 注入，全 Mock 不真实联网。"""
import httpx
import pytest

from evalkit.config import EvalConfig
from evalkit.judge import JudgeClient, JudgeUnavailableError


def _judge_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _client(handler) -> JudgeClient:
    cfg = EvalConfig.model_validate(
        {"target": {"base_url": "http://target.local:8000"}}
    )
    return JudgeClient(cfg, transport=httpx.MockTransport(handler))


def test_endpoint_defaults_to_target_base():
    cfg = EvalConfig.model_validate({})
    client = JudgeClient(cfg)
    assert client.endpoint == "http://host.docker.internal:8000/v1/chat/completions"


def test_endpoint_respects_judge_api_base_with_v1():
    cfg = EvalConfig.model_validate({"judge": {"api_base": "http://judge.local:9000/v1"}})
    assert JudgeClient(cfg).endpoint == "http://judge.local:9000/v1/chat/completions"


def test_score_normal_parse():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json=_judge_response('{"scores": {"accuracy": 4.5}, "reason": "ok"}')
        )

    result = _client(handler).score("评一下")
    assert result == {"scores": {"accuracy": 4.5}, "reason": "ok"}
    assert calls["n"] == 1


def test_score_markdown_wrapped_parse():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_judge_response(
                '```json\n{"scores": {"recall": 3.0}, "reason": "包裹"}\n```'
            ),
        )

    result = _client(handler).score("p")
    assert result["scores"] == {"recall": 3.0}
    assert result["reason"] == "包裹"


def test_score_out_of_range_is_case_failure_with_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json=_judge_response('{"scores": {"x": 7.5}, "reason": "越界"}')
        )

    result = _client(handler).score("p")
    assert result["judge_failed"] is True
    assert "越界" in result["error"]
    assert calls["n"] == 3  # 初次 + 2 次重试


def test_score_missing_fields_is_case_failure():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_judge_response('{"scores": {}}'))

    result = _client(handler).score("p")
    assert result["judge_failed"] is True
    assert calls["n"] == 3


def test_score_network_error_raises_unavailable():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    with pytest.raises(JudgeUnavailableError):
        _client(handler).score("p")
    assert calls["n"] == 3  # 重试计数：初次 + 2 次


def test_score_unparseable_output_is_case_failure():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_judge_response("不是 JSON"))

    result = _client(handler).score("p")
    assert result["judge_failed"] is True
    assert calls["n"] == 3
