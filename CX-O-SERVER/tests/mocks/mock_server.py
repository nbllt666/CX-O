"""FastAPI TestClient 封装（CX-O-SERVER 测试基础设施 Phase 1）。

提供三层封装，供后续批次补测按需选用：
1. ``create_test_client(app)`` —— 通用：将任意 FastAPI app 包装为 TestClient
2. ``create_mock_app()`` —— 轻量：构建仅含 health/root 的最小 FastAPI app，
   不拉起完整服务栈，用于测试 client 封装本身或做轻量端到端验证
3. ``get_real_app_client()`` —— 重型：懒加载 ``server.main.create_app`` 并包装，
   会触发完整 lifespan（含数据库/服务初始化），按需使用

注意：
- TestClient 基于 ``fastapi.testclient.TestClient``（依赖 httpx）
- 真实 app 客户端构建可能因外部依赖缺失而失败，调用方需自行处理异常
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient


def create_test_client(app: FastAPI, **kwargs: Any) -> TestClient:
    """将任意 FastAPI app 包装为 ``TestClient``。

    Args:
        app: 已构造的 FastAPI 实例
        **kwargs: 透传给 TestClient 的参数（如 base_url, headers）

    Returns:
        可用于发请求的 TestClient 实例
    """
    return TestClient(app, **kwargs)


def create_mock_app() -> FastAPI:
    """构建最小 FastAPI app（含 health / root 端点）。

    不导入 server 业务路由，避免拉起完整服务栈。适用于：
    - 验证 TestClient 封装行为
    - 轻量端到端冒烟测试
    - 作为 router 集成测试的宿主 app

    Returns:
        最小 FastAPI 实例
    """
    app = FastAPI(title="CX-O-SERVER-Mock", version="test")

    @app.get("/health")
    async def health_check() -> dict:
        return {"status": "healthy", "version": "test"}

    @app.get("/")
    async def root() -> dict:
        return {"service": "CX-O-SERVER-Mock", "version": "test"}

    @app.get("/api/ping")
    async def ping() -> dict:
        return {"message": "pong"}

    return app


class MockServerClient:
    """TestClient 的轻量封装，提供常用请求便捷方法。

    默认绑定 ``create_mock_app()`` 产出的最小 app，
    也可通过 ``app`` 参数绑定任意 FastAPI app。
    """

    def __init__(self, app: Optional[FastAPI] = None, **kwargs: Any) -> None:
        self.app = app if app is not None else create_mock_app()
        self.client = create_test_client(self.app, **kwargs)

    def health(self) -> dict:
        """GET /health"""
        resp = self.client.get("/health")
        resp.raise_for_status()
        return resp.json()

    def root(self) -> dict:
        """GET /"""
        resp = self.client.get("/")
        resp.raise_for_status()
        return resp.json()

    def ping(self) -> dict:
        """GET /api/ping"""
        resp = self.client.get("/api/ping")
        resp.raise_for_status()
        return resp.json()

    def get_json(self, path: str, **kwargs: Any) -> dict:
        """通用 GET，返回 JSON。"""
        resp = self.client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post_json(self, path: str, payload: Optional[dict] = None, **kwargs: Any) -> dict:
        """通用 POST，返回 JSON。"""
        resp = self.client.post(path, json=payload, **kwargs)
        resp.raise_for_status()
        return resp.json()


def get_real_app_client() -> TestClient:
    """懒加载真实 server app 并包装为 TestClient。

    会触发 ``server.main.create_app()`` 的完整 lifespan（含数据库、服务初始化）。
    若外部依赖缺失或初始化失败，抛出 RuntimeError 并附带原因。

    Returns:
        绑定真实 app 的 TestClient

    Raises:
        RuntimeError: 真实 app 构建失败
    """
    try:
        from server.main import create_app
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法导入 server.main.create_app: {exc}") from exc

    try:
        app = create_app()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"构建真实 app 失败（可能缺少外部依赖）: {exc}") from exc

    return create_test_client(app)
