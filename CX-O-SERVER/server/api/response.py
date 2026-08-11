"""统一响应模型——泛型 API 响应与通用错误响应的数据结构定义。"""
from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)
    success: bool = True
    data: Optional[T] = None
    error_message: Optional[str] = Field(default=None, alias='error')
    error_code: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    request_id: Optional[str] = None

    @classmethod
    def ok(cls, data: T = None, message: str = None) -> "APIResponse[T]":
        return cls(success=True, data=data, message=message)

    @classmethod
    def error(cls, error_message: str, error_code: str = None, data: T = None) -> "APIResponse[T]":
        return cls(success=False, error_message=error_message, error_code=error_code, data=data)


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
    model_config = ConfigDict(populate_by_name=True)
    success: bool = False
    error_message: str = Field(alias='error')
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
