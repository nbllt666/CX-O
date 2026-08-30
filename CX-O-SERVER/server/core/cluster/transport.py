"""节点间传输：TLS/HTTPS + 共享密钥 + request_id/seq 防重放 + 失败入待发队列。

- 每次请求携带 node_id + request_id + seq + epoch + payload + secret_hmac。
- 成功返回 True；网络/服务失败写待发队列（JSONL）并返回 False；认证失败抛 ClusterAuthError；
  重复 request_id 抛 ClusterReplayError（time.monotonic + 内存 set 防重放）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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

log = logging.getLogger(__name__)

# ---- flush_pending 边界常量 ----
FLUSH_PERMANENT_DROP_LIMIT = 50      # 单轮永久失败丢弃上限（防风暴：超过则保留余量下轮再试）
FLUSH_MAX_CONSECUTIVE_FAILURES = 10  # 连续发送失败熔断（网络持续不通时中止本轮，避免打爆）


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
        # flush 永久失败累计丢弃计数（可观测）
        self._dropped_count = 0

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

    async def _post(self, url: str, body: dict):
        """低层 POST：解析共享 client 并发起请求（flush/send 共用）。"""
        import server.core.utils as _utils

        client = self._client or _utils.get_shared_http_client()
        return await client.post(url, json=body, timeout=self._timeout_sec)

    def _build_body(
        self,
        op: str,
        node_id: str,
        request_id: str,
        seq: int = 0,
        epoch: int = 0,
        payload: dict = None,
    ) -> dict:
        return {
            "op": op,
            "node_id": node_id,
            "request_id": request_id,
            "seq": int(seq),
            "epoch": int(epoch),
            "payload": payload or {},
            "secret_hmac": compute_hmac(self._secret, node_id, request_id, str(int(seq)), op),
        }

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
        request_id = request_id or uuid.uuid4().hex
        if self.is_replayed(request_id):
            raise ClusterReplayError(f"replayed request_id={request_id}")

        url = build_endpoint(self._scheme, peer_endpoint, op)
        body = self._build_body(op, node_id, request_id, seq=seq, epoch=epoch, payload=payload)
        self._mark(request_id)
        try:
            resp = await self._post(url, body)
            if resp.status_code < 200 or resp.status_code >= 300:
                data = self._decode(resp)
                if parse_error_code(data) == CLUSTER_AUTH_FAILED:
                    raise ClusterAuthError(f"auth failed to {peer_endpoint}")
                # G1/A3: _enqueue 含同步 mkdir+open+write，async 上下文内经线程包裹
                await asyncio.to_thread(self._enqueue, peer_endpoint, body)
                return False
            # B4 应用级确认：sync_event 不能只看 HTTP 状态码——对端 2xx 但
            # applied=False 且未回 ack（acked_seq=0，应用失败/纪元拒绝）时视为
            # 本次投递未确认。返回 False 让 replicator._drain 保留 outbox 条目
            # 重投；不写磁盘待发队列（事件仍在 replicator outbox，避免双队列重复重投）。
            if op == "sync_event" and not self._sync_event_acked(self._decode(resp), seq):
                log.warning(
                    "[transport] sync_event 未获对端应用确认 endpoint=%s seq=%s resp=%s，保留重投",
                    peer_endpoint, seq, self._decode(resp),
                )
                return False
            return True
        except ClusterError:
            raise
        except Exception:  # noqa: BLE001 - 网络/超时等统一入待发队列
            # G1/A3: 同上——入队写盘经线程包裹，不阻塞事件循环
            await asyncio.to_thread(self._enqueue, peer_endpoint, body)
            return False

    @staticmethod
    def _sync_event_acked(data: dict, seq: int) -> bool:
        """判定 sync_event 响应是否构成有效应用确认（B4）。

        判据：acked_seq == 本次发送的 seq（新应用与幂等重放均回完整 ack）→ 确认；
        acked_seq==0 / 缺字段 / 非法 → 未确认。旧版对端恒回 acked_seq=event_seq，
        天然兼容本判据。
        """
        if not isinstance(data, dict):
            return False
        try:
            acked = int(data.get("acked_seq") or 0)
        except (TypeError, ValueError):
            return False
        return acked == int(seq)

    async def send_with_reply(
        self,
        peer_endpoint: str,
        op: str,
        node_id: str,
        request_id: str,
        seq: int = 0,
        epoch: int = 0,
        payload: dict = None,
    ) -> dict | None:
        """发送并取回对端应答体（gossip 等请求-响应语义）。

        - 2xx：返回解析后的 JSON dict；
        - 认证失败：抛 ClusterAuthError（与其他发送路径同约定）；
        - 其他服务失败 / 网络失败：返回 None（不排队——一次性问询重放无意义）。
        """
        request_id = request_id or uuid.uuid4().hex
        if self.is_replayed(request_id):
            raise ClusterReplayError(f"replayed request_id={request_id}")
        url = build_endpoint(self._scheme, peer_endpoint, op)
        body = self._build_body(op, node_id, request_id, seq=seq, epoch=epoch, payload=payload)
        self._mark(request_id)
        try:
            resp = await self._post(url, body)
        except ClusterError:
            raise
        except Exception:  # noqa: BLE001 - 网络/超时等统一视为无应答
            return None
        if resp.status_code < 200 or resp.status_code >= 300:
            data = self._decode(resp)
            if parse_error_code(data) == CLUSTER_AUTH_FAILED:
                raise ClusterAuthError(f"auth failed to {peer_endpoint}")
            return None
        try:
            return resp.json() or {}
        except Exception:  # noqa: BLE001
            return {}

    async def flush_pending(self) -> None:
        """逐条重试待发队列。

        - 发送成功 → 该条移除；
        - 4xx/认证类永久失败 → 计入丢弃计数并移除（单轮有 FLUSH_PERMANENT_DROP_LIMIT 上限防风暴）；
        - 网络类失败 → 条目保留；
        - 连续失败达 FLUSH_MAX_CONSECUTIVE_FAILURES → 中止本轮，余量保留；
        - 循环结束后把剩余条目原子改写回文件（tmp + os.replace）。
          改写前先按字节偏移量回收"flush 期间并发追加"的新条目，避免读改写窗口丢数据；
          改写本身原子：循环中途崩溃时原文件完好未动，磁盘上条目仍可恢复。
        """
        f = self._pending_dir / "outbox.jsonl"
        if not f.exists():
            return

        # 二进制读取并记录偏移量，供后续回收窗口期内新追加的字节。
        # 阻塞整读经 asyncio.to_thread 包裹：outbox 较大时不再卡事件循环。
        raw = await asyncio.to_thread(f.read_bytes)
        offset = len(raw)

        rows: list[dict] = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        kept: list[dict] = []
        permanent_dropped = 0
        consecutive_failures = 0
        for idx, rec in enumerate(rows):
            peer_endpoint = rec.get("peer_endpoint", "")
            op = rec.get("op", "")
            node_id = rec.get("node_id", self._node_id or "")
            if not peer_endpoint:
                continue  # 无效条目（缺目标端点）直接移除

            rid = uuid.uuid4().hex  # 重试用新 request_id 避免对端防重放误判
            body = {
                "op": op,
                "node_id": node_id,
                "request_id": rid,
                "seq": int(rec.get("seq", 0)),
                "epoch": int(rec.get("epoch", 0)),
                "payload": rec.get("payload") or {},
                "secret_hmac": compute_hmac(self._secret, node_id, rid, str(int(rec.get("seq", 0))), op),
            }
            outcome = "transient"
            try:
                resp = await self._post(build_endpoint(self._scheme, peer_endpoint, op), body)
                if 200 <= resp.status_code < 300:
                    # B4 应用级确认：sync_event 2xx 但未获 ack（acked_seq=0）时
                    # 视为瞬时未确认——条目保留重投，不得当 ok 移除（假确认丢数据），
                    # 也不得当 permanent 丢弃。
                    if op == "sync_event" and not self._sync_event_acked(self._decode(resp), int(rec.get("seq", 0))):
                        outcome = "transient"
                        log.warning(
                            "[flush] sync_event 未获对端应用确认 endpoint=%s seq=%s，保留重投",
                            peer_endpoint, rec.get("seq", 0),
                        )
                    else:
                        outcome = "ok"
                else:
                    code = parse_error_code(self._decode(resp))
                    # 4xx 与认证失败视为永久失败；5xx 视为瞬时失败
                    if (400 <= resp.status_code < 500) or code == CLUSTER_AUTH_FAILED:
                        outcome = "permanent"
            except Exception:  # noqa: BLE001 - 网络/超时等统一为瞬时失败
                outcome = "transient"

            if outcome == "ok":
                consecutive_failures = 0
                continue

            if outcome == "permanent" and permanent_dropped < FLUSH_PERMANENT_DROP_LIMIT:
                permanent_dropped += 1
                self._dropped_count += 1
                consecutive_failures += 1
                log.warning(
                    "[flush] 永久失败条目已丢弃 endpoint=%s op=%s dropped_total=%d",
                    peer_endpoint, op, self._dropped_count,
                )
                continue

            # 瞬时失败 / 超过单轮丢弃上限：保留待下轮
            kept.append({**rec})
            consecutive_failures += 1
            if consecutive_failures >= FLUSH_MAX_CONSECUTIVE_FAILURES:
                # 用枚举下标定位剩余条目：旧 rows.index(rec) 按值相等查找，
                # 重复条目（内容相同的 JSONL 行）会错位到首个匹配位置，多保/少保数据
                remaining_idx = idx + 1
                kept.extend(rows[remaining_idx:])
                log.warning(
                    "[flush] 连续失败 %d 次，中止本轮，剩余 %d 条保留",
                    consecutive_failures, len(kept),
                )
                break

        # 回收 flush 执行期间并发追加进文件的条目（读改写窗口保护）。
        # 阻塞读（stat + seek + read）经线程包裹，不卡事件循环。
        def _read_appended() -> bytes:
            try:
                size_now = f.stat().st_size
                if size_now > offset:
                    with open(f, "rb") as fh:
                        fh.seek(offset)
                        return fh.read()
            except OSError:
                pass
            return b""

        appended_raw = await asyncio.to_thread(_read_appended)

        final_bytes = b"".join(
            (json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8") for r in kept
        ) + appended_raw

        tmp = f.with_suffix(".jsonl.tmp")

        # 原子改写（拼字节 + tmp 写 + os.replace）经线程包裹：保持既有崩溃安全
        # 语义不变（中途失败原文件完好），只是不再阻塞事件循环。
        def _atomic_rewrite() -> None:
            with open(tmp, "wb") as fh:
                fh.write(final_bytes)
            os.replace(tmp, f)

        try:
            await asyncio.to_thread(_atomic_rewrite)
        except OSError:
            # 改写失败：保留原文件不动（条目仍在磁盘可恢复）
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    @property
    def dropped_count(self) -> int:
        """flush 周期中永久失败累计丢弃数（可观测）。"""
        return self._dropped_count

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