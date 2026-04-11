class CXHMSException(Exception):
    pass


class DatabaseError(CXHMSException):
    pass


class ValidationError(CXHMSException):
    pass


class ACPError(CXHMSException):
    pass


class MemoryOperationError(CXHMSException):
    pass


class VectorStoreError(CXHMSException):
    pass


class LLMError(CXHMSException):
    pass


class ToolError(CXHMSException):
    pass


class MCPError(CXHMSException):
    pass


class ContextError(CXHMSException):
    pass