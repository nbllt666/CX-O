"""局域网后端发现端点测试。

用 FastAPI TestClient 挂载 discovery 路由，monkeypatch 本地 IP 探测与健康检查，
验证子网扫描、可达后端收集与空结果兜底三条路径。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import discovery
from server.api.routers.admin import verify_admin_api_key


def _make_client() -> TestClient:
    """挂载 discovery 路由；C10 后端点已挂管理员鉴权，测试经依赖覆盖放行
    （本文件聚焦扫描逻辑，鉴权行为由 test_admin_router 覆盖）。"""
    app = FastAPI()
    app.include_router(discovery.router, prefix="/api")
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app)


def test_discovers_reachable_backends(monkeypatch):
    # 本机位于 192.168.1.x，扫描 /24 子网
    monkeypatch.setattr(discovery, "_get_local_ips", lambda: ["192.168.1.50"])
    # 仅 192.168.1.42 健康检查可达
    reachable = {"http://192.168.1.42:8100"}

    async def fake_probe(url: str, timeout: float) -> bool:
        assert timeout == 0.8
        return url in reachable

    monkeypatch.setattr(discovery, "_probe", fake_probe)

    client = _make_client()
    resp = client.get("/api/discovery/backends", params={"port": 8100})
    assert resp.status_code == 200
    data = resp.json()
    assert data["backends"] == [
        {"url": "http://192.168.1.42:8100", "host": "192.168.1.42", "port": 8100}
    ]


def test_no_local_subnet_returns_empty(monkeypatch):
    monkeypatch.setattr(discovery, "_get_local_ips", lambda: [])

    client = _make_client()
    resp = client.get("/api/discovery/backends")
    assert resp.status_code == 200
    assert resp.json() == {"backends": []}


def test_port_validation(monkeypatch):
    monkeypatch.setattr(discovery, "_get_local_ips", lambda: ["192.168.1.50"])

    client = _make_client()
    # 越界端口应返回 422
    resp = client.get("/api/discovery/backends", params={"port": 70000})
    assert resp.status_code == 422
    # C10: 非白名单端口（合法范围但不在 {8000, 8100, 8200}）应返回 400
    resp = client.get("/api/discovery/backends", params={"port": 9000})
    assert resp.status_code == 400


def test_all_hosts_scanned(monkeypatch):
    monkeypatch.setattr(discovery, "_get_local_ips", lambda: ["10.0.0.5"])
    scanned: list[str] = []

    async def fake_probe(url: str, timeout: float) -> bool:
        scanned.append(url)
        return False

    monkeypatch.setattr(discovery, "_probe", fake_probe)

    client = _make_client()
    resp = client.get("/api/discovery/backends", params={"port": 8100})
    assert resp.status_code == 200
    assert resp.json() == {"backends": []}
    # 应覆盖 10.0.0.1 ~ 10.0.0.254 全部 254 个地址
    assert len(scanned) == 254
    assert scanned[0] == "http://10.0.0.1:8100"
    assert scanned[-1] == "http://10.0.0.254:8100"
