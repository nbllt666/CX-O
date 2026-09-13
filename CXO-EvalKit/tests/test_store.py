"""store 单测：状态机流转 / 倒序列表 / artifacts 落盘。tmp_path 隔离，无网络。"""
import json

import pytest

from evalkit.store import EvalStore


@pytest.fixture()
def store(tmp_path):
    s = EvalStore(str(tmp_path / "data"))
    yield s
    s.close()


def test_state_machine_legal_transition(store):
    store.create_run("r1", "memory_decay", {"safe": True})
    assert store.get_run("r1")["status"] == "running"
    store.finish_run("r1", "passed", metrics_summary={"p95_ms": 100})
    run = store.get_run("r1")
    assert run["status"] == "passed"
    assert run["finished_at"]
    assert run["metrics_summary"] == {"p95_ms": 100}
    assert run["config_snapshot"] == {"safe": True}


def test_state_machine_all_terminal_statuses(store):
    for status in ("passed", "failed", "judge_unavailable", "error"):
        rid = f"r-{status}"
        store.create_run(rid, "latency")
        store.finish_run(rid, status, error="boom" if status == "error" else None)
        assert store.get_run(rid)["status"] == status


def test_state_machine_illegal_transitions(store):
    store.create_run("r2", "latency")
    # running → running 非法
    with pytest.raises(ValueError):
        store.finish_run("r2", "running")
    # 非法终态名
    with pytest.raises(ValueError):
        store.finish_run("r2", "whatever")
    store.finish_run("r2", "failed")
    # 终态 → 任何再转换都非法（单向终态）
    with pytest.raises(ValueError):
        store.finish_run("r2", "passed")
    with pytest.raises(ValueError):
        store.finish_run("r2", "error")
    # 不存在的 run
    with pytest.raises(ValueError):
        store.finish_run("nope", "passed")
    assert store.get_run("nope") is None


def test_list_runs_desc_order(store):
    for rid in ("a", "b", "c"):
        store.create_run(rid, "latency")
    assert [r["run_id"] for r in store.list_runs()] == ["c", "b", "a"]


def test_artifacts_written(store):
    store.create_run("r3", "memory_decay")
    detail_path = store.save_run_artifacts("r3", {"case_id": "c1", "score": 4.2})
    with open(detail_path, "r", encoding="utf-8") as f:
        assert json.load(f) == {"case_id": "c1", "score": 4.2}
    report_path = store.get_report_path("r3")
    # 路径约定存在即可，不必有文件
    assert report_path.endswith("report.md")
    assert "r3" in report_path
    assert store.data_dir in report_path
