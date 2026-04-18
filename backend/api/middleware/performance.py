"""
性能监控中间件
记录 API 响应时间和性能指标
"""
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        
        response = await call_next(request)
        
        process_time = (time.perf_counter() - start_time) * 1000
        
        response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
        
        path = request.url.path
        method = request.method
        
        if process_time > 100:
            logger.warning(
                f"慢请求: {method} {path} - {process_time:.2f}ms"
            )
        elif process_time > 50:
            logger.info(
                f"中等请求: {method} {path} - {process_time:.2f}ms"
            )
        else:
            logger.debug(
                f"快速请求: {method} {path} - {process_time:.2f}ms"
            )
        
        return response


api_stats = {
    "total_requests": 0,
    "total_time_ms": 0,
    "slow_requests": 0,
    "endpoints": {},
}


def record_api_call(endpoint: str, duration_ms: float):
    api_stats["total_requests"] += 1
    api_stats["total_time_ms"] += duration_ms
    
    if duration_ms > 100:
        api_stats["slow_requests"] += 1
    
    if endpoint not in api_stats["endpoints"]:
        api_stats["endpoints"][endpoint] = {
            "count": 0,
            "total_time_ms": 0,
            "max_time_ms": 0,
            "min_time_ms": float("inf"),
        }
    
    stats = api_stats["endpoints"][endpoint]
    stats["count"] += 1
    stats["total_time_ms"] += duration_ms
    stats["max_time_ms"] = max(stats["max_time_ms"], duration_ms)
    stats["min_time_ms"] = min(stats["min_time_ms"], duration_ms)


def get_api_stats() -> dict:
    return {
        "total_requests": api_stats["total_requests"],
        "average_time_ms": (
            api_stats["total_time_ms"] / api_stats["total_requests"]
            if api_stats["total_requests"] > 0
            else 0
        ),
        "slow_requests": api_stats["slow_requests"],
        "slow_request_rate": (
            api_stats["slow_requests"] / api_stats["total_requests"]
            if api_stats["total_requests"] > 0
            else 0
        ),
        "endpoints": api_stats["endpoints"],
    }
