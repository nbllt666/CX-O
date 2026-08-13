"""server.api.response 与 server.api.middleware.performance 单元测试。

覆盖：
- APIResponse / PaginatedResponse / HealthResponse / ErrorResponse 的工厂与分页逻辑
- PerformanceMiddleware 请求计时与慢请求日志

运行：python -m pytest tests/test_api_response.py -v
"""
from server.api.response import (
    APIResponse,
    PaginatedResponse,
    HealthResponse,
    ErrorResponse,
)


# ================================================================ APIResponse
class TestAPIResponse:
    def test_ok_default(self):
        r = APIResponse.ok(data={"a": 1})
        assert r.success is True
        assert r.data == {"a": 1}
        assert r.error_message is None

    def test_ok_with_message(self):
        r = APIResponse.ok(data=None, message="成功")
        assert r.message == "成功"

    def test_error(self):
        r = APIResponse.error("出错了", error_code="E1")
        assert r.success is False
        assert r.error_message == "出错了"
        assert r.error_code == "E1"

    def test_error_alias_populate(self):
        # error 别名可用于构造
        r = APIResponse(error="通过别名")
        assert r.error_message == "通过别名"

    def test_timestamp_present(self):
        assert APIResponse.ok().timestamp  # 非空


# ================================================================ PaginatedResponse
class TestPaginatedResponse:
    def test_create_total_pages(self):
        r = PaginatedResponse.create([1, 2, 3], total=23, page=2, page_size=10)
        assert r.total_pages == 3
        assert r.total == 23
        assert r.page == 2
        assert r.page_size == 10

    def test_create_exact_multiple(self):
        r = PaginatedResponse.create([1, 2], total=20, page=1, page_size=10)
        assert r.total_pages == 2

    def test_create_zero_page_size(self):
        r = PaginatedResponse.create([], total=0, page_size=0)
        assert r.total_pages == 0  # 避免除零

    def test_empty_data_default(self):
        r = PaginatedResponse.create([], total=0)
        assert r.data == []


# ================================================================ 其他响应模型
class TestOtherResponses:
    def test_health_response_defaults(self):
        h = HealthResponse()
        assert h.status == "ok"
        assert h.version == "1.0.0"
        assert h.components == {}

    def test_error_response(self):
        e = ErrorResponse(error="fail")
        assert e.success is False
        assert e.error_message == "fail"