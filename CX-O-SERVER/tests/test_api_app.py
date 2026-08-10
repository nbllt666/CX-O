"""
server/api/app.py (register_api_routes) 单元测试
路由注册 + /health 组件状态判定 + / 根路由
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.app import register_api_routes


def _build_app(services):
    """构造 FastAPI app，注册路由，注入假 ServiceState。"""
    app = FastAPI()
    register_api_routes(app)
    app.state.services = services
    return app


def _full_services():
    return SimpleNamespace(
        memory_manager=object(),
        context_manager=object(),
        acp_manager=object(),
        llm_client=object(),
        model_router=object(),
        asr_service=object(),
        tts_service=object(),
    )


def _empty_services():
    return SimpleNamespace(
        memory_manager=None,
        context_manager=None,
        acp_manager=None,
        llm_client=None,
        model_router=None,
        asr_service=None,
        tts_service=None,
    )


class TestHealthEndpoint:
    def test_healthy(self):
        client = TestClient(_build_app(_full_services()))
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["version"] == "1.0.0"
        assert all(body["components"].values())

    def test_degraded_all_missing(self):
        client = TestClient(_build_app(_empty_services()))
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert all(not v for v in body["components"].values())

    def test_degraded_partial(self):
        svc = _full_services()
        svc.llm_client = None
        svc.tts_service = None
        client = TestClient(_build_app(svc))
        body = client.get("/health").json()
        assert body["status"] == "degraded"
        assert body["components"]["llm_client"] is False
        assert body["components"]["tts_service"] is False
        assert body["components"]["memory_manager"] is True


class TestRootEndpoint:
    def test_root(self):
        client = TestClient(_build_app(_full_services()))
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["service"] == "CX-O-SERVER"
        assert body["version"] == "1.0.0"
        assert body["docs"] == "/docs"


class TestRouteRegistration:
    def test_routers_registered(self):
        client = TestClient(_build_app(_full_services()))
        routes = {r.path for r in client.app.routes}
        # 关键路由已挂载
        assert "/api/chat" in routes or any(x.startswith("/api/chat") for x in routes)
        assert "/api/config" in routes or any(x.startswith("/api/config") for x in routes)
        assert "/api/memory" in routes or any(x.startswith("/api/memory") for x in routes)
        assert "/api/tools" in routes or any(x.startswith("/api/tools") for x in routes)
        assert "/api/graph" in routes or any(x.startswith("/api/graph") for x in routes)
        assert "/api/cxfc" in routes or any(x.startswith("/api/cxfc") for x in routes)
        assert "/api/distillation" in routes or "/api/v1/distillation" in " ".join(routes) or any(x.startswith("/api/v1/distillation") for x in routes)
        assert "/health" in routes
        assert "/" in routes

    def test_exception_handlers_registered(self):
        from fastapi.exceptions import RequestValidationError
        from starlette.exceptions import HTTPException as StarletteHTTPException

        app = _build_app(_full_services())
        handlers = {k: v for k, v in app.exception_handlers.items()}
        # ServiceError / HTTPException / RequestValidationError / generic Exception
        assert any("ServiceError" in str(k) for k in handlers)
        assert StarletteHTTPException in handlers
        assert RequestValidationError in handlers
        assert Exception in handlers

    def test_performance_middleware_registered(self):
        from server.api.middleware.performance import PerformanceMiddleware

        app = _build_app(_full_services())
        mw_types = [getattr(m, "cls", None) for m in app.user_middleware]
        assert PerformanceMiddleware in mw_types