"""节点间传输：TLS/HTTPS + 共享密钥 + request_id/seq 防重放 + 失败入待发队列。

- 每次请求携带 node_id + request_id + seq + epoch + payload + secret_hmac。
- 成功返回 True；网络/服务失败写待发队列（JSONL）并返回 False；认证失败抛 ClusterAuthError；
  重复 request_id 抛 ClusterReplayError（time.monotonic + 内存 set 防重放）。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from ._common import (
    CLUSTER_AUTH_FAILED,
    CLUSTER_SERVICE_ERROR,
    _PENDING_DIR,
    ClusterAuthError,
    ClusterError,
    ClusterReplayError,
    build_endpoint,
    compute_hmac,
    parse_error_code,
)


class ClusterTransport:
    def __init__(
        self,
        config=None,
        secret: str = "",
        node_id: str = "",
        pending_dir=None,
        client=None,
        scheme: str = "",
    ):
        self._config = config
        self._secret = secret or (getattr(config, "cluster_secret", "") or "" if config else "")
        self._node_id = node_id
        self._scheme = scheme or (getattr(config, "transport", "https") or "https" if config else "https")
        self._pending_dir = Path(pending_dir) if pending_dir else Path(_PENDING_DIR)
        self._client = client
        self._evict_sec = float(getattr(config, "peer_timeout_sec", 15) or 15) if config else 15.0
        self._timeout_sec = max(5.0, self._evict_sec)
        # request_id 防重放：memory set + monotonic 时间窗
        self._seen: dict[str, float] = {}

    # ---- 依赖注入（便于单测，不发真实网络） ----
    def set_client(self, client):
        self._client = client

    def set_secret(self, secret: str):
        self._secret = secret

    def set_node_id(self, node_id: str):
        self._node_id = node_id

    # ---- 防重放 ----
    def _evict(self, now: float):
        stale = [rid for rid, ts in self._seen.items() if now - ts > self._evict_sec]
        for rid in stale:
            self._seen.pop(rid, None)

    def is_replayed(self, request_id: str) -> bool:
        self._evict(time.monotonic())
        return request_id in self._seen

    def _mark(self, request_id: str):
        self._seen[request_id] = time.monotonic()

    # ---- 待发队列（JSONL） ----
    def _enqueue(self, peer_endpoint: str, body: dict):
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        rec = dict(body)
        rec["peer_endpoint"] = peer_endpoint
        with open(self._pending_dir / "outbox.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    async def send(
        self,
        peer_endpoint: str,
        op: str,
        node_id: str,
        request_id: str,
        seq: int = 0,
        epoch: int = 0,
        payload: dict = None,
    ) -> bool:
        import server.core.utils as _utils

        request_id = request_id or uuid.uuid4().hex
        if self.is_replayed(request_id):
            raise ClusterReplayError(f"replayed request_id={request_id}")

        url = build_endpoint(self._scheme, peer_endpoint, op)
        secret_hmac = compute_hmac(self._secret, node_id, request_id, str(seq), op)
        body = {
            "op": op,
            "node_id": node_id,
            "request_id": request_id,
            "seq": int(seq),
            "epoch": int(epoch),
            "payload": payload or {},
            "secret_hmac": secret_hmac,
        }
        self._mark(request_id)
        client = self._client or _utils.get_shared_http_client()
        try:
            resp = await client.post(url, json=body, timeout=self._timeout_sec)
            if resp.status_code < 200 or resp.status_code >= 300:
                data = self._decode(resp)
                if parse_error_code(data) == CLUSTER_AUTH_FAILED:
                    raise ClusterAuthError(f"auth failed to {peer_endpoint}")
                self._enqueue(peer_endpoint, body)
                return False
            return True
        except ClusterError:
            raise
        except Exception:  # noqa: BLE001 - 网络/超时等统一入待发队列
            self._enqueue(peer_endpoint, body)
            return False

    async def flush_pending(self) -> None:
        """尽力重试待发队列。成功即从队列移除；失败则重新入列（新 request_id 避免重放误判）。"""
        f = self._pending_dir / "outbox.jsonl"
        if not f.exists():
            return
        rows = []
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass

        for rec in rows:
            peer_endpoint = rec.pop("peer_endpoint", "")
            if not peer_endpoint:
                continue
            try:
                await self.send(
                    peer_endpoint,
                    rec.get("op", ""),
                    rec.get("node_id", self._node_id or ""),
                    uuid.uuid4().hex,  # 重试用新 request_id
                    seq=rec.get("seq", 0),
                    epoch=rec.get("epoch", 0),
                    payload=rec.get("payload"),
                )
            except ClusterError:
                continue

    def pending_count(self) -> int:
        f = self._pending_dir / "outbox.jsonl"
        if not f.exists():
            return 0
        count = 0
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count

    @staticmethod
    def _decode(resp) -> dict:
        try:
            return resp.json() or {}
        except Exception:  # noqa: BLE001
            return {"error_code": CLUSTER_SERVICE_ERROR, "message": f"http {resp.status_code}"}