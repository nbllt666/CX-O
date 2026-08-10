"""
server/gateway/health.py 回归测试
服务健康检查器：注册/状态更新/健康判定
"""
import pytest

from server.gateway.health import HealthChecker


@pytest.fixture
def checker():
    return HealthChecker()


class TestRegisterService:
    def test_register_creates_default(self, checker):
        checker.register_service("asr")
        status = checker.get_status("asr")
        assert status["name"] == "asr"
        assert status["status"] == "unknown"


class TestUpdateStatus:
    def test_update_existing(self, checker):
        checker.register_service("tts")
        checker.update_status("tts", "healthy", latency_ms=12.3)
        status = checker.get_status("tts")
        assert status["status"] == "healthy"
        assert status["latency_ms"] == 12.3
        assert status["last_check"] > 0

    def test_update_unknown_is_noop(self, checker):
        # 未注册服务更新不报错
        checker.update_status("nonexistent", "healthy")


class TestGetStatus:
    def test_unknown_returns_none(self, checker):
        assert checker.get_status("missing") is None

    def test_get_all(self, checker):
        checker.register_service("a")
        checker.register_service("b")
        checker.update_status("a", "healthy")
        all_status = checker.get_all_status()
        assert set(all_status["services"].keys()) == {"a", "b"}
        assert "timestamp" in all_status


class TestHealthDetermination:
    def test_is_healthy(self, checker):
        checker.register_service("x")
        checker.update_status("x", "healthy")
        assert checker.is_healthy("x") is True

    def test_is_healthy_when_not_healthy(self, checker):
        checker.register_service("x")
        checker.update_status("x", "degraded")
        assert checker.is_healthy("x") is False

    def test_is_healthy_unknown_service(self, checker):
        assert checker.is_healthy("missing") is False

    def test_all_healthy_empty(self, checker):
        assert checker.all_healthy() is True

    def test_all_healthy_mixed(self, checker):
        checker.register_service("a")
        checker.register_service("b")
        checker.update_status("a", "healthy")
        checker.update_status("b", "down")
        assert checker.all_healthy() is False

    def test_all_healthy_true(self, checker):
        checker.register_service("a")
        checker.register_service("b")
        checker.update_status("a", "healthy")
        checker.update_status("b", "healthy")
        assert checker.all_healthy() is True