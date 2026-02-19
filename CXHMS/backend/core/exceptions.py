"""
自定义异常类模块

定义项目中使用的所有自定义异常类
"""


class CXHMSException(Exception):
    """CXHMS基础异常类"""

    pass


class DatabaseError(CXHMSException):
    """数据库操作异常"""

    pass


class ValidationError(CXHMSException):
    """数据验证异常"""

    pass


class ACPError(CXHMSException):
    """ACP相关异常"""

    pass


class MemoryOperationError(CXHMSException):
    """记忆管理异常"""

    pass


class VectorStoreError(CXHMSException):
    """向量存储异常"""

    pass


class LLMError(CXHMSException):
    """LLM调用异常"""

    pass


class ToolError(CXHMSException):
    """工具调用异常"""

    pass


class MCPError(CXHMSException):
    """MCP协议异常"""

    pass


class ContextError(CXHMSException):
    """上下文管理异常"""

    pass
