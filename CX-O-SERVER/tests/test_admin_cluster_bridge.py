"""server.core.admin.cluster_bridge 测试：集群未启用返回 cluster_disabled；启用后委托+审计。

运行：python -m pytest tests/test_admin_cluster_bridge.py -v
"""
import pytest
from unittest.mock import MagicMock

from server.core.admin.cluster_bridge import ClusterAdminBridge, audit_now


class TestReadOnly:
    def test_disabled_returns_cluster_disabled(self):
        bridge = ClusterAdminBridge(cluster_manager=None)
        assert bridge.read_topology() == {"status": "cluster_disabled"}
        assert bridge.read_state() == {"status": "cluster_disabled"}
        assert bridge.read_sync_status() == {"status": "cluster_disabled"}

    def test_enabled_delegates(self):
        cm = MagicMock()
        cm.topology.return_value = {"nodes": ["a"]}
        cm.state.return_value = {"role": "active"}
        cm.sync_status.return_value = {"lag": 0}
        bridge = ClusterAdminBridge(cm)
        assert bridge.read_topology() == {"nodes": ["a"]}
        assert bridge.read_state() == {"role": "active"}
        assert bridge.read_sync_status() == {"lag": 0}


class TestWrite:
    def test_disabled_write_returns_cluster_disabled(self):
        bridge = ClusterAdminBridge(cluster_manager=None)
        assert bridge.trigger_failover({}) == {"status": "cluster_disabled"}
        assert bridge.set_role({}) == {"status": "cluster_disabled"}
        assert bridge.add_peer({}) == {"status": "cluster_disabled"}
        assert bridge.remove_peer({}) == {"status": "cluster_disabled"}

    def test_enabled_write_delegates_and_audits(self, monkeypatch, tmp_path):
        cm = MagicMock()
        cm.trigger_failover.return_value = {"ok": True}
        monkeypatch.setattr(
            "server.core.admin.cluster_bridge._ADMIN_AUDIT_PATH", tmp_path / "audit.jsonl"
        )
        bridge = ClusterAdminBridge(cm)
        res = bridge.trigger_failover({"from": "A", "to": "B"})
        cm.trigger_failover.assert_called_once_with({"from": "A", "to": "B"})
        assert res.get("status") == "ok"
        assert res["result"] == {"ok": True}
        # 审计应落盘
        content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "control.trigger_failover" in content


def test_audit_now_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.core.admin.cluster_bridge._ADMIN_AUDIT_PATH", tmp_path / "admin_audit.jsonl"
    )
    entry = audit_now("CX-A", "info", "control.set_role", "node-x", "设置角色", request_id="r1", detail={"role": "active"})
    assert entry["action"] == "control.set_role"
    assert entry["timestamp"]
    # 条目按 schema 含必填字段
    for k in ("id", "timestamp", "actor", "level", "action", "target", "summary"):
        assert k in entry
    content = (tmp_path / "admin_audit.jsonl").read_text(encoding="utf-8")
    assert "control.set_role" in content

    # 自动生成的 instance_id 默认在写操作时会以 CX-A 为 actor
    assert entry["actor"] == "CX-A"