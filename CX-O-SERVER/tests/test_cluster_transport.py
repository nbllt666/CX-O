"""ClusterTransport 测试：校验头 / 防重放 / 失败入待发队列 / flush 重试。"""
from types import SimpleNamespace
import json

import httpx
import pytest

from server.core.cluster.transport import ClusterTransport
from server.core.cluster._common import ClusterReplayError
from server.core.cluster._common import compute_hmac


def make_config(**kw):
    cfg = SimpleNamespace(
        cluster_secret="sekrit",
        transport="https",
        peer_timeout_sec=5,
        peers=["p1:8443"],
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _capture_handler(log, status=200):
    def handler(request):
        body = json.loads(request.content)
        log.append(body)
        if status >= 400:
            return httpx.Response(status, json={"error_code": "CLUSTER_SERVICE_ERROR"})
        return httpx.Response(200, json={"ok": True})
    return handler


@pytest.mark.asyncio
async def test_send_ok_with_headers_and_hmac(tmp_path):
    seen = []
    cfg = make_config()
    transport = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler(seen, 200)))
    t = ClusterTransport(config=cfg, secret=cfg.cluster_secret, node_id="me", pending_dir=tmp_path, client=transport)

    ok = await t.send("p1:8443", "heartbeat", "me", "req-1", seq=3, epoch=0, payload={"x": 1})
    assert ok is True

    body = seen[0]
    # 校验请求头字段（对齐 cluster_transport.schema.json）
    assert body["op"] == "heartbeat"
    assert body["node_id"] == "me"
    assert body["request_id"] == "req-1"
    assert body["seq"] == 3
    assert body["epoch"] == 0
    assert body["payload"] == {"x": 1}
    assert body["secret_hmac"] == compute_hmac(cfg.cluster_secret, "me", "req-1", "3", "heartbeat")
    await transport.aclose()


@pytest.mark.asyncio
async def test_send_same_request_id_rejected(tmp_path):
    seen = []
    cfg = make_config()
    transport = httpx.AsyncClient(transport=httpx.MockTransport(_capture_handler(seen, 200)))
    t = ClusterTransport(config=cfg, secret=cfg.cluster_secret, node_id="me", pending_dir=tmp_path, client=transport)

    ok1 = await t.send("p1:8443", "heartbeat", "me", "dup", seq=0)
    with pytest.raises(ClusterReplayError):
        await t.send("p1:8443", "heartbeat", "me", "dup", seq=0)
    assert ok1 is True
    await transport.aclose()


@pytest.mark.asyncio
async def test_send_failure_enqueues_pending_and_flush_retries(tmp_path):
    calls = {"n": 0}
    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            (200 if calls["n"] >= 2 else 500),
            # 成功响应需符合 sync_event 确认契约：acked_seq==seq 且 applied=True，
            # 否则 transport 按“未获对端应用确认”保留重投
            json={"error_code": "CLUSTER_SERVICE_ERROR"} if calls["n"] < 2 else {"ok": True, "acked_seq": 7, "applied": True},
        )
    cfg = make_config()
    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    t = ClusterTransport(config=cfg, secret=cfg.cluster_secret, node_id="me", pending_dir=tmp_path, client=transport)

    first = await t.send("p1:8443", "sync_event", "me", "req-f", seq=7, payload={"k": "v"})
    assert first is False  # 500 → 入待发队列
    assert t.pending_count() == 1

    await t.flush_pending()
    assert t.pending_count() == 0
    assert calls["n"] == 2  # 首次失败 + flush 重试成功
    await transport.aclose()


@pytest.mark.asyncio
async def test_auth_failure_raises_not_enqueued(tmp_path):
    def handler(request):
        return httpx.Response(403, json={"error_code": "CLUSTER_AUTH_FAILED"})
    cfg = make_config()
    transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    t = ClusterTransport(config=cfg, secret="wrong", node_id="me", pending_dir=tmp_path, client=transport)

    from server.core.cluster._common import CLUSTER_AUTH_FAILED, ClusterError
    with pytest.raises(ClusterError) as exc:
        await t.send("p1:8443", "heartbeat", "me", "req-a")
    assert exc.value.error_code == CLUSTER_AUTH_FAILED
    assert t.pending_count() == 0  # 认证失败不入队
    await transport.aclose()


@pytest.mark.asyncio
async def test_flush_pending_preserves_outbox_on_send_crash(tmp_path):
    """flush 循环中途遇到未受控异常条目时，不得丢失任何磁盘条目。

    新 flush 实现对单条失败做受控分类（异常→瞬时失败→保留），逐条继续；
    结束后原子改写回文件：失败条目仍在、成功条目移除，部分进度持久化。
    """
    import json as _json

    cfg = make_config()
    t = ClusterTransport(config=cfg, secret="sk", node_id="me", pending_dir=tmp_path)
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text(_json.dumps({"peer_endpoint": "p1:8443", "op": "x", "payload": {"n": 1}}) + "\n",
                      encoding="utf-8")
    with open(outbox, "a", encoding="utf-8") as fh:
        fh.write(_json.dumps({"peer_endpoint": "p1:8443", "op": "x", "payload": {"n": 2}}) + "\n")

    calls = {"n": 0}

    async def _fake_post(url, body):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("mid-crash")  # 未受控异常：按瞬时失败保留该条
        return httpx.Response(200, json={"ok": True})

    t._post = _fake_post
    await t.flush_pending()
    # 崩溃条目保留，成功条目移除，文件仍可解析恢复
    assert outbox.exists()
    assert t.pending_count() == 1
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_flush_interrupt_keeps_correct_rows_with_duplicates(tmp_path):
    """flush 熔断中断后按枚举下标保留剩余条目：重复条目不错位。

    全部条目内容相同时，旧实现 rows.index(rec) 按值相等查找首个匹配——
    第 10 条（熔断点）会把 remaining_idx 错定位到 1，导致已保留的 10 条副本
    与 rows[1:]（11 条）重复叠加（12 条输入错写回 21 条）。枚举下标修复后：
    熔断点及其前 9 条逐条保留 + 其后余量 2 条 = 12 条（无重复叠加，零丢失）。
    """
    cfg = make_config()
    t = ClusterTransport(config=cfg, secret="sk", node_id="me", pending_dir=tmp_path)
    outbox = tmp_path / "outbox.jsonl"
    rec = {"peer_endpoint": "p1:8443", "op": "x", "payload": {"n": 1}}
    outbox.write_text(
        "".join(json.dumps(rec, ensure_ascii=False) + "\n" for _ in range(12)),
        encoding="utf-8",
    )

    async def _always_fail(url, body):
        raise RuntimeError("network down")  # 全部瞬时失败，累计连续失败触发熔断

    t._post = _always_fail
    await t.flush_pending()

    # FLUSH_MAX_CONSECUTIVE_FAILURES=10：熔断发生在第 10 条
    # → 前 10 条逐条保留 + remaining（下标 10 起的 2 条）= 12 条（零丢失）
    # 旧实现按值索引错位 → 10 + 11 = 21 条（重复叠加）
    assert t.pending_count() == 12
    lines = [json.loads(x) for x in outbox.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 12
    assert all(line == rec for line in lines)


@pytest.mark.asyncio
async def test_flush_mixed_success_with_duplicates_keeps_position(tmp_path):
    """重复条目场景下"成功才删"语义精确定位：第 1 条成功、第 2 条（重复内容）失败。

    旧 rows.index(rec) 在第 2 条失败时仍匹配到第 1 条的位置——本用例锁定
    枚举下标修复后成功/失败按真实位置生效。
    """
    cfg = make_config()
    t = ClusterTransport(config=cfg, secret="sk", node_id="me", pending_dir=tmp_path)
    outbox = tmp_path / "outbox.jsonl"
    same = {"peer_endpoint": "p1:8443", "op": "x", "payload": {"n": 1}}
    third = {"peer_endpoint": "p1:8443", "op": "x", "payload": {"n": 2}}
    outbox.write_text(
        json.dumps(same, ensure_ascii=False) + "\n"
        + json.dumps(same, ensure_ascii=False) + "\n"
        + json.dumps(third, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    async def _fail_second(url, body):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("transient")  # 第 2 条失败（未达熔断阈值 10，保留）
        return httpx.Response(200, json={"ok": True})

    t._post = _fail_second
    await t.flush_pending()

    # 第 1 条成功移除；第 2 条失败保留；第 3 条成功移除
    assert t.pending_count() == 1
    lines = [json.loads(x) for x in outbox.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines == [same]