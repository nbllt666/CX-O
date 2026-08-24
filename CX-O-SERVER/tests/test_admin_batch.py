"""server.core.admin.batch 测试：串行 stop_on_error 中止 + 并行聚合。

运行：python -m pytest tests/test_admin_batch.py -v
"""
import asyncio
import pytest
from unittest.mock import MagicMock

from server.core.admin.batch import AdminBatchExecutor


def _plane(result_dicts=None, fail_on=None):
    """dispatch 返回按顺序给定的成功结果；fail_on 命中 action 时抛 ValueError。"""
    cp = MagicMock()
    calls = {"n": 0}

    def dispatch(action, target, request_id, agent_id="default", params=None):
        calls["n"] += 1
        if fail_on is not None and action == fail_on:
            raise ValueError("boom")
        rets = result_dicts if result_dicts is not None else [{"action": action, "ok": True, "result": {"x": calls["n"]}}]
        r = rets[min(calls["n"] - 1, len(rets) - 1)]
        return dict(r)

    cp.dispatch.side_effect = dispatch
    return cp, calls


def test_sequential_stop_on_error_aborts():
    cp, calls = _plane(fail_on="update")
    exe = AdminBatchExecutor(cp)
    out = asyncio.run(exe.execute("r", "sequential",
                                  [{"target": "autonomy", "action": "enable"},
                                   {"target": "agent", "action": "update"},
                                   {"target": "config", "action": "reload"}],
                                  stop_on_error=True))
    assert out["mode"] == "sequential"
    steps = out["steps"]
    assert steps[0]["ok"] is True
    assert steps[1]["ok"] is False
    assert steps[1]["result"]["error"] == "boom"
    # 第二步失败即中止，第三步不执行
    assert calls["n"] == 2


def test_sequential_no_stop_continues():
    cp, calls = _plane(fail_on="update")
    exe = AdminBatchExecutor(cp)
    out = asyncio.run(exe.execute("r", "sequential",
                                  [{"target": "agent", "action": "update"},
                                   {"target": "config", "action": "reload"}],
                                  stop_on_error=False))
    assert calls["n"] == 2
    assert out["steps"][1]["ok"] is True


def test_parallel_number_of_calls():
    cp, calls = _plane()
    exe = AdminBatchExecutor(cp)
    steps = [{"target": "autonomy", "action": "enable"},
             {"target": "agent", "action": "create"},
             {"target": "config", "action": "reload"}]
    out = asyncio.run(exe.execute("r", "parallel", steps, stop_on_error=True))
    assert out["mode"] == "parallel"
    assert len(out["steps"]) == 3
    assert calls["n"] == 3
    for s in out["steps"]:
        assert s["ok"] is True
        assert "duration_ms" in s
        assert s["step"] in (0, 1, 2)


def test_parallel_agg_on_failure():
    cp, calls = _plane(fail_on="create")
    exe = AdminBatchExecutor(cp)
    out = asyncio.run(exe.execute("r", "parallel",
                                  [{"target": "agent", "action": "create"},
                                   {"target": "config", "action": "reload"}],
                                  stop_on_error=True))
    ok_by_step = [s["ok"] for s in out["steps"]]
    assert False in ok_by_step
    assert calls["n"] == 2  # parallel 不因单步失败中止


def test_unknown_mode_raises():
    cp, calls = _plane()
    exe = AdminBatchExecutor(cp)
    with pytest.raises(ValueError):
        asyncio.run(exe.execute("r", "pipeline", [{"target": "config", "action": "reload"}], True))