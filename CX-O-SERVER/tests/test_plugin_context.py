"""插件上下文（server.core.plugins.context）回归保护测试。

PluginContext 为插件提供与系统交互的 API 门面。测试用轻量替身注入
memory/context/llm/tool_registry/ws 依赖，验证委托与降级（缺依赖返回空、
异常捕获记录日志）行为。
"""
import asyncio

import pytest

from server.core.plugins.context import PluginContext


class FakeMemory:
    def __init__(self):
        self.added = []
        self.query = None

    def add_memory(self, content, **kwargs):
        self.added.append((content, kwargs))
        return f"m{len(self.added)}"

    def search(self, query, limit=10):
        self.query = (query, limit)
        return [{"id": "1", "content": "hit"}]


class FakeContext:
    def __init__(self):
        self.session = {"id": "s1"}
        self.messages = []

    def get_session(self, session_id):
        return self.session

    def add_message(self, session_id, role, content):
        self.messages.append((session_id, role, content))


class FakeLLM:
    def __init__(self, content="回复"):
        self.content = content

    async def chat(self, messages, **kwargs):
        return type("R", (), {"content": self.content})()


class FakeWs:
    def __init__(self):
        self.broadcasted = []
        self.channel_broadcasted = []

    async def broadcast(self, message):
        self.broadcasted.append(message)

    async def broadcast_to_channel(self, channel, message):
        self.channel_broadcasted.append((channel, message))


@pytest.fixture
def ctx(tmp_path):
    return PluginContext(
        plugin_id="p1",
        plugin_name="测试插件",
        config={"a": 1},
        storage_root=tmp_path,  # H3: 私有存储根注入 tmp，避免污染仓库 data/
    )


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
class TestBasic:
    def test_fields(self, ctx):
        assert ctx.plugin_id == "p1"
        assert ctx.plugin_name == "测试插件"
        assert ctx.config == {"a": 1}

    def test_logging_no_error(self, ctx):
        ctx.log_info("i")
        ctx.log_warning("w")
        ctx.log_error("e")
        ctx.log_debug("d")

    def test_config_get_set(self, ctx):
        assert ctx.get_config("a") == 1
        assert ctx.get_config("missing", "d") == "d"
        ctx.set_config("b", 2)
        assert ctx.config["b"] == 2

    def test_storage_stub(self, ctx):
        # H3: get/set_storage 已从桩实现升级为持久化存取（tmp 隔离）
        assert ctx.get_storage("k", None) is None
        ctx.set_storage("k", "v")
        assert ctx.get_storage("k", None) == "v"
        ctx.set_storage("obj", {"x": [1, 2]})
        assert ctx.get_storage("obj") == {"x": [1, 2]}


# --------------------------------------------------------------------------- #
# 记忆 API
# --------------------------------------------------------------------------- #
class TestMemory:
    def test_create_memory_delegates(self, ctx):
        fm = FakeMemory()
        ctx._memory_manager = fm
        result = ctx.create_memory("内容", tags=["t"])
        assert result == {"id": "m1", "content": "内容"}
        assert fm.added[0] == ("内容", {"tags": ["t"]})

    def test_create_memory_exception_returns_none(self, ctx):
        fm = FakeMemory()
        fm.add_memory = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        ctx._memory_manager = fm
        assert ctx.create_memory("内容") is None

    def test_create_memory_no_manager(self, ctx):
        assert ctx.create_memory("内容") is None

    def test_search_memories(self, ctx):
        fm = FakeMemory()
        ctx._memory_manager = fm
        assert ctx.search_memories("q", limit=5) == [{"id": "1", "content": "hit"}]
        assert fm.query == ("q", 5)

    def test_search_memories_exception(self, ctx):
        fm = FakeMemory()
        fm.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        ctx._memory_manager = fm
        assert ctx.search_memories("q") == []


# --------------------------------------------------------------------------- #
# 上下文 API
# --------------------------------------------------------------------------- #
class TestContextApi:
    def test_get_session(self, ctx):
        fc = FakeContext()
        ctx._context_manager = fc
        assert ctx.get_session("s1") == {"id": "s1"}

    def test_get_session_no_manager(self, ctx):
        assert ctx.get_session("s1") is None

    def test_send_message(self, ctx):
        fc = FakeContext()
        ctx._context_manager = fc
        ctx.send_message("s1", "user", "hello")
        assert fc.messages == [("s1", "user", "hello")]

    def test_send_message_no_manager(self, ctx):
        ctx.send_message("s1", "user", "hello")  # 不抛异常

    def test_properties(self, ctx):
        assert ctx.memory_manager is None
        assert ctx.context_manager is None
        assert ctx.llm_client is None
        assert ctx.tool_registry is None
        assert ctx.ws_manager is None


# --------------------------------------------------------------------------- #
# LLM API
# --------------------------------------------------------------------------- #
class TestLLM:
    def test_chat(self, ctx):
        fl = FakeLLM("你好")
        ctx._llm_client = fl
        result = asyncio.run(ctx.chat([{"role": "user", "content": "hi"}]))
        assert result == "你好"

    def test_chat_no_client(self, ctx):
        assert asyncio.run(ctx.chat([{"role": "user", "content": "hi"}])) is None

    def test_chat_exception(self, ctx):
        async def bad(messages, **kwargs):
            raise RuntimeError("x")

        ctx._llm_client = type("L", (), {"chat": bad})()
        assert asyncio.run(ctx.chat([{"role": "user", "content": "hi"}])) is None


# --------------------------------------------------------------------------- #
# 工具 API
# --------------------------------------------------------------------------- #
class TestToolRegistry:
    def test_register_tool(self, ctx):
        calls = []

        class FakeReg:
            def register(self, **kw):
                calls.append(kw)

        ctx._tool_registry = FakeReg()
        ctx.register_tool("t", lambda: 1, description="d", parameters={"x": 1})
        assert calls[0]["name"] == "t"
        assert calls[0]["description"] == "d"
        assert calls[0]["parameters"] == {"x": 1}

    def test_register_tool_no_registry(self, ctx):
        ctx.register_tool("t", lambda: 1)  # 不抛异常

    def test_register_tool_exception(self, ctx):
        from unittest.mock import Mock

        ctx._tool_registry = Mock()
        ctx._tool_registry.register.side_effect = RuntimeError("x")
        ctx.register_tool("t", lambda: 1)  # 捕获并记录，不抛


# --------------------------------------------------------------------------- #
# WebSocket API
# --------------------------------------------------------------------------- #
class TestWebSocket:
    @pytest.mark.asyncio
    async def test_broadcast_channel(self, ctx):
        fw = FakeWs()
        ctx._ws_manager = fw
        ctx.broadcast_message({"a": 1}, channel="ch")
        await asyncio.gather(*list(ctx._background_tasks))
        assert fw.channel_broadcasted == [("ch", {"a": 1})]

    @pytest.mark.asyncio
    async def test_broadcast_no_channel(self, ctx):
        fw = FakeWs()
        ctx._ws_manager = fw
        ctx.broadcast_message({"a": 1})
        await asyncio.gather(*list(ctx._background_tasks))
        assert fw.broadcasted == [{"a": 1}]

    def test_broadcast_no_ws(self, ctx):
        ctx.broadcast_message({"a": 1})  # 不抛异常

    def test_broadcast_exception(self, ctx):
        from unittest.mock import Mock

        fw = Mock()
        fw.broadcast_to_channel.side_effect = RuntimeError("x")
        ctx._ws_manager = fw
        ctx.broadcast_message({"a": 1}, channel="ch")  # 捕获并记录


# --------------------------------------------------------------------------- #
# 后台任务追踪
# --------------------------------------------------------------------------- #
class TestBackgroundTasks:
    @pytest.mark.asyncio
    async def test_track_adds_and_discards_on_done(self):
        ctx = PluginContext("p", "n")

        async def coro():
            return 1

        task = asyncio.create_task(coro())
        ctx._track_background_task(task)
        assert task in ctx._background_tasks
        await asyncio.wait_for(task, 1)
        # 完成后回调已丢弃引用
        assert task not in ctx._background_tasks