"""NodeIdentity 测试：首次生成持久化 + 幂等（再次加载不变）。"""
from types import SimpleNamespace
import json
import sys
from pathlib import Path

from server.core.cluster.identity import NodeIdentity


def make_config(**kw):
    cfg = SimpleNamespace(node_name="node-a", bind="10.0.0.5", transport="https")
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_create_then_reload_idempotent(tmp_path):
    cfg = make_config(node_name="node-a", bind="10.0.0.5", transport="https")
    ident = NodeIdentity()
    first = ident.load_or_create(tmp_path, cfg)

    assert isinstance(first, str)
    assert first.startswith("cxo-node-")

    # 再次加载，node_id 不变（幂等）
    ident2 = NodeIdentity()
    second = ident2.load_or_create(tmp_path, cfg)
    assert second == first

    # 属性已填充
    assert ident2.node_name == "node-a"


def test_identity_file_persisted_with_required_fields(tmp_path):
    cfg = make_config(node_name="node-a", transport="http", bind="10.0.0.5")
    NodeIdentity().load_or_create(tmp_path, cfg)

    doc_path = tmp_path / "node_identity.json"
    assert doc_path.exists()
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    # 契约必填字段
    assert set(doc) >= {"node_id", "node_name", "endpoint", "created_at"}
    assert doc["node_name"] == "node-a"
    assert doc["node_id"].startswith("cxo-node-")
    assert doc["endpoint"].startswith("http://")


def test_reload_file_returns_same_id_and_keeps_name(tmp_path):
    cfg = make_config(node_name="node-a", transport="https", bind="10.0.0.5")
    first = NodeIdentity().load_or_create(tmp_path, cfg)

    doc = json.loads((tmp_path / "node_identity.json").read_text(encoding="utf-8"))
    doc["node_name"] = "node-b"
    (tmp_path / "node_identity.json").write_text(json.dumps(doc), encoding="utf-8")

    ident = NodeIdentity()
    reloaded = ident.load_or_create(tmp_path, cfg)
    assert reloaded == first  # node_id 保持不变
    assert ident.node_name == "node-b"  # 名称沿用文件值