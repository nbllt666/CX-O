"""统一异常体系——服务异常定义与全局异常处理器注册。"""
import logging
from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .response import ErrorResponse

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """业务服务异常基类——统一携带错误码、HTTP 状态码与附加详情。"""

    def __init__(
        self,
        message: str,
        error_code: str = None,
        status_code: int = 500,
        details: Dict[str, Any] = None,
    ):
        self.message = message
        self.error_code = error_code or "INTERNAL_ERROR"
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


async def service_exception_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """将 ServiceError 转换为统一的 JSON 错误响应。"""

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_message=exc.message, error_code=exc.error_code, details=exc.details
        ).model_dump(by_alias=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """将 HTTPException 转换为统一的 JSON 错误响应。"""

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_message=str(exc.detail), error_code=f"HTTP_{exc.status_code}"
        ).model_dump(by_alias=True),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """统一处理请求校验异常，返回 422 与字段错误详情。"""
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
        )

    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error_message="Validation failed", error_code="VALIDATION_ERROR", details={"errors": errors}
        ).model_dump(by_alias=True),
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器——将未捕获异常统一转换为 500 JSON 响应。

    完整堆栈仅在服务端日志记录（A5 修复）；响应体不携带内部异常文本，
    与 gateway BUG-B-M7 保持同一出口口径，避免向客户端泄漏内部信息。
    """
    logger.error(f"未捕获异常 path={request.url.path}: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_message="Internal server error",
            error_code="INTERNAL_ERROR",
        ).model_dump(by_alias=True),
    )
