"""SentinelCluster 测试：disabled 拒绝 / 正常启动拓扑 / 事件 / shutdown。"""
from threading import Timer
from types import SimpleNamespace
import httpx
import pytest

from server.core.cluster.manager import SentinelCluster
from server.core.cluster._common import ClusterDisabledError


def make_witness(endpoint=""):
    return SimpleNamespace(endpoint=endpoint, secret="")


def make_config(enabled=True, peers=()):
    return SimpleNamespace(
        enabled=enabled,
        node_name="manager-node",
        cluster_secret="sekrit",
        peers=list(peers),
        role="standby",
        peer_heartbeat_interval_sec=1,
        peer_timeout_sec=5,
        miss_threshold=3,
        snapshot_interval_sec=60,
        sync_units=[],
        transport="https",
        bind="10.0.0.5",
        witness=make_witness(),
    )


def _ok_handler(request):
    return httpx.Response(200, json={"ok": True})


def _make_client():
    return httpx.AsyncClient(transport=httpx.MockTransport(_ok_handler))


@pytest.mark.asyncio
async def test_start_disabled_raises(tmp_path):
    cl = SentinelCluster(config=make_config(enabled=False))
    with pytest.raises(ClusterDisabledError):
        await cl.start()


@pytest.mark.asyncio
async def test_start_constructor_available_without_start():
    cl = SentinelCluster(config=make_config())
    # 启动前即可构造实例（异步 start 返回前尽量构造出实例）
    assert cl.identity is None


@pytest.mark.asyncio
async def test_start_then_topology_state_sync_status_shutdown(tmp_path, monkeypatch):
    client = _make_client()
    cl = SentinelCluster(config=make_config(enabled=True, peers=["p1:8443"]), client=client)

    # 未启动先调用 shutdown 也不应抛错
    await cl.shutdown()

    await cl.start()
    assert cl.identity is not None
    assert cl.identity.node_id.startswith("cxo-node-")
    assert cl.transport is not None
    assert cl.heartbeat is not None
    assert cl.replicator is not None

    topo = cl.topology()
    assert len(topo) == 2  # 自节点 + 1 peer
    assert topo[0]["node_id"] == cl.identity.node_id

    st = cl.state()
    assert st["node_id"] == cl.identity.node_id
    assert st["role"] == "standby"

    sst = cl.sync_status()
    assert "units" in sst

    # 事件订阅
    captured = []
    cl.set_event_callback(lambda ev: captured.append(ev))
    cl.emit_event("failover_completed", from_node="x")
    assert captured and captured[-1]["topic"] == "cluster.failover_completed"

    await cl.shutdown()
    await client.aclose()


@pytest.mark.asyncio
async def test_emit_event_prefixes_topic():
    client = _make_client()
    cl = SentinelCluster(config=make_config(), client=client)
    events = []
    cl.set_event_callback(lambda ev: events.append(ev))
    cl.emit_event("node_joined", node="x")
    assert events[0]["topic"] == "cluster.node_joined"
    await client.aclose()