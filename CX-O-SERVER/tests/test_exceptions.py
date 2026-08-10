"""server.core.exceptions 单元测试。

覆盖异常层级、默认/自定义 code、details、to_dict、__str__ 与继承关系。
运行：python -m pytest tests/test_exceptions.py -v
"""
import pytest

from server.core import exceptions as exc


class TestCoreException:
    def test_default_values(self):
        e = exc.CoreException()
        assert e.message == "An error occurred"
        assert e.code == "CORE_ERROR"
        assert e.details == {}

    def test_custom_code(self):
        e = exc.CoreException("boom", code="X")
        assert e.code == "X"

    def test_custom_details(self):
        e = exc.CoreException("boom", details={"k": 1})
        assert e.details == {"k": 1}

    def test_str_format(self):
        e = exc.CoreException("boom", code="X")
        assert str(e) == "[X] boom"

    def test_to_dict(self):
        e = exc.CoreException("boom", code="X", details={"a": 1})
        d = e.to_dict()
        assert d["error"] == "CoreException"
        assert d["code"] == "X"
        assert d["message"] == "boom"
        assert d["details"] == {"a": 1}

    def test_is_exception(self):
        assert isinstance(exc.CoreException(), Exception)


class TestSubclasses:
    @pytest.mark.parametrize(
        "cls,code",
        [
            (exc.DatabaseError, "DATABASE_ERROR"),
            (exc.ValidationError, "VALIDATION_ERROR"),
            (exc.ACPError, "ACP_ERROR"),
            (exc.MemoryOperationError, "MEMORY_ERROR"),
            (exc.VectorStoreError, "VECTOR_STORE_ERROR"),
            (exc.LLMError, "LLM_ERROR"),
            (exc.ToolError, "TOOL_ERROR"),
            (exc.MCPError, "MCP_ERROR"),
            (exc.ContextError, "CONTEXT_ERROR"),
        ],
    )
    def test_default_code(self, cls, code):
        assert cls().code == code

    def test_inheritance(self):
        for cls in [
            exc.DatabaseError,
            exc.ValidationError,
            exc.ACPError,
            exc.MemoryOperationError,
            exc.VectorStoreError,
            exc.LLMError,
            exc.ToolError,
            exc.MCPError,
            exc.ContextError,
        ]:
            assert issubclass(cls, exc.CoreException)

    def test_subclass_custom_code_overrides(self):
        e = exc.LLMError("x", code="CUSTOM")
        assert e.code == "CUSTOM"

    def test_subclass_to_dict_uses_own_name(self):
        e = exc.DatabaseError("db")
        assert e.to_dict()["error"] == "DatabaseError"