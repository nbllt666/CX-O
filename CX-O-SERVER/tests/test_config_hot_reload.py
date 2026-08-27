"""配置热更新 apply_section 定向测试（M9：reload_clients 异常不得谎报成功）。"""
from types import SimpleNamespace

import pytest

from server.config_hot_reload import REQUIRES_RESTART, apply_section


class _BrokenRouter:
    async def reload_clients(self):
        raise RuntimeError("llm client pool broken")


class _OkRouter:
    def __init__(self):
        self.reloaded = 0

    async def reload_clients(self):
        self.reloaded += 1


@pytest.mark.asyncio
async def test_llm_reload_failure_returns_applied_false_and_restart():
    """M9：LLM 热更新异常 → applied=False + requires_restart=True + error，不得 fallthrough 谎报成功。"""
    result = await apply_section("llm", {"api_key": "k"}, model_router=_BrokenRouter())
    assert result["applied"] is False
    assert result["requires_restart"] is True
    assert "llm client pool broken" in result["error"]


@pytest.mark.asyncio
async def test_llm_reload_success_reports_applied():
    router = _OkRouter()
    result = await apply_section("llm", {"api_key": "k"}, model_router=router)
    assert result == {"applied": True, "requires_restart": False}
    assert router.reloaded == 1


@pytest.mark.asyncio
async def test_restart_required_section_unaffected_by_llm_branch():
    """cluster 节需重启语义保持不变。"""
    assert REQUIRES_RESTART["cluster"] is True
    result = await apply_section("cluster", {"peers": ["p1"]}, model_router=_OkRouter())
    assert result == {"applied": False, "requires_restart": True}


@pytest.mark.asyncio
async def test_hot_section_without_router_reports_applied():
    """audio 节可热更新、无路由依赖 → applied=True。"""
    result = await apply_section("audio", {"volume": 0.8}, model_router=None)
    assert result == {"applied": True, "requires_restart": False}
