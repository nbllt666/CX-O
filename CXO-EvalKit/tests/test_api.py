"""API 冒烟（TestClient，隔离 data_dir，无真实网络/无真实主服务）。"""
import time

import pytest
from fastapi.testclient import TestClient

from evalkit.api import create_app
from evalkit.config import EvalConfig
from evalkit.suites import SUITE_REGISTRY, register_suite


@pytest.fixture()
def client(tmp_path):
    cfg = EvalConfig.model_validate({"data_dir": str(tmp_path / "data")})
    with TestClient(create_app(cfg)) as c:
        yield c


def test_health_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    # suite 由 pkgutil 自动发现注册（已落地 suite 逐批纳入断言）
    assert set(body["suites"]) >= {"latency", "memory_decay"}


def test_suites_endpoint(client):
    resp = client.get("/api/v1/suites")
    assert resp.status_code == 200
    assert set(resp.json()["suites"]) >= {"latency", "memory_decay"}


def test_post_run_unregistered_suite_400(client):
    resp = client.post(
        "/api/v1/runs", json={"suite": "not_exist", "config_overrides": {}}
    )
    assert resp.status_code == 400
    assert "not_exist" in resp.json()["detail"]


def test_runs_list_and_detail_404(client):
    assert client.get("/api/v1/runs").json() == {"runs": []}
    assert client.get("/api/v1/runs/missing").status_code == 404
    assert client.get("/api/v1/runs/missing/report").status_code == 404


def test_post_run_registered_suite_e2e(tmp_path):
    """注册桩 suite 验证 runner 全链路：202 → 后台线程 → 终态 + 明细落盘。"""

    @register_suite("dummy_ok")
    def _dummy(run_id, config, store):
        store.save_run_artifacts(run_id, {"ok": True})
        store.finish_run(run_id, "passed", metrics_summary={"ok": 1})

    try:
        cfg = EvalConfig.model_validate({"data_dir": str(tmp_path / "data")})
        with TestClient(create_app(cfg)) as c:
            resp = c.post("/api/v1/runs", json={"suite": "dummy_ok"})
            assert resp.status_code == 202
            run_id = resp.json()["run_id"]
            # 轮询等待后台线程终态化（最多 ~5s）
            deadline = time.time() + 5
            status = "running"
            while time.time() < deadline:
                run = c.get(f"/api/v1/runs/{run_id}").json()
                status = run.get("status")
                if status != "running":
                    break
                time.sleep(0.05)
            assert status == "passed"
    finally:
        SUITE_REGISTRY.pop("dummy_ok", None)  # 防止污染其他用例的注册表断言
