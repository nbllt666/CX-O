"""局域网后端发现——扫描本机所在子网的健康检查端点，返回可达的 CX-O 后端地址。

前端在「设置→后端地址」中一键发现局域网内的后端实例，避免手动填写 IP 端口。
扫描逻辑集中在服务端（本机可达的目标），前端仅调用单个端点并展示结果，
规避浏览器跨域/混合内容限制，与 AC 范式「逻辑收束后端、前端薄展示」一致。
"""
import asyncio
import socket
from typing import Dict, List

import httpx
from fastapi import APIRouter, Query

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

router = APIRouter()

# 并发探测上限：避免一次性打开过多连接
_MAX_CONCURRENCY = 64
# /24 子网主机范围
_HOST_START, _HOST_END = 1, 254


def _get_local_ips() -> List[str]:
    """收集本机非回环 IPv4 地址（用于推导局域网子网）。

    优先使用「UDP 建连探测」拿到默认路由出口 IP；再补 hostname 解析与
    getaddrinfo 枚举，覆盖多网卡场景。失败时静默返回空，交由调用方兜底。
    """
    ips: set[str] = set()

    # UDP connect 技巧：不真正发包，仅向系统查询默认出口地址
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass

    # hostname 枚举网卡地址
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    return sorted(ip for ip in ips if not ip.startswith("127."))


def _to_subnets(ips: List[str]) -> List[str]:
    """将 IP 列表收敛为去重的 /24 子网前缀（如 192.168.1）。"""
    subnets: set[str] = set()
    for ip in ips:
        parts = ip.split(".")
        if len(parts) == 4:
            subnets.add(".".join(parts[:3]))
    return sorted(subnets)


async def _probe(url: str, timeout: float) -> bool:
    """探测单个后端健康端点，返回是否可达。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url}/health")
            return resp.status_code == 200
    except Exception:
        return False


@router.get("/discovery/backends")
async def discover_backends(
    port: int = Query(8100, ge=1, le=65535, description="待探测的后端端口"),
    timeout: float = Query(0.8, ge=0.1, le=5.0, description="单地址探测超时（秒）"),
) -> Dict[str, List[Dict[str, object]]]:
    """扫描局域网子网，返回可达的 CX-O 后端地址列表。

    探测路径为 ``http://<host>:<port>/health``，仅收集返回 200 的目标。
    并发受 ``_MAX_CONCURRENCY`` 限制，避免瞬时占用过多连接。
    """
    local_ips = _get_local_ips()
    subnets = _to_subnets(local_ips)
    if not subnets:
        logger.warning("无法确定本机局域网子网，返回空发现结果")
        return {"backends": []}

    candidates: List[str] = []
    for subnet in subnets:
        for host in range(_HOST_START, _HOST_END + 1):
            candidates.append(f"http://{subnet}.{host}:{port}")

    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def probe_limited(url: str) -> bool:
        async with semaphore:
            return await _probe(url, timeout)

    results = await asyncio.gather(*(probe_limited(u) for u in candidates))
    backends: List[Dict[str, object]] = []
    for url, ok in zip(candidates, results):
        if ok:
            host = url.split("//", 1)[1].rsplit(":", 1)[0]
            backends.append({"url": url, "host": host, "port": port})

    logger.info(f"局域网后端发现完成：扫描 {len(candidates)} 个地址，发现 {len(backends)} 个后端")
    return {"backends": backends}