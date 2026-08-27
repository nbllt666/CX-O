"""server.core.tools.master_tools 单元测试。

覆盖主模型工具的核心逻辑：依赖注入获取、记忆写入/搜索、记忆管理模型调用、
提醒（设置/列表/取消）、上下文保持、永久记忆、ACP 网络调用（列表/连接/发送/
群组）。所有外部依赖（记忆管理器、上下文管理器、副路由器、ACP 管理器）均以
轻量替身注入，避免真实数据库与网络 IO。

运行：python -m pytest tests/test_master_tools.py -v
"""
import pytest

import server.core.tools.master_tools as mt
import server.core.tools.summary_tools as st


# ---------------------------------------------------------------- 依赖替身
class FakeMemoryManager:
    def __init__(self):
        self.written = []
        self.permanent = []
        self.search_results = []

    def write_memory(self, content, memory_type, importance, tags):
        self.written.append((content, memory_type, importance, tags))
        return "mem-1"

    def write_permanent_memory(self, content, tags, is_from_main):
        self.permanent.append((content, tags, is_from_main))
        return "perm-1"

    def search_memories(self, query, memory_type, time_range, limit):
        return self.search_results


class FakeContextManager:
    def __init__(self):
        self.mono_calls = []
        self.mono_result = True
        self.messages = []
        self.deleted = []
        self.added = []

    def add_mono_context(self, session_id, content, rounds):
        self.mono_calls.append((session_id, content, rounds))
        return self.mono_result

    def get_messages(self, session_id, limit):
        return self.messages

    def clear_session_messages(self, session_id):
        del self.messages[:]

    def delete_message(self, msg_id):
        self.deleted.append(msg_id)

    def add_message(self, session_id, role, content, content_type):
        self.added.append((session_id, role, content, content_type))


class FakeResult:
    def __init__(self, output=None, status="success", execution_time_ms=12):
        self.output = output or {"response": "ok"}
        self.status = status
        self.execution_time_ms = execution_time_ms


class FakeSecondaryRouter:
    def __init__(self, result=None, exc=None):
        self.result = result or FakeResult()
        self.exc = exc
        self.instructions = []

    async def execute_command(self, instruction, is_from_main):
        self.instructions.append((instruction, is_from_main))
        if self.exc:
            raise self.exc
        return self.result


class FakeAlarmManager:
    def __init__(self):
        self.created = []
        self.cancelled = []
        self.alarms = []

    def create_alarm(self, agent_id, seconds, message):
        self.created.append((agent_id, seconds, message))
        return "alarm-1"

    def get_alarms_by_agent(self, agent_id, include_triggered):
        return self.alarms

    def cancel_alarm(self, alarm_id):
        self.cancelled.append(alarm_id)
        return "alarm-1" in alarm_id


class FakeACPManager:
    def __init__(self, local_agent_id="local-1", local_agent_name="local"):
        self._local_agent_id = local_agent_id
        self._local_agent_name = local_agent_name
        self.agents = []
        self.agent = None
        self.connections = []
        self.messages = []
        self.groups = []
        self.exc = None

    async def list_agents(self, online_only):
        return self.agents

    async def get_agent(self, agent_id):
        return self.agent

    async def create_connection(self, conn):
        self.connections.append(conn)
        return True

    async def delete_connection(self, connection_id):
        return connection_id in self.connections

    async def send_message(self, msg):
        self.messages.append(msg)

    async def create_group(self, group):
        self.groups.append(group)

    async def add_group_member(self, group_id, member):
        return group_id in self.groups

    async def remove_group_member(self, group_id, agent_id):
        return group_id in self.groups


@pytest.fixture
def clean_deps():
    mt.set_dependencies(None, None, None, None)
    st.set_dependencies(None, None, None)
    yield
    mt.set_dependencies(None, None, None, None)
    st.set_dependencies(None, None, None)


def _set_mm(mm):
    mt.set_dependencies(memory_manager=mm)


def _set_cm(cm):
    mt.set_dependencies(context_manager=cm)


def _set_router(router):
    mt.set_dependencies(secondary_router=router)


def _set_acp(acp):
    mt.set_dependencies(acp_manager=acp)


# ---------------------------------------------------------------- 依赖注入
class TestDependencies:
    def test_set_and_get(self, clean_deps):
        mm = FakeMemoryManager()
        cm = FakeContextManager()
        mt.set_dependencies(memory_manager=mm, context_manager=cm)
        assert mt.get_memory_manager() is mm
        assert mt.get_context_manager() is cm
        assert mt.get_secondary_router() is None
        assert mt.get_acp_manager() is None


# ---------------------------------------------------------------- 记忆写入
class TestWriteLongTermMemory:
    def test_empty_content(self, clean_deps):
        assert mt.write_long_term_memory(None) == {"error": "内容不能为空"}

    def test_no_manager(self, clean_deps):
        r = mt.write_long_term_memory("hello")
        assert r == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = mt.write_long_term_memory("记住用户喜欢蓝色", importance=5, tags=["color"])
        assert r["status"] == "success"
        assert r["memory_id"] == "mem-1"
        assert mm.written == [("记住用户喜欢蓝色", "long_term", 5, ["color"])]

    def test_alias_message_priority_tag(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        mt.write_long_term_memory(message="别名内容", priority=2, tag="kw")
        assert mm.written[0] == ("别名内容", "long_term", 2, ["kw"])

    def test_write_exception(self, clean_deps):
        class Boom:
            def write_memory(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = mt.write_long_term_memory("x")
        assert "保存记忆失败" in r["error"]


# ---------------------------------------------------------------- 记忆搜索
class TestSearchAllMemories:
    def test_no_manager(self, clean_deps):
        r = mt.search_all_memories("q")
        assert r == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        mm.search_results = [
            {"id": "m1", "content": "a" * 50, "importance": 3, "created_at": "t1"},
            {"id": "m2", "content": "b" * 50, "importance": 2, "created_at": "t2"},
        ]
        _set_mm(mm)
        r = mt.search_all_memories("q", memory_type="all", limit=5)
        assert r["status"] == "success"
        assert r["count"] == 2
        assert r["memories"][0]["id"] == "m1"
        assert r["query"] == "q"

    def test_search_exception(self, clean_deps):
        class Boom:
            def search_memories(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = mt.search_all_memories("q")
        assert "搜索记忆失败" in r["error"]


# ---------------------------------------------------------------- 记忆管理模型
class TestCallAssistant:
    @pytest.mark.asyncio
    async def test_no_router(self, clean_deps):
        r = await mt.call_assistant("msg")
        assert r == {"error": "记忆管理模型不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        router = FakeSecondaryRouter(
            FakeResult(output={"response": "完成"}, status="done", execution_time_ms=33)
        )
        _set_router(router)
        r = await mt.call_assistant("总结")
        assert r["status"] == "done"
        assert r["response"] == "完成"
        assert r["message"] == "总结"
        assert len(router.instructions) == 1

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        _set_router(FakeSecondaryRouter(exc=RuntimeError("boom")))
        r = await mt.call_assistant("总结")
        assert "调用记忆管理模型失败" in r["error"]


# ---------------------------------------------------------------- 提醒
class TestAlarms:
    def test_set_alarm_bad_seconds(self, clean_deps, monkeypatch):
        r = mt.set_alarm(0, "msg")
        assert "秒数必须大于等于1" in r["error"]

    def test_set_alarm_rejects_above_24h(self, clean_deps):
        """上限校验（L 修复）：seconds > 86400 直接拒绝，不触达告警管理器。"""
        r = mt.set_alarm(86401, "太长")
        assert "error" in r
        assert "86400" in r["error"]

    def test_set_alarm_accepts_24h_boundary(self, clean_deps, monkeypatch):
        mgr = FakeAlarmManager()
        monkeypatch.setattr("server.core.alarm.get_alarm_manager", lambda: mgr)
        r = mt.set_alarm(86400, "恰好24小时")
        assert r["status"] == "scheduled"
        assert mgr.created == [("default", 86400, "恰好24小时")]

    def test_set_alarm_success(self, clean_deps, monkeypatch):
        mgr = FakeAlarmManager()
        monkeypatch.setattr("server.core.alarm.get_alarm_manager", lambda: mgr)
        r = mt.set_alarm(30, "喝水", agent_id="agent-1")
        assert r["status"] == "scheduled"
        assert r["alarm_id"] == "alarm-1"
        assert mgr.created == [("agent-1", 30, "喝水")]

    def test_set_alarm_exception(self, clean_deps, monkeypatch):
        def boom():
            raise RuntimeError("boom")

        monkeypatch.setattr("server.core.alarm.get_alarm_manager", boom)
        r = mt.set_alarm(5, "msg")
        assert "设置提醒失败" in r["error"]

    def test_get_alarms_success(self, clean_deps, monkeypatch):
        mgr = FakeAlarmManager()
        mgr.alarms = [{"id": "alarm-1", "message": "喝水"}]
        monkeypatch.setattr("server.core.alarm.get_alarm_manager", lambda: mgr)
        r = mt.get_alarms("agent-1", include_triggered=True)
        assert r["status"] == "success"
        assert r["count"] == 1

    def test_get_alarms_exception(self, clean_deps, monkeypatch):
        def boom():
            raise RuntimeError("boom")

        monkeypatch.setattr("server.core.alarm.get_alarm_manager", boom)
        r = mt.get_alarms()
        assert "获取提醒列表失败" in r["error"]

    def test_cancel_alarm_found(self, clean_deps, monkeypatch):
        mgr = FakeAlarmManager()
        monkeypatch.setattr("server.core.alarm.get_alarm_manager", lambda: mgr)
        r = mt.cancel_alarm("alarm-1")
        assert r["status"] == "cancelled"

    def test_cancel_alarm_not_found(self, clean_deps, monkeypatch):
        mgr = FakeAlarmManager()
        monkeypatch.setattr("server.core.alarm.get_alarm_manager", lambda: mgr)
        r = mt.cancel_alarm("other")
        assert r["status"] == "not_found"

    def test_cancel_alarm_exception(self, clean_deps, monkeypatch):
        def boom():
            raise RuntimeError("boom")

        monkeypatch.setattr("server.core.alarm.get_alarm_manager", boom)
        r = mt.cancel_alarm("alarm-1")
        assert "取消提醒失败" in r["error"]


# ---------------------------------------------------------------- 上下文保持
class TestMono:
    def test_no_context_manager(self, clean_deps):
        r = mt.mono("content")
        assert r == {"error": "上下文管理器不可用"}

    def test_no_session_id(self, clean_deps):
        _set_cm(FakeContextManager())
        r = mt.mono("content")
        assert r["status"] == "info"
        assert r["session_id"] is None

    def test_success(self, clean_deps):
        cm = FakeContextManager()
        _set_cm(cm)
        r = mt.mono("记住张三", session_id="s1", rounds=3)
        assert r["status"] == "success"
        assert cm.mono_calls == [("s1", "记住张三", 3)]

    def test_failed(self, clean_deps):
        cm = FakeContextManager()
        cm.mono_result = False
        _set_cm(cm)
        r = mt.mono("记住张三", session_id="s1")
        assert r["status"] == "failed"

    def test_exception(self, clean_deps):
        class Boom:
            def add_mono_context(self, **kw):
                raise RuntimeError("boom")

        _set_cm(Boom())
        r = mt.mono("x", session_id="s1")
        assert "添加上下文信息失败" in r["error"]


# ---------------------------------------------------------------- 永久记忆
class TestWritePermanentMemory:
    def test_empty(self, clean_deps):
        assert mt.write_permanent_memory(None) == {"error": "内容不能为空"}

    def test_no_manager(self, clean_deps):
        assert mt.write_permanent_memory("x") == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = mt.write_permanent_memory("用户是素食主义者", tags=["fact"])
        assert r["status"] == "success"
        assert r["memory_id"] == "perm-1"
        assert mm.permanent == [("用户是素食主义者", ["fact"], True)]

    def test_alias(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        mt.write_permanent_memory(message="别名", tag="t")
        assert mm.permanent[0][0] == "别名"

    def test_exception(self, clean_deps):
        class Boom:
            def write_permanent_memory(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = mt.write_permanent_memory("x")
        assert "保存永久记忆失败" in r["error"]


# ---------------------------------------------------------------- ACP
class TestACPListAgents:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_list_agents()
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        acp = FakeACPManager()
        acp.agents = [{"id": "a1", "name": "Agent1"}]
        _set_acp(acp)
        r = await mt.acp_list_agents(online_only=True)
        assert r["status"] == "success"
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        class Boom:
            async def list_agents(self, online_only):
                raise RuntimeError("boom")

        _set_acp(Boom())
        r = await mt.acp_list_agents()
        assert "获取 Agent 列表失败" in r["error"]


class TestACPConnect:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_connect("a1")
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_missing_host(self, clean_deps):
        _set_acp(FakeACPManager())
        r = await mt.acp_connect("a1")
        assert "未注册" in r["error"]

    @pytest.mark.asyncio
    async def test_success_registered(self, clean_deps):
        acp = FakeACPManager()
        acp.agent = {"host": "10.0.0.1", "port": 7000, "name": "Agent1"}
        _set_acp(acp)
        r = await mt.acp_connect("a1")
        assert r["status"] == "success"
        assert r["host"] == "10.0.0.1"
        assert r["port"] == 7000
        assert len(acp.connections) == 1

    @pytest.mark.asyncio
    async def test_success_explicit_host(self, clean_deps):
        acp = FakeACPManager()
        _set_acp(acp)
        r = await mt.acp_connect("a1", host="example.com", port=8080)
        assert r["status"] == "success"
        assert r["host"] == "example.com"

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        class Boom:
            _local_agent_id = "local"

            async def get_agent(self, agent_id):
                raise RuntimeError("boom")

        _set_acp(Boom())
        r = await mt.acp_connect("a1", host="h", port=1)
        assert "连接 Agent 失败" in r["error"]


class TestACPDisconnect:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_disconnect("c1")
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        acp = FakeACPManager()
        acp.connections.append("c1")
        _set_acp(acp)
        r = await mt.acp_disconnect("c1")
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_not_found(self, clean_deps):
        _set_acp(FakeACPManager())
        r = await mt.acp_disconnect("c1")
        assert "不存在" in r["error"]


class TestACPSendMessage:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_send_message("a1", "hi")
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        acp = FakeACPManager()
        _set_acp(acp)
        r = await mt.acp_send_message("a1", "hi", message_type="task")
        assert r["status"] == "success"
        assert len(acp.messages) == 1
        assert acp.messages[0].to_agent_id == "a1"
        assert acp.messages[0].msg_type == "task"
        assert acp.messages[0].content == {"text": "hi"}


class TestACPCreateGroup:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_create_group("g")
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        acp = FakeACPManager()
        _set_acp(acp)
        r = await mt.acp_create_group("协作组", description="项目")
        assert r["status"] == "success"
        assert len(acp.groups) == 1
        assert acp.groups[0].name == "协作组"


class TestACPJoinGroup:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_join_group("g1")
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        acp = FakeACPManager()
        acp.groups.append("g1")
        _set_acp(acp)
        r = await mt.acp_join_group("g1")
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_not_found(self, clean_deps):
        _set_acp(FakeACPManager())
        r = await mt.acp_join_group("g1")
        assert "不存在" in r["error"]


class TestACPLeaveGroup:
    @pytest.mark.asyncio
    async def test_no_acp(self, clean_deps):
        r = await mt.acp_leave_group("g1")
        assert r == {"error": "ACP 管理器不可用"}

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        acp = FakeACPManager()
        acp.groups.append("g1")
        _set_acp(acp)
        r = await mt.acp_leave_group("g1")
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_not_found(self, clean_deps):
        _set_acp(FakeACPManager())
        r = await mt.acp_leave_group("g1")
        assert "不存在" in r["error"]