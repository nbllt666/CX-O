"""latency suite 单测（全 Mock，禁真实网络）。

覆盖:
- percentile / summarize 纯函数: 已知样本集 → P50/P95/P99 精确断言（线性插值法）
- run_latency_suite（注入 httpx.MockTransport client）: 正常 passed 终态、
  metrics_summary 结构（总体/分组/检索延迟/并发）、artifacts detail.json 落盘
- 失败注入: chat 全 500 → 失败率 1.0 → failed；连接异常（首个探针）→ error
- 基线对比: regressed 标记（纯函数 + 集成）、baseline_run_id 不存在 / 结构缺失 → baseline_missing
- 并发档位 [1,2] 正常输出两档
- 注册: pkgutil 自动发现生效（"latency" in list_suites()）

MockTransport 关键点: handler 直接构造 httpx.Response(json=...) 会在构造期预读，
导致 resp.elapsed 永不赋值（httpx 0.28 行为）；因此统一用自定义 SyncByteStream
返回非预物化响应，elapsed 由 BoundSyncStream.close() 正常写入，
并可在流内 sleep 模拟真实延迟。统计口径正确性与 TargetClient 解耦，
经 summarize/percentile 纯函数单测独立保证。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import httpx
import pytest

from evalkit.config import EvalConfig
from evalkit.suites import list_suites
from evalkit.suites.latency import (
    PROBES,
    RETRIEVAL_QUERIES,
    RETRIEVAL_ROUNDS,
    compare_baseline_metrics,
    percentile,
    run_latency_suite,
    summarize,
)
from evalkit.store import EvalStore
from evalkit.target import TargetClient
from evalkit.ws_probe import WsProbeError, summarize_ws_turns


# ---------------------------------------------------------------------------
# Mock 基础设施
# ---------------------------------------------------------------------------
class _DelayedStream(httpx.SyncByteStream):
    """非预物化字节流: 保证 resp.elapsed 被赋值，可加延迟模拟真实耗时。"""

    def __init__(self, body: bytes, delay_seconds: float = 0.0):
        self._body = body
        self._delay = delay_seconds

    def __iter__(self):
        if self._delay:
            time.sleep(self._delay)
        yield self._body


def _json_response(payload: Dict[str, Any], delay_seconds: float = 0.0) -> httpx.Response:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        stream=_DelayedStream(body, delay_seconds),
    )


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """全端点 200 的默认 stub。"""
    path = request.url.path
    if path == "/api/chat":
        return _json_response({"response": "好的，我在。", "session_id": "s1"})
    if path == "/api/memories/search":
        return _json_response({"memories": [], "total": 0})
    if path == "/api/memories/rag":
        return _json_response({"results": []})
    return httpx.Response(404, json={"detail": f"unexpected path: {path}"})


class _Recorder:
    """按路径记录请求的 handler 包装器（线程安全）。"""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]):
        self._handler = handler
        self._lock = threading.Lock()
        self.chat_requests: List[httpx.Request] = []
        self.search_requests: List[httpx.Request] = []
        self.rag_requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            if request.url.path == "/api/chat":
                self.chat_requests.append(request)
            elif request.url.path == "/api/memories/search":
                self.search_requests.append(request)
            elif request.url.path == "/api/memories/rag":
                self.rag_requests.append(request)
        return self._handler(request)


def _make_client(config: EvalConfig, handler: Callable[[httpx.Request], httpx.Response]) -> TargetClient:
    return TargetClient(config, transport=httpx.MockTransport(handler))


def _config(**latency_overrides: Any) -> EvalConfig:
    latency: Dict[str, Any] = {
        "rounds": 2,
        "probe_timeout_seconds": 5.0,
        "concurrency_levels": [1],
        # 既有密闭用例默认禁用全双工段（无 WS stub）；全双工用例显式开启并注入 fake factory
        "ws_full_duplex": {"enabled": False},
    }
    latency.update(latency_overrides)
    return EvalConfig(
        latency=latency,
        thresholds={"latency": {"p95_ms": 2000.0, "regression_pct": 20.0, "ws_p95_ms": 800.0}},
    )


@pytest.fixture()
def store(tmp_path):
    s = EvalStore(str(tmp_path / "data"))
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 纯函数: 分位数与统计
# ---------------------------------------------------------------------------
def test_latency_suite_registered():
    """pkgutil 自动发现生效。"""
    assert "latency" in list_suites()


def test_percentile_linear_interpolation():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(vals, 50) == pytest.approx(30.0)
    assert percentile(vals, 95) == pytest.approx(48.0)
    assert percentile(vals, 99) == pytest.approx(49.6)
    assert percentile([3.0, 1.0, 2.0], 50) == pytest.approx(2.0)  # 无序输入先排序
    assert percentile([7.0], 95) == pytest.approx(7.0)  # 单样本
    assert percentile([1.0, 2.0, 3.0, 4.0], 25) == pytest.approx(1.75)  # 区间插值
    assert percentile([], 50) is None  # 空集


def test_summarize_known_samples():
    stats = summarize([500.0, 100.0, 300.0, 200.0, 400.0])
    assert stats["count"] == 5
    assert stats["mean"] == pytest.approx(300.0)
    assert stats["p50"] == pytest.approx(300.0)
    assert stats["p95"] == pytest.approx(480.0)
    assert stats["p99"] == pytest.approx(496.0)
    assert stats["min"] == pytest.approx(100.0)
    assert stats["max"] == pytest.approx(500.0)
    empty = summarize([])
    assert empty["count"] == 0
    assert empty["p50"] is None and empty["p95"] is None and empty["p99"] is None


def test_probes_contract():
    """探针集 ≥6 条、id 唯一、长短混合。"""
    assert len(PROBES) >= 6
    ids = [p["id"] for p in PROBES]
    assert len(set(ids)) == len(ids)
    assert all(p["message"].strip() for p in PROBES)
    assert any(len(p["message"]) <= 10 for p in PROBES)
    assert any(len(p["message"]) >= 40 for p in PROBES)


# ---------------------------------------------------------------------------
# suite 编排（注入 MockTransport client）
# ---------------------------------------------------------------------------
def test_run_latency_suite_passed(store):
    rounds = 2
    recorder = _Recorder(_ok_handler)
    config = _config()
    run_id = "lat-pass-1"
    store.create_run(run_id, "latency", config.to_safe_dict())

    summary = run_latency_suite(run_id, config, store, client=_make_client(config, recorder))

    # 终态与返回值
    assert summary["status"] == "passed"
    assert summary["judgment"]["passed"] is True
    run = store.get_run(run_id)
    assert run["status"] == "passed"
    assert run["metrics_summary"] == summary

    # 编排: e2e = 探针×rounds；并发档 [1] 一轮全探针
    assert len(recorder.chat_requests) == len(PROBES) * rounds + len(PROBES)
    for request in recorder.chat_requests:
        assert json.loads(request.content)["agent_id"] == "default"

    # 检索: 2 查询 × search/rag × RETRIEVAL_ROUNDS
    assert len(recorder.search_requests) == len(RETRIEVAL_QUERIES) * RETRIEVAL_ROUNDS
    assert len(recorder.rag_requests) == len(RETRIEVAL_QUERIES) * RETRIEVAL_ROUNDS
    for request in recorder.search_requests:
        body = json.loads(request.content)
        assert body["agent_id"] == "default" and body["limit"] == 5
    for request in recorder.rag_requests:
        assert request.url.params["agent_id"] == "default"
        assert request.url.params["limit"] == "5"

    # summary 结构: 总体 / 分组 / 检索 / 并发 / 基线
    assert summary["overall"]["count"] == len(PROBES) * rounds
    assert summary["overall"]["failure_rate"] == 0.0
    assert summary["overall"]["p95"] is not None
    assert set(summary["by_probe"].keys()) == {p["id"] for p in PROBES}
    for method in ("search_memories", "rag_search"):
        assert set(summary["retrieval"][method].keys()) == {q["id"] for q in RETRIEVAL_QUERIES}
        for query in RETRIEVAL_QUERIES:
            stats = summary["retrieval"][method][query["id"]]
            assert stats["count"] == RETRIEVAL_ROUNDS
            assert stats["failed_count"] == 0
            assert stats["p50"] is not None and stats["p95"] is not None
    assert set(summary["concurrency"]["levels"].keys()) == {"1"}
    assert summary["concurrency"]["levels"]["1"]["count"] == len(PROBES)
    assert summary["concurrency"]["degradation"]["1"]["p95_ratio"] == 1.0
    assert summary["baseline"]["baseline_missing"] is True  # 未配置基线

    # artifacts detail.json 落盘且体现判定
    detail_path = Path(store.data_dir) / "runs" / run_id / "detail.json"
    assert detail_path.exists()
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    assert detail["status"] == "passed"
    assert detail["judgment"]["passed"] is True
    assert set(detail["raw"]["e2e"]["samples_by_probe"].keys()) == {p["id"] for p in PROBES}
    assert len(detail["raw"]["e2e"]["samples_by_probe"]["greet_short"]) == rounds


def test_run_latency_suite_failed_all_500(store):
    """chat 一律 500 → 失败率 1.0、无成功样本 → 终态 failed。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            return httpx.Response(500, json={"detail": "boom"})
        return _ok_handler(request)

    config = _config()
    run_id = "lat-fail-1"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, handler))

    assert summary["status"] == "failed"
    assert summary["overall"]["count"] == 0
    assert summary["overall"]["p95"] is None
    assert summary["overall"]["failed_count"] == len(PROBES) * 2
    assert summary["overall"]["failure_rate"] == 1.0
    assert summary["judgment"]["passed"] is False
    # 检索不受 chat 失败影响，正常采样
    assert summary["retrieval"]["search_memories"][RETRIEVAL_QUERIES[0]["id"]]["count"] == RETRIEVAL_ROUNDS
    # 并发档失败率同样为 1.0
    assert summary["concurrency"]["levels"]["1"]["failure_rate"] == 1.0
    assert store.get_run(run_id)["status"] == "failed"


def test_run_latency_suite_error_on_connect_failure(store):
    """首个探针即连接层失败 → 主服务不可达 → 终态 error。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    config = _config()
    run_id = "lat-err-1"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, handler))

    assert summary["status"] == "error"
    run = store.get_run(run_id)
    assert run["status"] == "error"
    assert "主服务不可达" in run["error"]
    detail_path = Path(store.data_dir) / "runs" / run_id / "detail.json"
    assert detail_path.exists()


# ---------------------------------------------------------------------------
# 基线对比
# ---------------------------------------------------------------------------
def _seed_baseline(store: EvalStore, run_id: str, metrics_summary: Dict[str, Any]) -> None:
    store.create_run(run_id, "latency")
    store.finish_run(run_id, "passed", metrics_summary=metrics_summary)


def test_compare_baseline_metrics_pure():
    base = {"p50": 100.0, "p95": 200.0}
    # P95 +50% > 20% → 回归；P50 +20% 恰在阈值上（严格大于才标记）
    result = compare_baseline_metrics({"p50": 120.0, "p95": 300.0}, base, regression_pct=20.0)
    assert result["metrics"]["p95"]["delta_ms"] == pytest.approx(100.0)
    assert result["metrics"]["p95"]["delta_pct"] == pytest.approx(50.0)
    assert result["metrics"]["p95"]["regressed"] is True
    assert result["metrics"]["p50"]["regressed"] is False
    assert result["regressed"] is True  # 顶层由 P95 驱动
    # 延迟下降 → 不算回归
    improved = compare_baseline_metrics({"p50": 50.0, "p95": 100.0}, base, regression_pct=20.0)
    assert improved["regressed"] is False
    # 指标缺失 → missing 标记
    missing = compare_baseline_metrics({"p50": 1.0}, base, regression_pct=20.0)
    assert missing["metrics"]["p95"]["missing"] is True
    assert missing["regressed"] is False


def test_run_baseline_comparison(store):
    _seed_baseline(store, "base-1", {"overall": {"p50": 100.0, "p95": 200.0}})
    config = _config(baseline_run_id="base-1")
    run_id = "lat-base-1"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, _ok_handler))

    baseline = summary["baseline"]
    assert baseline["baseline_missing"] is False
    assert baseline["baseline_run_id"] == "base-1"
    comparison = baseline["comparison"]
    assert comparison["metrics"]["p95"]["baseline_ms"] == pytest.approx(200.0)
    # MockTransport 下当前延迟远低于基线 → 负变化、不回归
    assert comparison["metrics"]["p95"]["delta_pct"] < 0
    assert comparison["regressed"] is False


def test_run_baseline_missing_run(store):
    config = _config(baseline_run_id="ghost")
    run_id = "lat-base-ghost"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, _ok_handler))

    assert summary["baseline"]["baseline_missing"] is True
    assert "不存在" in summary["baseline"]["reason"]
    assert "comparison" not in summary["baseline"]


def test_run_baseline_missing_structure(store):
    _seed_baseline(store, "base-2", {"foo": 1})  # 缺少 overall 延迟结构
    config = _config(baseline_run_id="base-2")
    run_id = "lat-base-struct"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, _ok_handler))

    assert summary["baseline"]["baseline_missing"] is True
    assert "overall" in summary["baseline"]["reason"]


# ---------------------------------------------------------------------------
# 并发档位
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 全双工语音链路（WS voice.dual_stream）
# ---------------------------------------------------------------------------
class _FakeWsProbe:
    """fake 全双工探测器: 返回预设轮次或按序抛错。"""

    def __init__(self, turns: List[Dict[str, Any]], error: Optional[Exception] = None):
        self._turns = turns
        self._error = error
        self.calls: List[str] = []

    def run_turn(self, agent_id: str, turn_index: int) -> Dict[str, Any]:
        self.calls.append(f"{agent_id}#{turn_index}")
        if self._error is not None:
            raise self._error
        return self._turns[turn_index % len(self._turns)]


def _ws_turn(index: int, partial: float, first: float, speech_end: float = 800.0,
             **extra: Any) -> Dict[str, Any]:
    timings = {"asr_first_partial": partial, "asr_final": partial + 500.0,
               "tts_first_audio": first}
    timings.update(extra)
    return {"turn_index": index, "timings": timings, "timeout": False, "error": None,
            "asr_text": "你好", "speech_end_offset_ms": speech_end}


def _agents_handler(state: Dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """在默认 stub 上叠加 /api/agents 创建/删除。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/agents" and request.method == "POST":
            body = json.loads(request.content)
            aid = f"agent-fake{len(state['created'])}"
            state["created"].append({**body, "id": aid})
            return _json_response({"status": "success", "agent": {**body, "id": aid}})
        if request.url.path.startswith("/api/agents/") and request.method == "DELETE":
            aid = request.url.path.rsplit("/", 1)[1]
            state["deleted"].append(aid)
            return _json_response({"status": "success"})
        return _ok_handler(request)

    return handler


def test_summarize_ws_turns_pure():
    """全双工统计纯函数: 主指标 = 首个 partial → 首包（投机响应体感），钳 0/超时/错误口径。"""
    turns = [
        _ws_turn(0, partial=500.0, first=1500.0, speech_end=800.0),    # partial→首包 1000
        _ws_turn(1, partial=1800.0, first=1900.0, speech_end=1800.0),  # partial→首包 100
        _ws_turn(2, partial=2800.0, first=4200.0, speech_end=2800.0),  # partial→首包 1400
        {"turn_index": 3, "timings": {}, "timeout": True, "error": None, "asr_text": ""},
        {"turn_index": 4, "timings": {}, "timeout": False, "error": "boom", "asr_text": ""},
    ]
    stats = summarize_ws_turns(turns)
    main = stats["first_partial_to_first_audio"]
    assert main["count"] == 3
    assert main["mean"] == pytest.approx(833.3)   # (1000+100+1400)/3
    assert main["p95"] == pytest.approx(1360.0)   # 线性插值: 1000+0.9*(1400-1000)
    assert main["min"] == pytest.approx(100.0)
    assert main["max"] == pytest.approx(1400.0)
    # 辅助口径: 说完（能量）→ 首包
    assert stats["speech_end_to_first_audio"]["count"] == 3
    assert stats["speech_end_to_first_audio"]["mean"] == pytest.approx(733.3)
    # 诊断: 定稿→首包（asr_final=partial+500；t1 竞态负值钳 0）
    assert stats["asr_final_to_first_audio"]["count"] == 3
    assert stats["asr_final_to_first_audio"]["mean"] == pytest.approx(466.7)  # (500+0+900)/3
    assert stats["stages"]["asr_final"]["count"] == 3
    assert stats["timeouts"] == 1 and stats["errors"] == 1
    assert stats["stream_to_first_audio"]["count"] == 3


def test_run_latency_suite_ws_full_duplex_passed(store):
    state: Dict[str, Any] = {"created": [], "deleted": []}
    config = _config(ws_full_duplex={"enabled": True, "turns": 3, "turn_timeout_seconds": 5.0})
    factory = lambda: _FakeWsProbe([
        _ws_turn(0, partial=500.0, first=1100.0),
        _ws_turn(1, partial=500.0, first=1300.0),
        _ws_turn(2, partial=500.0, first=1000.0),
    ])
    run_id = "lat-ws-pass"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(
        run_id, config, store,
        client=_make_client(config, _agents_handler(state)),
        ws_probe_factory=factory,
    )

    assert summary["status"] == "passed"  # partial→首包 P95 780 ≤ 800
    ws = summary["ws_full_duplex"]
    assert ws["judgment"]["passed"] is True
    assert ws["judgment"]["ws_p95"] == pytest.approx(780.0)  # 线性插值: 600+0.9*(800-600)
    assert ws["judgment"]["threshold_ws_p95_ms"] == 800.0
    assert len(ws["turns"]) == 3
    assert ws["stats"]["first_partial_to_first_audio"]["count"] == 3
    # 一次性 eval agent 已创建并删除（真实模式隔离约定）
    assert len(state["created"]) == 1 and state["deleted"] == [state["created"][0]["id"]]


def test_run_latency_suite_ws_p95_exceeds_threshold(store):
    state: Dict[str, Any] = {"created": [], "deleted": []}
    config = _config(ws_full_duplex={"enabled": True, "turns": 2, "turn_timeout_seconds": 5.0})
    factory = lambda: _FakeWsProbe([
        _ws_turn(0, partial=500.0, first=2500.0),
        _ws_turn(1, partial=500.0, first=2600.0),
    ])
    run_id = "lat-ws-fail"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(
        run_id, config, store,
        client=_make_client(config, _agents_handler(state)),
        ws_probe_factory=factory,
    )

    assert summary["status"] == "failed"  # partial→首包 P95 2090 > 800（REST 指标仍正常产出）
    ws = summary["ws_full_duplex"]
    assert ws["judgment"]["passed"] is False
    assert "超过阈值" in ws["failure_reason"]
    assert summary["overall"]["count"] == len(PROBES) * 2  # REST 部分不受影响
    assert store.get_run(run_id)["status"] == "failed"


def test_run_latency_suite_ws_probe_unavailable(store):
    state: Dict[str, Any] = {"created": [], "deleted": []}
    config = _config(ws_full_duplex={"enabled": True, "turns": 1, "turn_timeout_seconds": 5.0})
    factory = lambda: (_ for _ in ()).throw(WsProbeError("语音资产缺失"))
    run_id = "lat-ws-err"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(
        run_id, config, store,
        client=_make_client(config, _agents_handler(state)),
        ws_probe_factory=factory,
    )

    assert summary["status"] == "failed"
    ws = summary["ws_full_duplex"]
    assert "WsProbeError" in ws["error"]
    assert "语音资产缺失" in ws["error"]
    assert summary["overall"]["p95"] is not None  # REST 指标仍产出


def test_run_latency_suite_ws_skipped_in_mock(store):
    config = _config()
    config = EvalConfig.model_validate({**config.model_dump(), "mock": {"enabled": True}})
    run_id = "lat-ws-mock"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, _ok_handler))

    ws = summary["ws_full_duplex"]
    assert ws["skipped"] is True
    assert summary["status"] == "passed"  # skipped 不影响终态


# ---------------------------------------------------------------------------
# 并发档位
# ---------------------------------------------------------------------------
def test_run_concurrency_two_levels(store):
    config = _config(concurrency_levels=[1, 2], rounds=1)
    run_id = "lat-conc"
    store.create_run(run_id, "latency")
    summary = run_latency_suite(run_id, config, store, client=_make_client(config, _ok_handler))

    levels = summary["concurrency"]["levels"]
    assert set(levels.keys()) == {"1", "2"}
    for key in ("1", "2"):
        assert levels[key]["count"] == len(PROBES)
        assert levels[key]["failed_count"] == 0
        assert levels[key]["failure_rate"] == 0.0
        assert levels[key]["p50"] is not None and levels[key]["p95"] is not None
    degradation = summary["concurrency"]["degradation"]
    assert degradation["1"]["p95_ratio"] == 1.0
    ratio = degradation["2"]["p95_ratio"]
    assert isinstance(ratio, float) and ratio >= 0
