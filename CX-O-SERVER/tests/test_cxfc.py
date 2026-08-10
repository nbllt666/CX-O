"""server.core.cxfc（SkillRegistry + CXFCStorage）单元测试。

覆盖：
- SkillRegistry：注册/按插件注销/关键词匹配（大小写不敏感）/事件匹配/全量列举/模板渲染。
- SkillDefinition 模型默认值。
- CXFCStorage：aiosqlite 临时库上的建表/保存/加载/删除/状态更新及 JSON 字段往返。

运行：python -m pytest tests/test_cxfc.py -v
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from server.core.cxfc.models import (
    CXFCPluginInfo,
    PluginStatus,
    SkillDefinition,
    CXFCEvent,
)
from server.core.cxfc.skill_registry import SkillRegistry
from server.core.cxfc.storage import CXFCStorage


def _skill(name, keywords, events, plugin="p1"):
    return SkillDefinition(
        name=name,
        source_plugin_id=plugin,
        trigger_keywords=keywords,
        trigger_events=events,
    )


# ================================================================ SkillRegistry
class TestSkillRegistry:
    def test_register_and_get_all(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", ["hello"], ["msg"]))
        assert len(reg.get_all_skills()) == 1

    def test_register_same_name_diff_plugin(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s", ["a"], [], plugin="p1"))
        reg.register_skill(_skill("s", ["b"], [], plugin="p2"))
        assert len(reg.get_all_skills()) == 2

    def test_unregister_skills_by_plugin(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", ["a"], [], plugin="p1"))
        reg.register_skill(_skill("s2", ["b"], [], plugin="p2"))
        reg.unregister_skills("p1")
        assert len(reg.get_all_skills()) == 1
        assert reg.get_all_skills()[0].name == "s2"

    def test_find_by_keywords_case_insensitive(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", ["Hello"], ["msg"]))
        reg.register_skill(_skill("s2", ["world"], ["msg"]))
        matched = reg.find_by_keywords("say HELLO now")
        assert [m.name for m in matched] == ["s1"]

    def test_find_by_keywords_multiple_match(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", ["hello"], ["m"]))
        reg.register_skill(_skill("s2", ["hello"], ["m"]))
        assert len(reg.find_by_keywords("hello")) == 2

    def test_find_by_keywords_no_match(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", ["hello"], ["m"]))
        assert reg.find_by_keywords("goodbye") == []

    def test_find_by_event(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", [], ["on_join"]))
        reg.register_skill(_skill("s2", [], ["on_leave"]))
        matched = reg.find_by_event("on_join")
        assert [m.name for m in matched] == ["s1"]

    def test_find_by_event_no_match(self):
        reg = SkillRegistry()
        reg.register_skill(_skill("s1", [], ["on_join"]))
        assert reg.find_by_event("none") == []

    def test_render_template(self):
        reg = SkillRegistry()
        out = reg.render_template("你好 {{name}}，今天 {{date}}", {"name": "小明", "date": "周一"})
        assert out == "你好 小明，今天 周一"

    def test_render_template_unknown_key_kept(self):
        reg = SkillRegistry()
        assert reg.render_template("{{a}} {{b}}", {"a": "x"}) == "x {{b}}"


class TestModels:
    def test_skill_defaults(self):
        s = SkillDefinition(name="s")
        assert s.description == ""
        assert s.trigger_keywords == []
        assert s.auto_inject is True
        assert s.source_plugin_id == ""

    def test_plugin_info_defaults(self):
        p = CXFCPluginInfo(plugin_id="id", host="h", port=1)
        assert p.status == PluginStatus.DISCONNECTED
        assert p.version == "1.0.0"
        assert p.capabilities == []
        assert p.last_seen is None

    def test_event_serializer(self):
        ts = datetime.now(timezone.utc)
        e = CXFCEvent(from_port=1, event_type="t", timestamp=ts)
        assert e.model_dump()["timestamp"] == ts.isoformat()


# ================================================================ CXFCStorage
@pytest_asyncio.fixture
async def storage(tmp_path):
    s = CXFCStorage(db_path=str(tmp_path / "cxfc.db"))
    await s.init_db()
    yield s
    await s.close()


def _plugin(pid, **kw):
    defaults = dict(plugin_id=pid, host="127.0.0.1", port=8000)
    defaults.update(kw)
    return CXFCPluginInfo(**defaults)


class TestStorage:
    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, storage):
        p = _plugin("p1", name="插件A", capabilities=["cap1"], skills=[{"name": "s"}],
                    tools=[{"name": "t"}])
        await storage.save_plugin(p)
        loaded = await storage.load_plugins()
        assert len(loaded) == 1
        assert loaded[0].plugin_id == "p1"
        assert loaded[0].name == "插件A"
        assert loaded[0].capabilities == ["cap1"]
        assert loaded[0].skills == [{"name": "s"}]

    @pytest.mark.asyncio
    async def test_save_upsert(self, storage):
        await storage.save_plugin(_plugin("p1", name="旧"))
        await storage.save_plugin(_plugin("p1", name="新"))
        loaded = await storage.load_plugins()
        assert len(loaded) == 1
        assert loaded[0].name == "新"

    @pytest.mark.asyncio
    async def test_status_and_last_seen_roundtrip(self, storage):
        ts = datetime(2026, 8, 7, 12, 0, 0)
        await storage.save_plugin(_plugin("p1", status=PluginStatus.CONNECTED, last_seen=ts))
        loaded = await storage.load_plugins()
        assert loaded[0].status == PluginStatus.CONNECTED
        assert loaded[0].last_seen == ts

    @pytest.mark.asyncio
    async def test_delete_plugin(self, storage):
        await storage.save_plugin(_plugin("p1"))
        await storage.save_plugin(_plugin("p2"))
        await storage.delete_plugin("p1")
        loaded = await storage.load_plugins()
        assert [p.plugin_id for p in loaded] == ["p2"]

    @pytest.mark.asyncio
    async def test_update_status(self, storage):
        await storage.save_plugin(_plugin("p1"))
        await storage.update_status("p1", PluginStatus.CONNECTED)
        loaded = await storage.load_plugins()
        assert loaded[0].status == PluginStatus.CONNECTED
        assert loaded[0].updated_at is not None

    @pytest.mark.asyncio
    async def test_load_empty(self, storage):
        assert await storage.load_plugins() == []

    @pytest.mark.asyncio
    async def test_close_sets_none(self, storage):
        await storage.close()
        assert storage._db is None