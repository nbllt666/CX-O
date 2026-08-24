"""对等发现：种子列表主动握手（默认）；UDP 广播留占位 TODO。

cluster_secret 校验：握手载荷含 node_id + secret_hmac，secret 不匹配由对端拒绝
（HTTP 403 / CLUSTER_AUTH_FAILED）→ 本端抛 ClusterAuthError。
"""
from __future__ import annotations

import hmac
import uuid

from ._common import (
    CLUSTER_AUTH_FAILED,
    CLUSTER_SERVICE_ERROR,
    ClusterAuthError,
    ClusterError,
    build_endpoint,
    compute_hmac,
)


class PeerDiscovery:
    """种子列表主动握手发现。默认不监听/广播；UDP 广播为可选扩展。"""

    # NOTE(UDP 广播，非默认): 若需自组网，可在后续实现 async 的 UDP
    # 广播/SO_REUSEADDR 监听线程；本模块先以种子握手作为唯一默认路径，
    # 不实现网络监听，为跨进程/跨机部署留档。

    def __init__(
        self,
        config=None,
        node_id: str = "",
        node_name: str = "",
        role: str = "standby",
        endpoint: str = "",
        client=None,
        secret: str = "",
    ):
        self._config = config
        self._client = client
        self._secret = secret or (getattr(config, "cluster_secret", "") or "" if config else "")
        self._node_id = node_id
        self._node_name = node_name
        self._role = role
        self._endpoint = endpoint

    def set_client(self, client):  # 依赖注入（便于单测，不发真实网络）
        self._client = client

    def _scheme(self) -> str:
        return getattr(self._config, "transport", "https") or "https" if self._config else "https"

    def _peers(self):
        if not self._config:
            return []
        return list(getattr(self._config, "peers", []) or [])

    def discover(self) -> list[dict]:
        """返回候选 peer dict {endpoint, node_id}。node_id 握手后填充（此前未知）。"""
        return [{"endpoint": ep, "node_id": None} for ep in self._peers()]

    async def handshake(self, peer_endpoint: str) -> dict:
        import server.core.utils as _utils

        url = build_endpoint(self._scheme(), peer_endpoint, "handshake")
        request_id = uuid.uuid4().hex
        secret_hmac = compute_hmac(self._secret, self._node_id, "handshake", self._node_id)
        body = {
            "op": "handshake",
            "node_id": self._node_id,
            "request_id": request_id,
            "seq": 0,
            "epoch": 0,
            "payload": {
                "node_name": self._node_name,
                "role": self._role,
                "endpoint": self._endpoint,
                "secret_hmac": secret_hmac,
            },
        }
        client = self._client or _utils.get_shared_http_client()
        try:
            resp = await client.post(url, json=body, timeout=10.0)
            data = self._decode(resp)
            if resp.is_error:
                code = data.get("error_code") or (data.get("detail") or {}).get("error_code")
                if code == CLUSTER_AUTH_FAILED:
                    raise ClusterAuthError(
                        f"handshake {peer_endpoint} rejected: cluster_secret mismatch"
                    )
                if code:
                    raise ClusterError(code, str(data))
                raise ClusterError(
                    CLUSTER_SERVICE_ERROR,
                    f"handshake {peer_endpoint} failed: http {resp.status_code}",
                )
            peer_id = str(data.get("node_id") or "")
            # 校验对端使用同一共享密钥（对端须回传自身 secret_hmac 证明）
            peer_hmac = (data.get("payload") or {}).get("secret_hmac")
            if peer_id and peer_hmac:
                expected = compute_hmac(self._secret, peer_id, "handshake", peer_id)
                if not hmac.compare_digest(str(peer_hmac), expected):
                    raise ClusterAuthError(f"peer {peer_id} failed secret proof")
            return {"endpoint": peer_endpoint, "node_id": peer_id}
        except ClusterError:
            raise
        except Exception as e:  # noqa: BLE001 - 所有传输异常统一收敛为服务错误
            raise ClusterError(CLUSTER_SERVICE_ERROR, f"handshake {peer_endpoint}: {e}") from e

    @staticmethod
    def _decode(resp) -> dict:
        try:
            return resp.json() or {}
        except Exception:  # noqa: BLE001
            return {"error_code": CLUSTER_SERVICE_ERROR, "message": f"http {resp.status_code}"}