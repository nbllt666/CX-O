"""集群接收端闭环测试（批次F）。

覆盖：
- 五种 op 接收正反路径（含 401/403/404/disabled）；
- gossip 请求-响应真实意见计票（sender 侧统计对端意见，网络失败视为弃权）；
- sync_event 幂等去重（ack 序号 / applied 标记）；
- flush_pending 三态处理（永久失败移除 / 网络失败保留 / 读改写窗口防丢追加）；
- replicator 边界治理（outbox 上限丢弃最旧 / applied_seqs 容量压实）。
"""
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import cluster as cluster_router
from server.core.cluster.manager import SentinelCluster
from server.core.cluster.replicator import StateReplicator
from server.core.cluster.transport import ClusterTransport

SECRET = "sekrit"


# ---------------- 公共桩 ----------------

def make_config(**kw):
    cfg = SimpleNamespace(
        enabled=True,
        node_name="receive-node",
        cluster_secret=SECRET,
        peers=[],
        role="standby",
        peer_heartbeat_interval_sec=5,
        peer_timeout_sec=5,
        miss_threshold=3,
        snapshot_interval_sec=60,
        sync_units=["memory"],
        transport="https",
        bind="10.0.0.5",
        witness=SimpleNamespace(endpoint="", secret=""),
        pending_flush_interval_sec=30,
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


@pytest.fixture(autouse=True)
def _restore_globals(monkeypatch):
    """每条用例后恢复路由单例与 ref_audio emit hook，避免跨用例状态污染。"""
    yield
    monkeypatch.setattr(cluster_router, "_cluster_manager", None)
    try:
        from server import ref_audio_store

        ref_audio_store.set_emit_hook(None)
    except Exception:  # noqa: BLE001
        pass


def assemble(tmp_path) -> SentinelCluster:
    """组装一个已 _wire 但未启动后台循环的完整运行时（走生产装配路径）。"""
    cfg = make_config()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))
    cl = SentinelCluster(config=cfg, client=client)
    cl._wire(cfg)
    return cl


def make_app(cl) -> TestClient:
    app = FastAPI()
    app.include_router(cluster_router.peer_router)
    return TestClient(app)


def inject(cl, monkeypatch):
    monkeypatch.setattr(cluster_router, "_cluster_manager", cl)


def peer_body(op, node_id="peer-a", payload=None, seq=0, mode="ok"):
    """按发送侧同款约定构造 op 请求体。mode: ok | missing | bad

    handshake 额外携带内层密钥证明（payload.secret_hmac），与 PeerDiscovery 发送侧一致。
    """
    rid = uuid.uuid4().hex
    from server.core.cluster._common import compute_hmac

    payload = dict(payload or {})
    if op == "handshake" and mode == "ok":
        payload["secret_hmac"] = compute_hmac(SECRET, node_id, "handshake", node_id)
    body = {
        "op": op,
        "node_id": node_id,
        "request_id": rid,
        "seq": seq,
        "epoch": 0,
        "payload": payload,
        "secret_hmac": compute_hmac(SECRET, node_id, rid, str(seq), op),
    }
    if mode == "missing":
        body.pop("secret_hmac")
    elif mode == "bad":
        body["secret_hmac"] = "deadbeef"
    return body


# ---------------- 接收路径（正反） ----------------

def test_handshake_registers_peer_and_replies_identity(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)

    resp = tc.post("/cluster/handshake", json=peer_body(
        "handshake",
        payload={"node_name": "p-a", "role": "standby", "endpoint": "pa:8443"},
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["node_id"] == cl.identity.node_id  # 回应己方身份
    # 对端证明校验逻辑（与 discovery.handshake 同款）：自身证明可用本地密钥复算
    from server.core.cluster._common import compute_hmac

    expect_proof = compute_hmac(SECRET, data["node_id"], "handshake", data["node_id"])
    assert data["payload"]["secret_hmac"] == expect_proof
    # 对端已登记
    entry = cl._peers_registry.get("peer-a")
    assert entry and entry["endpoint"] == "pa:8443"


def test_missing_hmac_returns_401(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)

    resp = tc.post("/cluster/heartbeat", json=peer_body("heartbeat", mode="missing"))
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False and body["error_code"] == "CLUSTER_AUTH_FAILED"


def test_bad_secret_returns_403(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)

    resp = tc.post("/cluster/gossip", json=peer_body(
        "gossip", payload={"ask": "dead", "about": "x"}, mode="bad"))
    assert resp.status_code == 403
    body = resp.json()
    assert body["ok"] is False and body["error_code"] == "CLUSTER_AUTH_FAILED"


def test_unknown_op_returns_404(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)

    resp = tc.post("/cluster/bogus", json=peer_body("bogus"))
    assert resp.status_code == 404
    assert resp.json()["ok"] is False


def test_disabled_cluster_returns_503(tmp_path, monkeypatch):
    # 未注入任何运行时：cluster.enabled=false 的零摩擦口径
    monkeypatch.setattr(cluster_router, "_cluster_manager", None)
    app = FastAPI()
    app.include_router(cluster_router.peer_router)
    tc = TestClient(app)

    resp = tc.post("/cluster/heartbeat", json={"op": "heartbeat", "node_id": "x"})
    assert resp.status_code == 503
    assert resp.json()["error_code"] == "CLUSTER_DISABLED"


def test_inbound_heartbeat_resets_miss_and_marks_healthy(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)

    hb = cl.heartbeat
    hb._miss["peer-b"] = 2  # 预置 miss，等待入站心跳复位
    resp = tc.post("/cluster/heartbeat", json=peer_body(
        "heartbeat", node_id="peer-b",
        payload={"role": "standby", "epoch": 0, "last_sync_seq": 3, "state_version": 1}))
    assert resp.status_code == 200 and resp.json()["ok"] is True
    st = hb.node_status()["peer-b"]
    assert st["state"] == "healthy"
    assert "peer-b" not in hb._miss  # 复用 miss 追踪数据结构


def test_gossip_answers_real_local_opinion(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)
    hb = cl.heartbeat

    # 已确认死亡集命中
    hb._dead.add("ghost")
    # 连续 miss 达阈值 → 本地判死
    hb._miss["limbo"] = hb._miss_threshold
    # 别名解析：registry 登记 node_id=nid-x 对应 endpoint ep-x:8443，
    # 监视 key 是 node_id 时，按 endpoint 问询也应识别为死亡
    cl.register_peer("nid-x", {"endpoint": "ep-x:8443"})
    hb._miss["nid-x"] = 99

    def ask(about):
        r = tc.post("/cluster/gossip", json=peer_body("gossip", payload={"ask": "dead", "about": about}))
        assert r.status_code == 200
        return r.json()

    assert ask("ghost")["dead"] is True
    assert ask("limbo")["dead"] is True
    assert ask("ep-x:8443")["dead"] is True       # endpoint 别名跨标识解析
    assert ask("stranger")["dead"] is False       # 本地无观测 → 如实回答未死
    # 发送方只发 {"ask":"dead"} 协议；其他 ask 类型宽松应答未死
    r = tc.post("/cluster/gossip", json=peer_body("gossip", payload={"ask": "other", "about": "ghost"}))
    assert r.status_code == 200 and r.json()["ok"] is True


@pytest.mark.asyncio
async def test_sync_event_applies_then_dedupes(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)

    # E13 后仅 ref_audio 有应用端：改用 ref_audio 绑定事件（落盘走临时资产目录），
    # 保持原意图：应用→ack / 同 seq 重放幂等 ack / 新 seq 正常推进。
    from server import ref_audio_store

    ref_audio_store._set_assets_dir(tmp_path)
    try:
        payload1 = {"unit": "ref_audio", "op": "binding_set", "seq": 11,
                    "data": {"agent_id": "agent-x", "asset_id": "a-1", "tts_voice": "v1"}}
        r1 = tc.post("/cluster/sync_event", json=peer_body("sync_event", node_id="peer-c", seq=11, payload=payload1))
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1 == {"ok": True, "acked_seq": 11, "applied": True}
        assert cl.replicator.last_applied()["ref_audio"] == 11

        # 幂等：同 seq 重放 ack 但不再应用
        r2 = tc.post("/cluster/sync_event", json=peer_body("sync_event", node_id="peer-c", seq=11, payload=payload1))
        d2 = r2.json()
        assert d2["ok"] is True and d2["acked_seq"] == 11 and d2["applied"] is False

        # 新 seq 正常推进
        payload3 = {"unit": "ref_audio", "op": "binding_set", "seq": 12,
                    "data": {"agent_id": "agent-x", "asset_id": "a-2", "tts_voice": "v2"}}
        r3 = tc.post("/cluster/sync_event", json=peer_body("sync_event", node_id="peer-c", seq=12, payload=payload3))
        assert r3.json()["applied"] is True
        assert cl.replicator.last_applied()["ref_audio"] == 12
    finally:
        ref_audio_store._set_assets_dir(None)


def test_leave_marks_left_clears_suspect_and_emits_event(tmp_path, monkeypatch):
    cl = assemble(tmp_path)
    inject(cl, monkeypatch)
    tc = make_app(cl)
    hb = cl.heartbeat

    hb.mark_suspect("peer-d")
    hb._miss["peer-d"] = 7
    events = []
    cl.set_event_callback(events.append)

    resp = tc.post("/cluster/leave", json=peer_body("leave", node_id="peer-d", payload={"node_id": "peer-d"}))
    assert resp.status_code == 200 and resp.json()["left"] == "peer-d"
    assert hb.node_status()["peer-d"]["state"] == "left"
    assert not hb.is_suspect("peer-d")           # 嫌疑清理
    assert "peer-d" not in hb._miss
    assert cl._peers_registry["peer-d"]["left"] is True
    topics = [e["topic"] for e in events]
    assert "cluster.node_left" in topics          # 相应清理事件广播


# ---------------- gossip sender 侧真实意见计票 ----------------

def _hb_with_gossip_replies(dead_reply, raise_error=False):
    cfg = make_config(peers=["p1"])
    handler_state = {"n": 0}

    def handler(request):
        handler_state["n"] += 1
        if raise_error:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True, "dead": dead_reply})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tr = ClusterTransport(config=cfg, secret=SECRET, node_id="me", client=client)
    from server.core.cluster.heartbeat import PeerHeartbeat

    hb = PeerHeartbeat(config=cfg, transport=tr, node_id="me")
    return hb


@pytest.mark.asyncio
async def test_confirm_dead_counts_real_opinions_not_reachability():
    """可达但明确回答"没死"不算赞成票——替换旧"可达即赞成"语义。"""
    hb = _hb_with_gossip_replies(dead_reply=False)
    assert await hb.confirm_dead("victimX") is False
    report = hb.last_confirm_report
    assert report["abstained"] == []            # 对端可达且有应答：非弃权
    assert report["agree_peers"] == 0           # 明确反对：不计入赞成

    hb2 = _hb_with_gossip_replies(dead_reply=True)
    assert await hb2.confirm_dead("victimY") is True  # 单 peer 真实赞成 + 自身 = 多数派(2/2)


@pytest.mark.asyncio
async def test_network_failure_abstains_reported():
    hb = _hb_with_gossip_replies(dead_reply=False, raise_error=True)
    assert await hb.confirm_dead("victimZ") is False
    report = hb.last_confirm_report
    assert report["abstained"] == ["p1"]        # 网络失败 peer 弃权并在报告中说明
    assert report["agree_peers"] == 0
    assert report["agreements"] == 1            # 仅剩自身一票 < 多数派 2


# ---------------- flush_pending 三态 ----------------

def _outbox_transport(tmp_path):
    cfg = make_config()
    t = ClusterTransport(config=cfg, secret=SECRET, node_id="me", pending_dir=tmp_path)
    rec = {
        "peer_endpoint": "pd:8000", "op": "sync_event", "node_id": "me",
        "request_id": uuid.uuid4().hex, "seq": 1, "epoch": 0, "payload": {"n": 1},
    }
    with open(t._pending_dir / "outbox.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return t


@pytest.mark.asyncio
async def test_flush_permanent_failure_drops_entry(tmp_path):
    """4xx 永久失败：条目移除且丢弃计数累计。"""
    t = _outbox_transport(tmp_path)

    async def _gone(url, body):
        return httpx.Response(410, json={"error_code": "CLUSTER_SERVICE_ERROR"})

    t._post = _gone
    await t.flush_pending()
    assert t.pending_count() == 0               # 永久失败：条目移除
    assert t.dropped_count == 1                 # 丢弃计数累计


@pytest.mark.asyncio
async def test_flush_network_failure_keeps_entry(tmp_path):
    t = _outbox_transport(tmp_path)

    async def _down(url, body):
        raise httpx.ConnectError("network down")

    t._post = _down
    await t.flush_pending()
    assert t.pending_count() == 1               # 网络类失败：条目保留
    rows = open(t._pending_dir / "outbox.jsonl", encoding="utf-8").read().splitlines()
    rec = json.loads(rows[0])
    assert rec["peer_endpoint"] == "pd:8000" and rec["payload"] == {"n": 1}


@pytest.mark.asyncio
async def test_flush_preserves_entries_appended_during_window(tmp_path):
    """读改写窗口保护：flush 进行中并发追加的新条目不得被原子改写吞掉。"""
    t = _outbox_transport(tmp_path)
    outbox = t._pending_dir / "outbox.jsonl"

    async def _append_then_fail(url, body):
        with open(outbox, "a", encoding="utf-8") as fh:
            late = {"peer_endpoint": "pe:9000", "op": "gossip", "node_id": "me",
                    "request_id": uuid.uuid4().hex, "seq": 2, "epoch": 0, "payload": {"late": True}}
            fh.write(json.dumps(late, ensure_ascii=False) + "\n")
        return httpx.Response(500, json={"error_code": "CLUSTER_SERVICE_ERROR"})  # 原条目瞬时失败保留

    t._post = _append_then_fail
    await t.flush_pending()
    rows = [json.loads(x) for x in open(outbox, encoding="utf-8").read().splitlines() if x.strip()]
    endpoints = {r["peer_endpoint"] for r in rows}
    assert endpoints == {"pd:8000", "pe:9000"}  # 原条目 + 窗口期新追加均保留


# ---------------- replicator 边界治理 ----------------

@pytest.mark.asyncio
async def test_outbox_hard_cap_drops_oldest(tmp_path, monkeypatch):
    from server.core.cluster import replicator as rep_mod

    monkeypatch.setattr(rep_mod, "OUTBOX_MAX", 3)
    rep = StateReplicator(config=make_config(), node_id="me", units={"memory": "incremental"})
    for i in range(5):
        rep.emit("memory", "upsert", {"i": i})
    assert rep.outbox_len == 3                  # 硬上限生效
    remaining = [e["payload"]["i"] for e in rep._outbox]
    assert remaining == [2, 3, 4]               # 最旧的先被丢
    assert rep.sync_status()["_dropped_unsent"] == 2  # 丢弃计数累计


@pytest.mark.asyncio
async def test_applied_seqs_capacity_compaction(tmp_path, monkeypatch):
    from server.core.cluster import replicator as rep_mod

    monkeypatch.setattr(rep_mod, "APPLIED_SEQS_MAX", 4)
    rep = StateReplicator(config=make_config(), node_id="me", units={"ref_audio": "incremental"})
    monkeypatch.setattr(rep, "_apply_ref_audio", lambda op, payload: True)  # 隔离应用层（E13）
    for s in range(1, 7):                       # 应用 6 个 distinct seq（> 上限 4 触发压实）
        await rep.apply_event({"unit": "ref_audio", "seq": s, "op": "x", "payload": {}})
    rep._compact_applied_seqs()                 # 周期压实入口（生产由 _loop 调度）
    seqs = rep._applied_seqs["ref_audio"]
    assert len(seqs) <= 4                       # 容量有界
    assert seqs == {5, 6}                       # 保留最新一半
    # 最新 seq 重放仍幂等跳过；被压实的极旧 seq 会重新应用（容量窗口取舍，各单元应用层幂等兜底）
    assert await rep.apply_event({"unit": "ref_audio", "seq": 6, "op": "x", "payload": {}}) is False
    assert await rep.apply_event({"unit": "ref_audio", "seq": 1, "op": "x", "payload": {}}) is True


@pytest.mark.asyncio
async def test_snapshot_failure_logs_warning(tmp_path, monkeypatch, caplog):
    import logging

    rep = StateReplicator(config=make_config(), node_id="me", units={"memory": "incremental"})
    rep.register_backup_provider("memory", lambda u: (_ for _ in ()).throw(RuntimeError("boom")))
    with caplog.at_level(logging.WARNING, logger="server.core.cluster.replicator"):
        await rep._try_snapshot()
    assert any("快照" in rec.message and "memory" in rec.message for rec in caplog.records)
