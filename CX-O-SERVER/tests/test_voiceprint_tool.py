"""server.core.tools.voiceprint_tool 单元测试。

隔离外部依赖：monkeypatch asr_service.get_recent_spk_embedding、
voiceprint_service.register_embedding、get_websocket_manager().send_message，
避免触碰真实 ASR/声纹服务与声纹档案文件。

运行：python -m pytest tests/test_voiceprint_tool.py -v
"""
import asyncio

import pytest

import server.core.tools.voiceprint_tool as vt
import server.services.asr_service as asr_mod
import server.services.voiceprint_service as vp_mod
import server.core.websocket.manager as ws_manager_mod
from server.core.tools.registry import tool_registry
from server.core.tools.voiceprint_tool import _handler, register_voiceprint_tool


class _FakeManager:
    """记录 send_message 消息的 WebSocket 管理器替身。"""

    def __init__(self):
        self.sent = []

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


async def _flush_voice_tasks():
    """等待后台注册任务全部完成（done_callback 会将任务从集合移除）。

    后台任务里可能含真实 sleep，故先显式 gather 全部待办任务，
    再轮询一轮等 done_callback 清空集合。
    """
    pending = list(vt._voice_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    for _ in range(50):
        if not vt._voice_tasks:
            return
        await asyncio.sleep(0)
    raise AssertionError("后台注册任务未在预期内完成")


@pytest.fixture
def fake_manager(monkeypatch):
    mgr = _FakeManager()
    monkeypatch.setattr(ws_manager_mod, "get_websocket_manager", lambda: mgr)
    return mgr


@pytest.fixture
def no_embedding(monkeypatch):
    monkeypatch.setattr(asr_mod, "get_recent_spk_embedding", lambda client_id=None: None)


@pytest.fixture
def with_embedding(monkeypatch):
    monkeypatch.setattr(
        asr_mod, "get_recent_spk_embedding", lambda client_id=None: [0.1] * 192
    )


@pytest.fixture
def fake_register(monkeypatch):
    calls = []

    async def _register(name, embedding):
        calls.append((name, embedding))
        return {"name": name, "embeddings_count": 1}

    monkeypatch.setattr(vp_mod, "register_embedding", _register)
    return calls


# ---------------------------------------------------------------- handler
@pytest.mark.asyncio
async def test_handler_success_schedules_background(with_embedding, fake_register, fake_manager):
    result = await _handler(name="小明")
    assert result["success"] is True
    assert result["status"] == "registering"
    assert result["name"] == "小明"

    await _flush_voice_tasks()
    # register_embedding 被异步调用（name + 该客户端 embedding）
    assert any(name == "小明" for name, emb in fake_register)
    # voice.voiceprint_result 事件已推送
    assert fake_manager.sent
    cid, msg = fake_manager.sent[0]
    assert cid == "default"
    assert msg["type"] == "voice.voiceprint_result"
    assert msg["data"]["ok"] is True
    assert msg["data"]["name"] == "小明"


@pytest.mark.asyncio
async def test_background_task_kept_reference_until_complete(with_embedding, fake_manager,
                                                             monkeypatch):
    """handler 立即返回后，后台任务仍被 _voice_tasks 持有（防 GC）。"""
    async def _slow_register(name, embedding):
        await asyncio.sleep(0.05)
        return {"name": name, "embeddings_count": 1}

    monkeypatch.setattr(vp_mod, "register_embedding", _slow_register)

    result = await _handler(name="阿明")
    assert result["success"] is True
    # 任务刚创建，尚未执行完 → 仍被集合持有
    assert len(vt._voice_tasks) == 1
    await _flush_voice_tasks()
    assert len(vt._voice_tasks) == 0


@pytest.mark.asyncio
async def test_handler_no_embedding_returns_error(no_embedding, fake_register, fake_manager):
    result = await _handler(name="小明")
    assert result["success"] is False
    assert "未检测到你的声纹" in result["error"]
    assert not fake_register  # 未发起注册


@pytest.mark.asyncio
async def test_handler_value_error_produces_false_event(with_embedding, fake_manager,
                                                        monkeypatch):
    async def _boom(name, embedding):
        raise ValueError("声纹档案名不能为空且长度不能超过 32")

    monkeypatch.setattr(vp_mod, "register_embedding", _boom)
    result = await _handler(name="小明")
    assert result["success"] is True

    await _flush_voice_tasks()
    cid, msg = fake_manager.sent[0]
    assert msg["type"] == "voice.voiceprint_result"
    assert msg["data"]["ok"] is False
    assert "不能为空且长度不能超过 32" in msg["data"]["detail"]


# ---------------------------------------------------------------- 注册元数据
def test_register_voiceprint_tool_is_registered():
    tool_registry.delete_tool("register_voiceprint")
    register_voiceprint_tool()
    tool = tool_registry.get_tool("register_voiceprint")
    assert tool is not None
    assert tool.enabled is True

    fn = tool.to_openai_function()
    assert fn["function"]["name"] == "register_voiceprint"
    params = fn["function"]["parameters"]
    assert params["required"] == ["name"]
    assert "name" in params["properties"]


# ---------------------------------------------------------------- chat_helpers 注入
def test_get_tools_for_agent_collects_voiceprint(monkeypatch):
    """register_voiceprint 注册后应被 get_tools_for_agent() 收集。"""
    import server.core.tools as tools_mod
    from server.core.tools import builtin as builtin_mod
    from server.chat_helpers import get_tools_for_agent

    # 真实注册表单例已注册 voiceprint；将其作为 get_tools_for_agent 使用的注册表
    assert tool_registry is tools_mod.tool_registry
    register_voiceprint_tool()

    def _list_openai_functions(enabled_only=True, include_builtin=False, category=None):
        return []

    monkeypatch.setattr(
        tools_mod.tool_registry, "list_openai_functions", _list_openai_functions
    )
    monkeypatch.setattr(builtin_mod, "get_builtin_tools", lambda: [{"name": "builtin"}])

    tools = get_tools_for_agent()

    def _tool_name(t):
        return t.get("name") or t.get("function", {}).get("name")

    names = [_tool_name(t) for t in tools]
    assert "builtin" in names
    assert "register_voiceprint" in names