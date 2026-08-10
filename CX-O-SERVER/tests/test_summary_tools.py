"""server.core.tools.summary_tools 单元测试。

覆盖摘要模型工具：摘要生成、摘要记忆保存、日记保存、会话消息获取/清空、
话题摘要配置、以及话题摘要触发（含上下文替换与记忆持久化）。外部依赖
（记忆管理器、模型路由器、上下文管理器）均以轻量替身注入。

运行：python -m pytest tests/test_summary_tools.py -v
"""
import pytest

import server.core.tools.summary_tools as st
from server.core.tools.graph_tools import set_current_agent_id


# ---------------------------------------------------------------- 依赖替身
class FakeSummaryClient:
    def __init__(self, response=None, exc=None):
        self.response = response or _Resp("摘要结果")
        self.exc = exc

    async def chat(self, messages, stream):
        if self.exc:
            raise self.exc
        return self.response


class _Resp:
    def __init__(self, content):
        self.content = content


class AsyncMemoryManager:
    def __init__(self):
        self.writes = []

    async def write_memory_async(self, **kwargs):
        self.writes.append(kwargs)
        return "mem-<id>"


class FakeContextManager:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.deleted = []
        self.added = []

    def get_messages(self, session_id, limit):
        return self.messages

    def clear_session_messages(self, session_id):
        del self.messages[:]

    def delete_message(self, msg_id):
        self.deleted.append(msg_id)

    def add_message(self, session_id, role, content, content_type):
        self.added.append((session_id, role, content, content_type))


class FakeModelRouter:
    def __init__(self, client=None):
        self.client = client or FakeSummaryClient()

    def get_client(self, name):
        return self.client if name == "summary" else None


@pytest.fixture
def clean_deps():
    st.set_dependencies(None, None, None)
    yield
    st.set_dependencies(None, None, None)


def _set_mm(mm):
    st.set_dependencies(memory_manager=mm)


def _set_router(router):
    st.set_dependencies(model_router=router)


def _set_cm(cm):
    st.set_dependencies(context_manager=cm)


# ---------------------------------------------------------------- 配置
class TestTopicSummaryConfig:
    def test_default_config(self, clean_deps):
        cfg = st.get_topic_summary_config()
        assert cfg["auto_save_memory"] is True
        assert cfg["max_history_topics"] is None

    def test_update_known_key(self, clean_deps):
        r = st.update_topic_summary_config("auto_save_memory", False)
        assert r["status"] == "success"
        assert r["config"]["auto_save_memory"] is False

    def test_update_unknown_key(self, clean_deps):
        r = st.update_topic_summary_config("nope", 1)
        assert "未知的配置项" in r["error"]

    def test_set_max_history_topics(self, clean_deps):
        st.set_max_history_topics(5)
        assert st._TOPIC_SUMMARY_CONFIG["max_history_topics"] == 5

    def test_set_max_history_topics_wrapper(self, clean_deps):
        r = st.set_max_history_topics_wrapper(3)
        assert r["status"] == "success"
        assert r["max_history_topics"] == 3

    def test_set_max_history_topics_wrapper_none(self, clean_deps):
        r = st.set_max_history_topics_wrapper(None)
        assert r["status"] == "success"
        assert r["max_history_topics"] is None

    def test_get_wrapper(self, clean_deps):
        assert st.get_topic_summary_config_wrapper() == st.get_topic_summary_config()


# ---------------------------------------------------------------- 摘要生成
class TestSummarizeContent:
    @pytest.mark.asyncio
    async def test_no_client(self, clean_deps):
        r = await st.summarize_content("内容")
        assert r == {"error": "摘要模型不可用"}

    @pytest.mark.asyncio
    async def test_response_object(self, clean_deps):
        _set_router(FakeModelRouter(FakeSummaryClient(_Resp("  简洁摘要  "))))
        r = await st.summarize_content("很长很长的内容")
        assert r["status"] == "success"
        assert r["summary"] == "简洁摘要"
        assert r["original_length"] == len("很长很长的内容")

    @pytest.mark.asyncio
    async def test_response_dict(self, clean_deps):
        _set_router(FakeModelRouter(FakeSummaryClient({"content": "dict摘要"})))
        r = await st.summarize_content("内容")
        assert r["summary"] == "dict摘要"

    @pytest.mark.asyncio
    async def test_response_plain_str(self, clean_deps):
        _set_router(FakeModelRouter(FakeSummaryClient("纯文本")))
        r = await st.summarize_content("内容")
        assert r["status"] == "success"
        assert str == type(r["summary"])

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        _set_router(FakeModelRouter(FakeSummaryClient(exc=RuntimeError("boom"))))
        r = await st.summarize_content("内容")
        assert "生成摘要失败" in r["error"]


# ---------------------------------------------------------------- 摘要记忆保存
class TestSaveSummaryMemory:
    @pytest.mark.asyncio
    async def test_no_manager(self, clean_deps):
        r = await st.save_summary_memory("内容", 5, "202602112235")
        assert r == {"error": "记忆管理器未初始化"}

    @pytest.mark.asyncio
    async def test_empty_content(self, clean_deps):
        _set_mm(AsyncMemoryManager())
        r = await st.save_summary_memory("  ", 5, "202602112235")
        assert "记忆内容不能为空" in r["error"]

    @pytest.mark.asyncio
    async def test_bad_importance(self, clean_deps):
        _set_mm(AsyncMemoryManager())
        r = await st.save_summary_memory("内容", 11, "202602112235")
        assert "重要性必须是 1-10" in r["error"]

    @pytest.mark.asyncio
    async def test_bad_timestamp_format(self, clean_deps):
        _set_mm(AsyncMemoryManager())
        r = await st.save_summary_memory("内容", 5, "2026")
        assert "时间戳格式错误" in r["error"]

    @pytest.mark.asyncio
    async def test_bad_timestamp_value(self, clean_deps):
        _set_mm(AsyncMemoryManager())
        r = await st.save_summary_memory("内容", 5, "202613999999")
        assert "时间戳格式错误" in r["error"]

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        mm = AsyncMemoryManager()
        _set_mm(mm)
        r = await st.save_summary_memory("用户喜欢咖啡", 8, "202602112235", tags=["pref"], topic="爱好")
        assert r["status"] == "success"
        write = mm.writes[0]
        assert write["content"] == "用户喜欢咖啡"
        assert write["memory_type"] == "long_term"
        assert write["importance"] == 0.8
        assert "topic:爱好" in write["tags"]
        assert write["metadata"]["source"] == "summary"

    @pytest.mark.asyncio
    async def test_default_tag(self, clean_deps):
        mm = AsyncMemoryManager()
        _set_mm(mm)
        await st.save_summary_memory("内容", 5, "20260211")
        assert mm.writes[0]["tags"] == ["summary"]

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        class Boom:
            async def write_memory_async(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = await st.save_summary_memory("内容", 5, "202602112235")
        assert "保存记忆失败" in r["error"]


# ---------------------------------------------------------------- 日记保存
class TestSaveDiaryEntry:
    @pytest.mark.asyncio
    async def test_no_manager(self, clean_deps):
        r = await st.save_diary_entry("2026-06-20", "标题", "愉快", "正文", "0-15")
        assert r == {"error": "记忆管理器未初始化"}

    @pytest.mark.asyncio
    async def test_empty_body(self, clean_deps):
        _set_mm(AsyncMemoryManager())
        r = await st.save_diary_entry("2026-06-20", "标题", "愉快", "  ", "0-15")
        assert "日记正文不能为空" in r["error"]

    @pytest.mark.asyncio
    async def test_bad_date(self, clean_deps):
        _set_mm(AsyncMemoryManager())
        r = await st.save_diary_entry("2026/06/20", "标题", "愉快", "正文", "0-15")
        assert "日期格式错误" in r["error"]

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        mm = AsyncMemoryManager()
        _set_mm(mm)
        set_current_agent_id("agentx")
        r = await st.save_diary_entry("2026-06-20", "讨论方案", "积极", "今天我们讨论了方案", "0-15")
        assert r["status"] == "success"
        write = mm.writes[0]
        assert write["memory_type"] == "diary"
        assert write["agent_id"] == "agentx"
        assert write["metadata"]["date"] == "2026-06-20"
        assert write["metadata"]["title"] == "讨论方案"

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        class Boom:
            async def write_memory_async(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = await st.save_diary_entry("2026-06-20", "标题", "愉快", "正文", "0-15")
        assert "保存日记失败" in r["error"]


# ---------------------------------------------------------------- 会话消息
class TestSessionMessages:
    def test_no_context_manager(self, clean_deps):
        r = st.get_session_messages("s1")
        assert r == {"error": "上下文管理器不可用"}

    def test_success(self, clean_deps):
        cm = FakeContextManager([{"id": "m1", "role": "user", "content": "hi"}])
        _set_cm(cm)
        r = st.get_session_messages("s1", limit=10)
        assert r["status"] == "success"
        assert r["count"] == 1

    def test_exception(self, clean_deps):
        class Boom:
            def get_messages(self, session_id, limit):
                raise RuntimeError("boom")

        _set_cm(Boom())
        r = st.get_session_messages("s1")
        assert "获取会话消息失败" in r["error"]

    def test_clear_no_manager(self, clean_deps):
        r = st.clear_summary_context("s1")
        assert r == {"error": "上下文管理器不可用"}

    def test_clear_success(self, clean_deps):
        cm = FakeContextManager()
        _set_cm(cm)
        r = st.clear_summary_context("s1")
        assert r["status"] == "success"

    def test_clear_exception(self, clean_deps):
        class Boom:
            def clear_session_messages(self, session_id):
                raise RuntimeError("boom")

        _set_cm(Boom())
        r = st.clear_summary_context("s1")
        assert "清空上下文失败" in r["error"]


# ---------------------------------------------------------------- 话题摘要触发
class TestTriggerTopicSummary:
    @pytest.mark.asyncio
    async def test_no_context_manager(self, clean_deps):
        r = await st.trigger_topic_summary("s1")
        assert r == {"error": "上下文管理器不可用"}

    @pytest.mark.asyncio
    async def test_no_manager(self, clean_deps):
        _set_cm(FakeContextManager([{"id": "m1", "content": "x"}]))
        r = await st.trigger_topic_summary("s1")
        assert r == {"error": "记忆管理器未初始化"}

    @pytest.mark.asyncio
    async def test_no_messages(self, clean_deps):
        st.set_dependencies(
            context_manager=FakeContextManager([]), memory_manager=AsyncMemoryManager()
        )
        r = await st.trigger_topic_summary("s1")
        assert "没有可摘要的消息" in r["error"]

    @pytest.mark.asyncio
    async def test_no_new_messages(self, clean_deps):
        # 全部是话题摘要，没有新消息
        cm = FakeContextManager(
            [{"id": "m1", "content": "[话题摘要] 旧", "content_type": "topic_summary"}]
        )
        st.set_dependencies(context_manager=cm, memory_manager=AsyncMemoryManager())
        r = await st.trigger_topic_summary("s1")
        assert "当前话题没有新消息可摘要" in r["error"]

    @pytest.mark.asyncio
    async def test_no_summary_client(self, clean_deps):
        cm = FakeContextManager([{"id": "m1", "role": "user", "content": "你好"}])
        st.set_dependencies(context_manager=cm, memory_manager=AsyncMemoryManager())
        # model_router 置空 -> get_summary_client() 返回 None
        r = await st.trigger_topic_summary("s1")
        assert "摘要模型不可用" in r["error"]

    @pytest.mark.asyncio
    async def test_success(self, clean_deps):
        cm = FakeContextManager(
            [
                {"id": "m1", "role": "user", "content": "最近喜欢喝咖啡"},
                {"id": "m2", "role": "assistant", "content": "好的"},
            ]
        )
        mm = AsyncMemoryManager()
        st.set_dependencies(
            context_manager=cm,
            memory_manager=mm,
            model_router=FakeModelRouter(FakeSummaryClient(_Resp("用户喜欢喝咖啡"))),
        )
        r = await st.trigger_topic_summary("s1", topic="咖啡", end_signal="sig")
        assert r["status"] == "success"
        assert r["summary"] == "用户喜欢喝咖啡"
        assert r["summarized_messages"] == 2
        # 原消息被删除
        assert cm.deleted == ["m2", "m1"]
        # 摘要标记被加入
        assert cm.added[0][2].startswith("[话题摘要]")
        # 记忆被保存
        assert mm.writes[0]["memory_type"] == "conversation_summary"
        assert mm.writes[0]["metadata"]["topic"] == "咖啡"

    @pytest.mark.asyncio
    async def test_exception(self, clean_deps):
        class Boom:
            def get_messages(self, session_id, limit):
                raise RuntimeError("boom")

        st.set_dependencies(context_manager=Boom(), memory_manager=AsyncMemoryManager())
        r = await st.trigger_topic_summary("s1")
        assert "触发话题摘要失败" in r["error"]