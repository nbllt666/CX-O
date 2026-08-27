"""server.core.admin.registry 测试：注册 / 心跳 / 过期 / 快照。

运行：python -m pytest tests/test_admin_registry.py -v
"""
import time
from unittest.mock import MagicMock

from server.core.admin.registry import InstanceRegistry


def test_register_and_snapshot():
    r = InstanceRegistry(register_interval_sec=15)
    r.register("a", "http://a:8000", role="active")
    r.register("b", "http://b:8000", role="standby")
    snap = r.snapshot()
    assert len(snap) == 2
    by_id = {s["instance_id"]: s for s in snap}
    assert by_id["a"]["endpoint"] == "http://a:8000"
    assert by_id["a"]["role"] == "active"
    assert by_id["b"]["role"] == "standby"
    assert "last_heartbeat" in by_id["a"]
    assert isinstance(by_id["a"]["last_heartbeat"], str)  # ISO8601 序列化


def test_heartbeat_updates_timestamp_and_unknown_returns_none():
    r = InstanceRegistry()
    assert r.heartbeat("missing") is None
    r.register("a", "e")
    t1 = r.snapshot()[0]["last_heartbeat"]
    time.sleep(0.01)
    r.heartbeat("a")
    t2 = r.snapshot()[0]["last_heartbeat"]
    assert t2 != t1


def test_expire_stale():
    r = InstanceRegistry()
    r.register("fresh", "e1")
    r.register("stale", "e2")
    # 手动把 stale 的 last_heartbeat 推到过去
    from datetime import datetime, timezone, timedelta
    with r._lock:
        r._instances["stale"]["last_heartbeat"] = (
            datetime.now(timezone.utc) - timedelta(seconds=100)
        )
    r.expire_stale(timeout_sec=30)
    ids = [s["instance_id"] for s in r.snapshot()]
    assert "fresh" in ids
    assert "stale" not in ids


def test_register_updates_existing():
    r = InstanceRegistry()
    r.register("a", "old", role="active")
    r.register("a", "new", role="superadmin")
    snap = r.snapshot()
    assert len(snap) == 1
    assert snap[0]["endpoint"] == "new"
    assert snap[0]["role"] == "superadmin"


def test_start_no_op_without_endpoint_and_shutdown():
    r = InstanceRegistry(register_interval_sec=1, admin_cfg=MagicMock(cx_a_endpoint=""))
    r.start()
    t = r._thread
    assert t is not None and t.is_alive()
    r.shutdown()
    assert not t.is_alive()


def test_proactive_register_skips_without_endpoint():
    import pytest
    import httpx
    r = InstanceRegistry(admin_cfg=MagicMock(cx_a_endpoint=""))
    # 未配置端点时 _active_register 不应发起网络请求，直接返回
    with pytest.MonkeyPatch.context() as mp:
        post = MagicMock()
        mp.setattr(httpx, "post", post)
        r._active_register()
        post.assert_not_called()


# ================================================================ M-E: 真实对外 endpoint
class TestSelfEndpoint:
    def test_self_endpoint_composes_lan_ip_and_port(self, monkeypatch):
        """M-E 定向: 上报 endpoint 为 LAN IP + 本服务端口，不再自指管理端 URL。"""
        import socket as socket_mod

        r = InstanceRegistry()

        class FakeSock:
            def connect(self, addr):
                pass

            def getsockname(self):
                return ("192.168.7.23", 54321)

            def close(self):
                pass

        monkeypatch.setattr(
            "server.core.admin.registry.socket.socket",
            lambda *a, **k: FakeSock(),
        )
        monkeypatch.setattr(
            InstanceRegistry, "_resolve_self_port", staticmethod(lambda: 8123)
        )
        assert r._self_endpoint() == "http://192.168.7.23:8123"
        assert socket_mod  # 引用防 lint

    def test_active_register_payload_endpoint_not_self_referential(self, monkeypatch):
        """M-E 定向: /api/admin/register 上报的 endpoint 字段为实例真实地址。"""
        import httpx

        r = InstanceRegistry(
            admin_cfg=MagicMock(cx_a_endpoint="http://cx-a-host:9000")
        )
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            return MagicMock(status_code=200)

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(r, "_self_endpoint", lambda: "http://10.1.2.3:8000")

        r._active_register()

        assert captured["url"].startswith("http://cx-a-host:9000")
        payload = captured["payload"]
        assert payload["endpoint"] == "http://10.1.2.3:8000"  # 不再等于管理端 URL
        assert payload["instance_id"] == r.instance_id

    def test_resolve_self_port_falls_back_env_then_default(self, monkeypatch):
        from server.core.admin.registry import InstanceRegistry as IR

        def boom():
            raise RuntimeError("settings unavailable")

        monkeypatch.setattr("server.config.get_settings", boom)
        monkeypatch.delenv("CXO_PORT", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        assert IR._resolve_self_port() == 8000  # 默认兜底

        monkeypatch.setenv("CXO_PORT", "9111")
        assert IR._resolve_self_port() == 9111