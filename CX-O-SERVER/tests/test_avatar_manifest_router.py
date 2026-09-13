"""头像清单上报路由 + 注册表单测（spec enhance-emotion-tts-and-action-presets Task 5.1）。

覆盖：
- 上报→查询闭环：POST 覆盖式更新 → GET 返回快照（reported=True）
- 覆盖语义：同 agent 重复上报以最新为准（切换头像重新上报场景）
- 未上报安全回退：GET 未上报 agent 返回空清单 + reported=False，不报错
- 参数校验 422：缺 agent_id / 空 agent_id / 类型非法
- expressions 省略兼容：缺省为空清单
- 多 agent 隔离：互不串扰
- 注册表线程安全：并发覆盖不撕裂
- 进程级单例：get_avatar_manifest_registry 返回同一实例

运行：python -m pytest tests/test_avatar_manifest_router.py -q
"""
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import avatar_manifest as avatar_manifest_router_mod
from server.services.avatar_manifest_registry import (
    AvatarManifestRegistry,
    get_avatar_manifest_registry,
)


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    """每个用例使用全新注册表实例，保证用例隔离（不污染进程级单例）。"""
    # 路由内延迟 import 命中模块全局变量，直接替换单例缓存即可隔离
    import server.services.avatar_manifest_registry as reg_mod

    monkeypatch.setattr(reg_mod, "_registry", AvatarManifestRegistry())
    yield
    monkeypatch.setattr(reg_mod, "_registry", None)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(avatar_manifest_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- 上报/查询闭环
def test_report_then_get_roundtrip(client):
    """上报 → 查询：返回上报的清单与 reported=True。"""
    r = client.post(
        "/avatar-manifest",
        json={"agent_id": "agent-1", "actions": ["wave", "nod"], "expressions": ["smile"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["agent_id"] == "agent-1"
    assert body["actions_count"] == 2
    assert body["expressions_count"] == 1
    assert body["updated_at"] is not None

    r = client.get("/avatar-manifest/agent-1")
    assert r.status_code == 200
    snap = r.json()
    assert snap["actions"] == ["wave", "nod"]
    assert snap["expressions"] == ["smile"]
    assert snap["reported"] is True
    assert snap["updated_at"] == body["updated_at"]


def test_report_overwrite_keeps_latest(client):
    """覆盖语义：同 agent 重复上报以最新为准（切换头像重新上报场景）。"""
    client.post("/avatar-manifest", json={"agent_id": "a", "actions": ["old1"], "expressions": ["e1"]})
    client.post("/avatar-manifest", json={"agent_id": "a", "actions": ["new1", "new2"], "expressions": ["e2"]})

    snap = client.get("/avatar-manifest/a").json()
    assert snap["actions"] == ["new1", "new2"]
    assert snap["expressions"] == ["e2"]


def test_get_unreported_returns_empty_safely(client):
    """未上报安全回退：返回空清单 + reported=False，不报错。"""
    r = client.get("/avatar-manifest/never-reported")
    assert r.status_code == 200
    snap = r.json()
    assert snap["actions"] == []
    assert snap["expressions"] == []
    assert snap["updated_at"] is None
    assert snap["reported"] is False


def test_expressions_omitted_defaults_empty(client):
    """expressions 可省略：缺省按空清单处理。"""
    r = client.post("/avatar-manifest", json={"agent_id": "a", "actions": ["wave"]})
    assert r.status_code == 200
    assert r.json()["expressions_count"] == 0

    snap = client.get("/avatar-manifest/a").json()
    assert snap["expressions"] == []


def test_multiple_agents_isolated(client):
    """多 agent 隔离：各自缓存互不串扰。"""
    client.post("/avatar-manifest", json={"agent_id": "a", "actions": ["a1"]})
    client.post("/avatar-manifest", json={"agent_id": "b", "actions": ["b1", "b2"]})

    assert client.get("/avatar-manifest/a").json()["actions"] == ["a1"]
    assert client.get("/avatar-manifest/b").json()["actions"] == ["b1", "b2"]


# ---------------------------------------------------------------- 参数校验
def test_report_missing_agent_id_422(client):
    r = client.post("/avatar-manifest", json={"actions": ["wave"]})
    assert r.status_code == 422


def test_report_empty_agent_id_422(client):
    r = client.post("/avatar-manifest", json={"agent_id": "", "actions": ["wave"]})
    assert r.status_code == 422


def test_report_actions_wrong_type_422(client):
    r = client.post("/avatar-manifest", json={"agent_id": "a", "actions": "wave"})
    assert r.status_code == 422


def test_report_missing_body_422(client):
    r = client.post("/avatar-manifest", json={})
    assert r.status_code == 422


# ---------------------------------------------------------------- 注册表
def test_registry_singleton():
    """进程级单例：多次获取返回同一实例。"""
    assert get_avatar_manifest_registry() is get_avatar_manifest_registry()


def test_registry_concurrent_upsert_no_tear():
    """并发覆盖：每个 agent 的清单值始终完整（不撕裂），最终值为写入集合之一。"""
    reg = AvatarManifestRegistry()
    payloads = {f"agent-{i}": [f"action-{i}-{j}" for j in range(64)] for i in range(8)}
    errors = []

    def _worker(agent_id: str, actions: list) -> None:
        try:
            for _ in range(200):
                reg.upsert(agent_id, actions)
                got = reg.get(agent_id)
                assert got["actions"] == actions  # 完整清单（不撕裂）
        except Exception as e:  # noqa: BLE001 测试收集线程异常
            errors.append(e)

    threads = [threading.Thread(target=_worker, args=(aid, acts)) for aid, acts in payloads.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    for aid, acts in payloads.items():
        assert reg.get(aid)["actions"] == acts
