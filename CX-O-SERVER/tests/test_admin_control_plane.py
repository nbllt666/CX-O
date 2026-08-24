"""server.core.admin.control_plane 测试：各域分发 + 未知 target/action 抛异常。

运行：python -m pytest tests/test_admin_control_plane.py -v
"""
import pytest
from unittest.mock import MagicMock

from server.core.admin.control_plane import AdminControlPlane
from server.core.admin.auth import AdminUnknownActionError
from server.core.admin.cluster_bridge import ClusterAdminBridge


class Box:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _services(**overrides):
    svc = Box(tts=None, audio=None, live=None, tuner=None, acp_manager=None)
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def _plane(services=None, bridge=None):
    return AdminControlPlane(services or _services(), auth=MagicMock(), cluster_bridge=bridge)


class TestAutonomy:
    def test_enable_calls_manager(self):
        auto = MagicMock()
        auto.enable.return_value = {"enabled": True}
        plane = _plane(_services(autonomy_manager=auto))
        out = plane.dispatch("enable", "autonomy", "r")
        assert out["ok"] is True and out["target"] == "autonomy"
        auto.enable.assert_called_once()

    def test_emergency_stop(self):
        auto = MagicMock()
        auto.emergency_stop.return_value = {"stopped": True}
        plane = _plane(_services(autonomy_manager=auto))
        out = plane.dispatch("emergency_stop", "autonomy", "r")
        assert out["ok"] is True
        auto.emergency_stop.assert_called_once()


class TestVoice:
    def test_pause_via_tts(self):
        tts = MagicMock()
        tts.pause.return_value = {"paused": True}
        plane = _plane(_services(tts=tts))
        out = plane.dispatch("pause", "voice", "r")
        assert out["result"]["result"] == {"paused": True}

    def test_resume_falls_back_to_audio(self):
        audio = MagicMock()
        audio.resume.return_value = {"resumed": True}
        plane = _plane(_services(audio=audio))
        out = plane.dispatch("resume", "voice", "r")
        audio.resume.assert_called_once()


class TestLiveConfigTuner:
    def test_live_start(self):
        live = MagicMock()
        live.start.return_value = {"ok": True}
        plane = _plane(_services(live=live))
        out = plane.dispatch("start", "live", "r")
        live.start.assert_called_once()

    def test_config_reload(self):
        plane = _plane()
        out = plane.dispatch("reload", "config", "r")
        assert out["ok"] is True

    def test_tuner_start(self):
        tuner = MagicMock()
        im = MagicMock()
        tuner.start.return_value = im
        plane = _plane(_services(tuner=tuner))
        out = plane.dispatch("start", "tuner", "r")
        tuner.start.assert_called_once()


class TestAgent:
    def test_create(self):
        acp = MagicMock()
        acp.create_agent.return_value = {"id": "a1"}
        plane = _plane(_services(acp_manager=acp))
        out = plane.dispatch("create", "agent", "r", agent_id="a9")
        assert out["ok"] is True

    def test_delete_candidate(self):
        acp = MagicMock()
        acp.delete_agent.return_value = {"deleted": True}
        plane = _plane(_services(acp_manager=acp))
        out = plane.dispatch("delete", "agent", "r")
        acp.delete_agent.assert_called_once()


class TestInstance:
    def test_restart_triggered(self):
        plane = _plane()
        out = plane.dispatch("restart", "instance", "r")
        assert out["result"]["result"] == "triggered"

    def test_shutdown_triggered(self):
        plane = _plane()
        out = plane.dispatch("shutdown", "instance", "r")
        assert out["result"]["result"] == "triggered"


class TestCluster:
    def test_cluster_read_delegates(self):
        cm = MagicMock()
        cm.state.return_value = {"node": "A"}
        bridge = ClusterAdminBridge(cm, None)
        plane = _plane(bridge=bridge)
        out = plane.dispatch("state", "cluster", "r")
        assert out["result"]["result"] == {"node": "A"}

    def test_cluster_write_delegates_audits(self):
        cm = MagicMock()
        cm.trigger_failover.return_value = {"ok": True}
        bridge = ClusterAdminBridge(cm, None)
        plane = _plane(bridge=bridge)
        out = plane.dispatch("trigger_failover", "cluster", "r", params={"from": "A", "to": "B"})
        cm.trigger_failover.assert_called_once()
        assert out["ok"] is True


class TestUnknown:
    def test_unknown_target(self):
        with pytest.raises(AdminUnknownActionError):
            _plane().dispatch("enable", "bogus", "r")

    def test_unknown_action(self):
        with pytest.raises(AdminUnknownActionError):
            _plane().dispatch("fly", "autonomy", "r")

    def test_unknown_cluster_action(self):
        bridge = ClusterAdminBridge(MagicMock(), None)
        with pytest.raises(AdminUnknownActionError):
            _plane(bridge=bridge).dispatch("explode", "cluster", "r")