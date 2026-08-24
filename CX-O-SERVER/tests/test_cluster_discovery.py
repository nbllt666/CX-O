"""PeerDiscovery 测试：种子列表发现 + 握手密钥拒绝（ClusterAuthError）。"""
from types import SimpleNamespace
import httpx
import pytest

from server.core.cluster.discovery import PeerDiscovery
from server.core.cluster._common import compute_hmac


def make_config(**kw):
    cfg = SimpleNamespace(
        peers=["p1:8443", "p2:8443"],
        cluster_secret="sekrit",
        transport="https",
        role="standby",
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _peer_handler(secret, peer_id="peer-001"):
    """模拟对端：校验我方 secret_hmac；回传 peer 自身 secret_hmac 证明。"""
    def handler(request):
        import json as _j
        body = _j.loads(request.content)
        node_id = body["node_id"]
        provided = body["payload"]["secret_hmac"]
        sender_hmac = compute_hmac(secret, node_id, "handshake", node_id)
        if provided != sender_hmac:
            return httpx.Response(403, json={"error_code": "CLUSTER_AUTH_FAILED", "message": "bad secret"})
        my_hmac = compute_hmac(secret, peer_id, "handshake", peer_id)
        return httpx.Response(200, json={"node_id": peer_id, "payload": {"secret_hmac": my_hmac}})
    return handler


@pytest.mark.asyncio
async def test_discover_returns_seed_candidates():
    d = PeerDiscovery(config=make_config(), node_id="me")
    cands = d.discover()
    assert cands == [{"endpoint": "p1:8443", "node_id": None}, {"endpoint": "p2:8443", "node_id": None}]


@pytest.mark.asyncio
async def test_handshake_success_with_correct_secret():
    cfg = make_config()
    transport = httpx.AsyncClient(transport=httpx.MockTransport(_peer_handler(cfg.cluster_secret)))
    d = PeerDiscovery(config=cfg, node_id="me", secret=cfg.cluster_secret, client=transport)
    result = await d.handshake("p1:8443")
    assert result["node_id"] == "peer-001"
    assert result["endpoint"] == "p1:8443"
    await transport.aclose()


@pytest.mark.asyncio
async def test_handshake_rejects_wrong_secret():
    cfg = make_config()
    transport = httpx.AsyncClient(transport=httpx.MockTransport(_peer_handler(cfg.cluster_secret)))
    d = PeerDiscovery(config=cfg, node_id="me", secret="WRONG", client=transport)
    with pytest.raises(Exception) as exc:
        await d.handshake("p1:8443")
    from server.core.cluster._common import CLUSTER_AUTH_FAILED, ClusterError
    assert isinstance(exc.value, ClusterError)
    assert exc.value.error_code == CLUSTER_AUTH_FAILED
    await transport.aclose()


@pytest.mark.asyncio
async def test_handshake_rejects_peer_wrong_secret_proof():
    cfg = make_config()
    # 对端用不同 secret 计算自己的证明 → 本端校验失败 → ClusterAuthError
    transport = httpx.AsyncClient(transport=httpx.MockTransport(_peer_handler("other-secret")))
    d = PeerDiscovery(config=cfg, node_id="me", secret=cfg.cluster_secret, client=transport)
    with pytest.raises(Exception) as exc:
        await d.handshake("p1:8443")
    from server.core.cluster._common import CLUSTER_AUTH_FAILED, ClusterError
    assert isinstance(exc.value, ClusterError)
    assert exc.value.error_code == CLUSTER_AUTH_FAILED
    await transport.aclose()