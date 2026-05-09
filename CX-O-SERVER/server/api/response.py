from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    request_id: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def ok(cls, data: T = None, message: str = None) -> "APIResponse[T]":
        return cls(success=True, data=data, message=message)

    @classmethod
    def error(cls, error: str, error_code: str = None, data: T = None) -> "APIResponse[T]":
        return cls(success=False, error=error, error_code=error_code, data=data)


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    data: List[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def create(
        cls, data: List[T], total: int, page: int = 1, page_size: int = 20
    ) -> "PaginatedResponse[T]":
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            success=True,
            data=data,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    components: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
