"""哨兵集群 REST 端点（spec admin-plane-sentinel-cluster Part B）。

端点：/api/cluster/topology · /api/cluster/state · /api/cluster/sync · /api/cluster/takeover。
依赖模块级单例 _cluster_manager，由 main.py lifespan 经 inject_cluster_runtime 注入；
未装配（cluster.enabled=false）为 None，路由侧自动降级为 disabled 口径（对齐
autonomy/cluster 降级风格）。

对等接收端（peer_router）：POST /cluster/{handshake|heartbeat|gossip|sync_event|leave}。
sender 端点形状由 server/core/cluster/_common.build_endpoint 决定为 {scheme}://{base}/cluster/{op}
（根级、无 /api 前缀），故本 router 必须在 app.py 以"无前缀"方式挂载，保证发送 URL 恰好命中。
鉴权走节点间共享密钥 HMAC（与发送侧 transport 同一套约定），不走 admin api key。
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.core.cluster._common import CLUSTER_DISABLED, CLUSTER_SERVICE_ERROR
from server.core.logging_config import get_contextual_logger
from server.api.routers.admin import verify_admin_api_key

router = APIRouter()
peer_router = APIRouter()
logger = get_contextual_logger(__name__)

_cluster_manager: Optional[Any] = None


def inject_cluster_runtime(cluster_manager: Optional[Any]) -> None:
    """注入集群管理器单例（main.py lifespan 调用；未启用 cluster.enabled=False 时传 None）。

    Args:
        cluster_manager: SentinelCluster 实例或 None（集群未启用）。
    """
    global _cluster_manager
    _cluster_manager = cluster_manager


def _require_cluster():
    """返回 SentinelCluster 实例；集群未启用时抛 503 disabled。"""
    if _cluster_manager is None:
        raise HTTPException(status_code=503, detail="集群未启用（cluster.enabled=false）")
    return _cluster_manager


class TakeoverRequest(BaseModel):
    """触发故障转移请求体。"""

    from_node: str
    to_node: Optional[str] = None
    params: dict = {}


@router.get("/cluster/topology")
async def cluster_topology():
    """集群拓扑：所有节点、角色、心跳、同步进度。"""
    mgr = _require_cluster()
    return {"status": "success", "topology": mgr.topology()}


@router.get("/cluster/state")
async def cluster_state():
    """集群整体状态：纪元、active 节点、健康度。"""
    mgr = _require_cluster()
    return {"status": "success", "state": mgr.state()}


@router.get("/cluster/sync")
async def cluster_sync():
    """各备份单元同步延迟。"""
    mgr = _require_cluster()
    return {"status": "success", "sync": mgr.sync_status()}


@router.post("/cluster/takeover")
async def cluster_takeover(req: TakeoverRequest, _: bool = Depends(verify_admin_api_key)):
    """手动触发故障转移（演练/应急；生产侧权限由管理面/调用方约束）。"""
    mgr = _require_cluster()
    try:
        result = await mgr.maybe_takeover(req.from_node)
    except Exception as e:
        logger.warning("手动故障转移失败: %s", e)
        raise HTTPException(status_code=400, detail=f"故障转移失败: {e}")
    return {"status": "success", "result": result}


# ---- F1: 对等接收端点（节点间互信，HMAC 鉴权；无 /api 前缀） ----

def _peer_json(status_code: int, content: dict) -> JSONResponse:
    """对端响应统一 {ok: ...} JSON 信封。"""
    return JSONResponse(status_code=status_code, content=content)


@peer_router.post("/cluster/{op}")
async def cluster_peer_op(op: str, request: Request):
    """接收对端节点 op（handshake/heartbeat/gossip/sync_event/leave），分派到 manager。

    - 集群未启用 → 503 CLUSTER_DISABLED（不建任务不发请求的零摩擦原则：未开集群时本路径
      除返回 disabled 外不做任何事）；
    - 非法 JSON 体 → 400；
    - 其余鉴权与分派逻辑集中在 SentinelCluster.handle_peer_op。
    """
    if _cluster_manager is None:
        return _peer_json(503, {
            "ok": False,
            "error_code": CLUSTER_DISABLED,
            "message": "集群未启用（cluster.enabled=false）",
        })
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - 空/坏 body 统一 400
        return _peer_json(400, {
            "ok": False,
            "error_code": CLUSTER_SERVICE_ERROR,
            "message": "invalid json body",
        })
    status_code, data = await _cluster_manager.handle_peer_op(op, body)
    return _peer_json(status_code, data)
