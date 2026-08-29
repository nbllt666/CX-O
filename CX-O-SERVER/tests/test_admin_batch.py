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


# ===========================================================================
# 路由委托等价：/admin/batch 内联 _run_step + 循环改为委托 AdminBatchExecutor
# 后，端点对外行为（顺序/并行编排、失败步处理、响应结构）必须保持不变。
# ===========================================================================
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from server.api.routers import admin as admin_router_mod  # noqa: E402


def _batch_client(monkeypatch, cp):
    """挂载 admin 路由：跳过鉴权、注入 MagicMock control_plane、审计打桩。"""
    monkeypatch.setattr(admin_router_mod, "_admin_guard", lambda *a, **k: None)
    monkeypatch.setattr(admin_router_mod, "_control_plane", cp)
    # audit_now 仅在 inject_admin_runtime 后存在；未注入路径下打桩避免 NameError
    monkeypatch.setattr(
        admin_router_mod, "audit_now", lambda *a, **k: {"id": "noop"}, raising=False
    )
    app = FastAPI()
    app.include_router(admin_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestRouterDelegationEquivalence:
    def test_sequential_stop_on_error(self, monkeypatch):
        """失败步 ok=False 携 error，stop_on_error 中止后续步（与原内联一致）。"""
        cp, calls = _plane(fail_on="update")
        c = _batch_client(monkeypatch, cp)
        r = c.post("/admin/batch", json={
            "request_id": "r-1", "mode": "sequential", "stop_on_error": True,
            "steps": [
                {"target": "autonomy", "action": "enable"},
                {"target": "agent", "action": "update"},
                {"target": "config", "action": "reload"},
            ]})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["mode"] == "sequential"
        steps = body["steps"]
        # 第三步被中止，仅返回前两步
        assert [s["step"] for s in steps] == [0, 1]
        assert steps[0]["ok"] is True
        assert steps[1]["ok"] is False
        assert steps[1]["result"] == {"error": "boom"}
        assert "duration_ms" in steps[1]
        assert calls["n"] == 2

    def test_parallel_all_executed(self, monkeypatch):
        """并行模式全步执行、结构对齐 executor 契约。"""
        cp, calls = _plane()
        c = _batch_client(monkeypatch, cp)
        r = c.post("/admin/batch", json={
            "request_id": "r-2", "mode": "parallel",
            "steps": [{"target": "a", "action": "x"},
                      {"target": "b", "action": "y"},
                      {"target": "c", "action": "z"}]})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["mode"] == "parallel"
        assert len(body["steps"]) == 3
        assert calls["n"] == 3
        assert all(s["ok"] for s in body["steps"])
        assert {s["step"] for s in body["steps"]} == {0, 1, 2}
        assert all("duration_ms" in s for s in body["steps"])

    def test_agent_id_none_normalized_and_result_shell(self, monkeypatch):
        """agent_id 显式 None 归一化为 default；成功步 result 为 dispatch 外壳。"""
        cp, calls = _plane()
        c = _batch_client(monkeypatch, cp)
        r = c.post("/admin/batch", json={
            "request_id": "r-3", "mode": "sequential",
            "steps": [{"target": "t", "action": "a", "agent_id": None, "params": {}}]})
        assert r.status_code == 200
        step = r.json()["steps"][0]
        assert step["ok"] is True
        # result 保持 dispatch 外壳结构（与原内联返回一致）
        assert step["result"]["ok"] is True
        assert step["result"]["action"] == "a"
        _, kwargs = cp.dispatch.call_args
        assert kwargs["agent_id"] == "default"
        assert kwargs["request_id"] == "r-3"

    def test_unknown_mode_falls_back_sequential(self, monkeypatch):
        """未知 mode 按原内联语义回退 sequential，响应 mode 字段原样回显。"""
        cp, calls = _plane()
        c = _batch_client(monkeypatch, cp)
        r = c.post("/admin/batch", json={
            "request_id": "r-4", "mode": "weird",
            "steps": [{"target": "t", "action": "a"},
                      {"target": "t", "action": "b"}]})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "weird"
        assert calls["n"] == 2
        assert [s["ok"] for s in body["steps"]] == [True, True]