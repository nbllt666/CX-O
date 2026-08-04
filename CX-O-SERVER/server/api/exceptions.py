from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .response import ErrorResponse


class ServiceError(Exception):
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


class DatabaseError(ServiceError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, "DATABASE_ERROR", 500, details)


class MemoryNotFoundError(ServiceError):
    def __init__(self, memory_id: str):
        super().__init__(f"Memory not found: {memory_id}", "MEMORY_NOT_FOUND", 404)


class AgentNotFoundError(ServiceError):
    def __init__(self, agent_id: str):
        super().__init__(f"Agent not found: {agent_id}", "AGENT_NOT_FOUND", 404)


class SessionNotFoundError(ServiceError):
    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}", "SESSION_NOT_FOUND", 404)


class LLMError(ServiceError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, "LLM_ERROR", 503, details)


class VectorStoreError(ServiceError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, "VECTOR_STORE_ERROR", 503, details)


class ValidationError(ServiceError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, "VALIDATION_ERROR", 400, details)


class AuthenticationError(ServiceError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, "AUTHENTICATION_ERROR", 401)


class RateLimitError(ServiceError):
    def __init__(self, retry_after: int = 60):
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after} seconds",
            "RATE_LIMIT_ERROR",
            429,
            {"retry_after": retry_after},
        )


async def service_exception_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_message=exc.message, error_code=exc.error_code, details=exc.details
        ).model_dump(by_alias=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error_message=str(exc.detail), error_code=f"HTTP_{exc.status_code}"
        ).model_dump(by_alias=True),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
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
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_message="Internal server error",
            error_code="INTERNAL_ERROR",
            details={"exception": str(exc)} if str(exc) else None,
        ).model_dump(by_alias=True),
    )
