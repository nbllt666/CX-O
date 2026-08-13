"""
性能监控中间件
记录 API 响应时间和性能指标
"""
import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class PerformanceMiddleware(BaseHTTPMiddleware):
    """性能监控中间件——记录每个请求的处理耗时并写入响应头与日志。"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求：计时、写 X-Process-Time-Ms 响应头，并按耗时分级记日志。"""
        start_time = time.perf_counter()
        
        response = await call_next(request)
        
        process_time = (time.perf_counter() - start_time) * 1000
        
        response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
        
        path = request.url.path
        method = request.method
        
        if process_time > 100:
            logger.warning("慢请求: %s %s - %.2fms", method, path, process_time)
        elif process_time > 50:
            logger.info("中等请求: %s %s - %.2fms", method, path, process_time)
        else:
            logger.debug("快速请求: %s %s - %.2fms", method, path, process_time)
        
        return response
