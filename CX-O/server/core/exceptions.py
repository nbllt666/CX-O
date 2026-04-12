from typing import Any, Dict, Optional


class CXHMSException(Exception):
    """CXHMS基础异常类"""

    ERROR_CODE = "CXHMS_ERROR"

    def __init__(
        self,
        message: str = "An error occurred",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.ERROR_CODE
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class DatabaseError(CXHMSException):
    """数据库操作异常"""

    ERROR_CODE = "DATABASE_ERROR"

    def __init__(
        self,
        message: str = "Database operation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class ValidationError(CXHMSException):
    """数据验证异常"""

    ERROR_CODE = "VALIDATION_ERROR"

    def __init__(
        self,
        message: str = "Validation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class ACPError(CXHMSException):
    """ACP相关异常"""

    ERROR_CODE = "ACP_ERROR"

    def __init__(
        self,
        message: str = "ACP operation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class MemoryOperationError(CXHMSException):
    """记忆管理异常"""

    ERROR_CODE = "MEMORY_ERROR"

    def __init__(
        self,
        message: str = "Memory operation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class VectorStoreError(CXHMSException):
    """向量存储异常"""

    ERROR_CODE = "VECTOR_STORE_ERROR"

    def __init__(
        self,
        message: str = "Vector store operation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class LLMError(CXHMSException):
    """LLM调用异常"""

    ERROR_CODE = "LLM_ERROR"

    def __init__(
        self,
        message: str = "LLM operation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class ToolError(CXHMSException):
    """工具调用异常"""

    ERROR_CODE = "TOOL_ERROR"

    def __init__(
        self,
        message: str = "Tool execution failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class MCPError(CXHMSException):
    """MCP协议异常"""

    ERROR_CODE = "MCP_ERROR"

    def __init__(
        self,
        message: str = "MCP protocol error",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)


class ContextError(CXHMSException):
    """上下文管理异常"""

    ERROR_CODE = "CONTEXT_ERROR"

    def __init__(
        self,
        message: str = "Context operation failed",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code, details)