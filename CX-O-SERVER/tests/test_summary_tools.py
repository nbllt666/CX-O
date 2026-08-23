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
        self._seq = 0

    def get_messages(self, session_id, limit):
        return self.messages

    def get_recent_messages(self, session_id, limit):
        return self.messages

    def clear_session_messages(self, session_id):
        del self.messages[:]

    def delete_message(self, msg_id):
        self.deleted.append(msg_id)

    def add_message(self, session_id, role, content, content_type="text", metadata=None):
        self._seq += 1
        msg_id = f"new-{self._seq}"
        self.messages.append(
            {
                "id": msg_id,
                "session_id": session_id,
                "role": role,
                "content": content,
                "content_type": content_type,
                "metadata": metadata or {},
            }
        )
        self.added.append((session_id, role, content, content_type))
        return msg_id

    def update_message(self, message_id, content=None, content_type=None, metadata=None):
        for m in self.messages:
            if m.get("id") == message_id:
                if content is not None:
                    m["content"] = content
                if content_type is not None:
                    m["content_type"] = content_type
                if metadata is not None:
                    m["metadata"] = metadata
                return True
        return False


class FakeModelRouter:
    def __init__(self, client=None):
        self.client = client or FakeSummaryClient()

    def get_client(self, name):
        return self.client if name == "summary" else None


class CapturingSummaryClient:
    """记录最后一次收到的 prompt，便于断言注入内容。"""

    def __init__(self, response=None):
        self.response = response or _Resp("摘要结果")
        self.last_prompt = None

    async def chat(self, messages, stream):
        self.last_prompt = messages[0]["content"]
        return self.response


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


# ---------------------------------------------------------------- 事件未完成状态
class TestTriggerUnfinishedStatus:
    @pytest.mark.asyncio
    async def test_auto_detect_unfinished(self, clean_deps):
        cm = FakeContextManager([{"id": "m1", "role": "user", "content": "确定了方案，记得待办"}])
        mm = AsyncMemoryManager()
        cap = CapturingSummaryClient(_Resp("本次确定了方案，仍有待办事项未完成"))
        st.set_dependencies(
            context_manager=cm, memory_manager=mm, model_router=FakeModelRouter(cap)
        )
        r = await st.trigger_topic_summary("s1", topic="方案")
        assert r["status"] == "success"
        marker = cm.messages[-1]
        # 自动判定为未完成 + 原文快照 + memory_id 落盘
        assert marker["metadata"]["status"] == "unfinished"
        assert marker["metadata"]["summary_id"] == marker["id"]
        assert marker["metadata"]["raw_messages"] == [
            {"role": "user", "content": "确定了方案，记得待办"}
        ]
        assert marker["metadata"]["memory_id"] is not None

    @pytest.mark.asyncio
    async def test_explicit_status(self, clean_deps):
        cm = FakeContextManager([{"id": "m1", "role": "user", "content": "ok"}])
        mm = AsyncMemoryManager()
        st.set_dependencies(
            context_manager=cm,
            memory_manager=mm,
            model_router=FakeModelRouter(FakeSummaryClient(_Resp("没有未完成"))),
        )
        await st.trigger_topic_summary("s1", status="completed")
        assert cm.messages[-1]["metadata"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_default_completed_when_no_indicator(self, clean_deps):
        cm = FakeContextManager([{"id": "m1", "role": "user", "content": "买咖啡"}])
        mm = AsyncMemoryManager()
        st.set_dependencies(
            context_manager=cm,
            memory_manager=mm,
            model_router=FakeModelRouter(FakeSummaryClient(_Resp("用户买了一杯咖啡"))),
        )
        await st.trigger_topic_summary("s1")
        assert cm.messages[-1]["metadata"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_inject_prior_unfinished(self, clean_deps):
        prior = {
            "id": "u1",
            "role": "topic_summary",
            "content": "[话题摘要] 讨论A，待办X未完成",
            "content_type": "topic_summary",
            "metadata": {"summary_id": "u1", "status": "unfinished"},
        }
        cm = FakeContextManager([prior, {"id": "m1", "role": "user", "content": "继续讨论"}])
        mm = AsyncMemoryManager()
        cap = CapturingSummaryClient(_Resp("延续了待办X"))
        st.set_dependencies(
            context_manager=cm, memory_manager=mm, model_router=FakeModelRouter(cap)
        )
        await st.trigger_topic_summary("s1")
        # 未完成旧摘要被注入摘要模型上下文
        assert "未完成议题" in cap.last_prompt
        assert "讨论A" in cap.last_prompt

    @pytest.mark.asyncio
    async def test_pruning_skips_unfinished(self, clean_deps):
        st.set_max_history_topics(1)
        try:
            completed = {
                "id": "c1",
                "role": "topic_summary",
                "content": "[话题摘要] 旧完成",
                "content_type": "topic_summary",
                "metadata": {"summary_id": "c1", "status": "completed"},
            }
            unfinished = {
                "id": "u1",
                "role": "topic_summary",
                "content": "[话题摘要] 未完成",
                "content_type": "topic_summary",
                "metadata": {"summary_id": "u1", "status": "unfinished"},
            }
            cm = FakeContextManager(
                [completed, unfinished, {"id": "m1", "role": "user", "content": "新话题"}]
            )
            mm = AsyncMemoryManager()
            st.set_dependencies(
                context_manager=cm,
                memory_manager=mm,
                model_router=FakeModelRouter(FakeSummaryClient(_Resp("新摘要"))),
            )
            await st.trigger_topic_summary("s1")
            # 完成摘要被清理、未完成摘要保留
            assert "c1" in cm.deleted
            assert "u1" not in cm.deleted
        finally:
            st.set_max_history_topics(None)


# ---------------------------------------------------------------- 摘要维护工具
class TestListTopicSummaries:
    def test_no_cm(self, clean_deps):
        r = st.list_topic_summaries("s1")
        assert r == {"error": "上下文管理器不可用"}

    def test_success(self, clean_deps):
        cm = FakeContextManager(
            [
                {
                    "id": "c1",
                    "role": "topic_summary",
                    "content": "[话题摘要] A",
                    "content_type": "topic_summary",
                    "metadata": {"summary_id": "c1", "status": "completed", "topic": "t1"},
                },
                {"id": "m1", "role": "user", "content": "x"},
            ]
        )
        _set_cm(cm)
        r = st.list_topic_summaries("s1")
        assert r["status"] == "success"
        assert r["count"] == 1
        assert r["summaries"][0]["summary_id"] == "c1"
        assert r["summaries"][0]["status"] == "completed"


class TestGetTopicSummaryRaw:
    def test_no_cm(self, clean_deps):
        assert st.get_topic_summary_raw("s1", "a") == {"error": "上下文管理器不可用"}

    def test_not_found(self, clean_deps):
        _set_cm(FakeContextManager([]))
        r = st.get_topic_summary_raw("s1", "none")
        assert "不存在" in r["error"]

    def test_success(self, clean_deps):
        cm = FakeContextManager(
            [
                {
                    "id": "c1",
                    "role": "topic_summary",
                    "content": "[话题摘要] A",
                    "content_type": "topic_summary",
                    "metadata": {
                        "summary_id": "c1",
                        "status": "unfinished",
                        "raw_messages": [{"role": "user", "content": "原始"}],
                        "memory_id": 5,
                    },
                }
            ]
        )
        _set_cm(cm)
        r = st.get_topic_summary_raw("s1", "c1")
        assert r["status"] == "success"
        assert r["raw_count"] == 1
        assert r["raw_messages"][0]["content"] == "原始"


class TestUpdateTopicSummary:
    def test_no_cm(self, clean_deps):
        assert st.update_topic_summary("s1", "a") == {"error": "上下文管理器不可用"}

    def test_not_found(self, clean_deps):
        _set_cm(FakeContextManager([]))
        r = st.update_topic_summary("s1", "none")
        assert "不存在" in r["error"]

    def test_invalid_status(self, clean_deps):
        cm = FakeContextManager(
            [
                {
                    "id": "c1",
                    "role": "topic_summary",
                    "content": "[话题摘要] A",
                    "content_type": "topic_summary",
                    "metadata": {"summary_id": "c1", "status": "unfinished", "memory_id": 5},
                }
            ]
        )
        _set_cm(cm)
        r = st.update_topic_summary("s1", "c1", status="bogus")
        assert "无效状态" in r["error"]
        assert cm.messages[0]["metadata"]["status"] == "unfinished"

    def test_update_content_and_status(self, clean_deps):
        cm = FakeContextManager(
            [
                {
                    "id": "c1",
                    "role": "topic_summary",
                    "content": "[话题摘要] A",
                    "content_type": "topic_summary",
                    "metadata": {"summary_id": "c1", "status": "unfinished", "memory_id": 5},
                }
            ]
        )
        _set_cm(cm)
        st.update_topic_summary("s1", "c1", new_content="已处理完", status="completed")
        m = cm.messages[0]
        assert m["content"] == "[话题摘要] 已处理完"
        assert m["metadata"]["status"] == "completed"
        assert m["metadata"]["summary"] == "已处理完"

    def test_sync_memory_update(self, clean_deps):
        class MM:
            def __init__(self):
                self.calls = []

            def update_memory(self, **kw):
                self.calls.append(kw)

        mm = MM()
        cm = FakeContextManager(
            [
                {
                    "id": "c1",
                    "role": "topic_summary",
                    "content": "[话题摘要] A",
                    "content_type": "topic_summary",
                    "metadata": {"summary_id": "c1", "status": "unfinished", "memory_id": 5},
                }
            ]
        )
        st.set_dependencies(memory_manager=mm, context_manager=cm)
        r = st.update_topic_summary("s1", "c1", status="completed")
        assert r["status"] == "success"
        assert mm.calls and mm.calls[0]["memory_id"] == 5