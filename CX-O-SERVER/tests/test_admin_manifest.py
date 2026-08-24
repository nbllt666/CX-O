"""server.core.admin.manifest 测试：动态能力探测 + cluster 未启用降级。

运行：python -m pytest tests/test_admin_manifest.py -v
"""
from unittest.mock import MagicMock

from server.core.admin.manifest import AdminManifest


class Box:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _services(**overrides):
    svc = Box(
        acp_manager=MagicMock(),  # 有 acp_manager 但无连通方法 -> agents 降级空
        cxfc_manager=None,
        model_router=None,
        autonomy_manager=None,
        tts=None,
        audio=None,
        live=None,
        multimodal=None,
    )
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def test_build_defaults_full_schema():
    svc = _services()
    man = AdminManifest(svc, Box(node_name=""))
    out = man.build()
    assert out["version"] == "1.0.0"
    assert out["node_name"] == "cx-o-node"
    assert out["cluster"] == {"enabled": False}
    assert out["endpoints"]["ws"] == "/ws"
    assert out["control_actions"]
    # 无自治/tuner/多模态时对应能力为 False
    assert "autonomy" in out["capabilities"]
    assert "tuner" in out["capabilities"]
    assert out["capabilities"]["tuner"] is False


def test_cluster_state_passthrough():
    man = AdminManifest(_services(), Box(node_name="n1"))
    out = man.build({"enabled": True, "node_id": "n-1", "role": "active"})
    assert out["cluster"]["enabled"] is True
    assert out["cluster"]["node_id"] == "n-1"


def test_capabilities_dynamic():
    tts = MagicMock()
    ax = MagicMock()
    live = MagicMock()
    multi = MagicMock()
    svc = _services(tts=tts, autonomy_manager=ax, live=live, multimodal=multi)
    man = AdminManifest(svc, Box(node_name="x"))
    caps = man.detect_capabilities()
    assert caps["realtime_voice"] is True
    assert caps["autonomy"] is True
    assert caps["live_stream"] is True
    assert caps["vision"] is True
    assert caps["computer_control"] is False


def test_models_from_model_router():
    mr = Box(get_main=lambda: "gpt-main", get_memory=lambda: "embed", get_summary=lambda: "gpt-sum")
    man = AdminManifest(_services(model_router=mr), Box(node_name="x"))
    models = man.detect_models()
    assert models.get("main") == "gpt-main"
    assert models.get("memory") == "embed"
    assert models.get("summary") == "gpt-sum"


def test_models_missing_slot_gives_empty():
    mr = Box(get_main=lambda: "m")
    man = AdminManifest(_services(model_router=mr), Box(node_name="x"))
    models = man.detect_models()
    assert models == {"main": "m"}


def test_plugins_from_cxfc():
    cxfc = MagicMock()
    p = MagicMock(plugin_id="skill-a")
    cxfc.get_plugins.return_value = [p, {"plugin_id": "skill-b"}]
    man = AdminManifest(_services(cxfc_manager=cxfc), Box(node_name="x"))
    assert sorted(man.detect_plugins()) == ["skill-a", "skill-b"]


def test_agents_from_acp_dict():
    acp = MagicMock()
    a1 = MagicMock(agent_id="ag-1")
    a2 = MagicMock(agent_id="ag-2")
    acp.agents = {"k1": a1, "k2": a2}
    man = AdminManifest(_services(acp_manager=acp), Box(node_name="x"))
    assert sorted(man.detect_agents()) == ["ag-1", "ag-2"]


def test_agents_via_list_when_no_dict():
    acp = MagicMock()
    acp.agents = {}
    acp.list_agents.return_value = [{"agent_id": "lh-9"}, {"id": "lh-10"}]
    man = AdminManifest(_services(acp_manager=acp), Box(node_name="x"))
    assert sorted(man.detect_agents()) == ["lh-10", "lh-9"]


def test_instance_id_reuse_cfg_or_services():
    svc = _services(instance_id="srv-1")
    man = AdminManifest(svc, Box(node_name="n"))
    assert man.build()["instance_id"] == "srv-1"

    man2 = AdminManifest(_services(), Box(node_name="n", instance_id="cfg-i"))
    assert man2.build()["instance_id"] == "cfg-i"