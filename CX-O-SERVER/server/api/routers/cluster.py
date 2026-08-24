"""哨兵集群 REST 端点（spec admin-plane-sentinel-cluster Part B）。

端点：/api/cluster/topology · /api/cluster/state · /api/cluster/sync · /api/cluster/takeover。
依赖模块级单例 _cluster_manager，由 main.py lifespan 经 inject_cluster_runtime 注入；
未装配（cluster.enabled=false）为 None，路由侧自动降级为 disabled 口径（对齐
autonomy/cluster 降级风格）。
"""
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger

router = APIRouter()
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
async def cluster_takeover(req: TakeoverRequest):
    """手动触发故障转移（演练/应急；生产侧权限由管理面/调用方约束）。"""
    mgr = _require_cluster()
    try:
        result = await mgr.maybe_takeover(req.from_node)
    except Exception as e:
        logger.warning("手动故障转移失败: %s", e)
        raise HTTPException(status_code=400, detail=f"故障转移失败: {e}")
    return {"status": "success", "result": result}