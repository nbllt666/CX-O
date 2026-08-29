"""server.core.acp.manager (ACPManager) 单元测试。

用 tmp data_dir 隔离 YAML 持久化，monkeypatch 外部交付/存储实例隔离副作用，覆盖：
模型 to_dict 映射、初始化、Agent/连接/群组 CRUD、消息路由（群组/外部 HTTP/本地）、
统计、端口更新、per-agent 资源清理（per-agent SQLite graph 文件）。

运行：python -m pytest tests/test_acp_manager.py -v
"""
from datetime import datetime
from pathlib import Path

import pytest

from server.core.acp.manager import (
    ACPAgentInfo,
    ACPConnectionInfo,
    ACPGroupInfo,
    ACPManager,
    ACPMessageInfo,
)


def _make(data_dir):
    return ACPManager(data_dir=str(data_dir))


def _agent(agent_id="a1", **kw):
    base = dict(id=agent_id, name=agent_id, host="", port=0, status="online")
    base.update(kw)
    return ACPAgentInfo(**base)


def _conn(conn_id="c1", local_agent_id="local", **kw):
    base = dict(id=conn_id, local_agent_id=local_agent_id, status="connected")
    base.update(kw)
    return ACPConnectionInfo(**base)


def _group(group_id="g1", creator_id="local", **kw):
    base = dict(id=group_id, name=group_id, creator_id=creator_id)
    base.update(kw)
    return ACPGroupInfo(**base)


def _msg(msg_id="m1", to_agent_id="a1", to_group_id=None, **kw):
    base = dict(id=msg_id, from_agent_id="local", to_agent_id=to_agent_id, to_group_id=to_group_id)
    base.update(kw)
    return ACPMessageInfo(**base)


def _noop(*args, **kwargs):
    return None


async def _anoop(*args, **kwargs):
    return None


# ================================================================ 模型
class TestModels:
    def test_agent_to_dict(self):
        d = _agent(name="阿a", capabilities=["chat"]).to_dict()
        assert d["id"] == "a1"
        assert d["name"] == "阿a"
        assert d["capabilities"] == ["chat"]
        assert d["status"] == "online"

    def test_connection_to_dict(self):
        d = _conn(messages_sent=3).to_dict()
        assert d["id"] == "c1"
        assert d["local_agent_id"] == "local"
        assert d["messages_sent"] == 3

    def test_group_to_dict(self):
        d = _group(max_members=50).to_dict()
        assert d["id"] == "g1"
        assert d["max_members"] == 50
        assert d["is_active"] is True

    def test_message_to_dict_maps_msg_type(self):
        d = _msg(msg_type="group").to_dict()
        assert d["type"] == "group"  # msg_type -> type 映射
        assert "msg_type" not in d
        assert d["from_agent_id"] == "local"

    def test_message_defaults(self):
        m = ACPMessageInfo(id="x")
        d = m.to_dict()
        assert d["type"] == "chat"
        assert d["to_agent_id"] is None
        assert d["content"] == {}


# ================================================================ 初始化
class TestInit:
    def test_data_dir_created(self, tmp_path):
        d = tmp_path / "acp"
        _make(d)
        assert d.exists()

    def test_initialize_sets_local(self, tmp_path):
        mgr = _make(tmp_path)
        mgr.initialize("sys", "系统")
        assert mgr._local_agent_id == "sys"
        assert mgr._local_agent_name == "系统"

    def test_local_http_port_property(self, tmp_path):
        mgr = _make(tmp_path)
        assert mgr.local_http_port == mgr._local_http_port

    def test_load_data_empty(self, tmp_path):
        mgr = _make(tmp_path)
        assert mgr.agents == {}
        assert mgr.connections == {}
        assert mgr.groups == {}


# ================================================================ Agent CRUD
class TestAgentCRUD:
    @pytest.mark.asyncio
    async def test_register_and_get(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent())
        got = await mgr.get_agent("a1")
        assert got is not None
        assert got.id == "a1"
        assert got.last_seen  # register 更新 last_seen

    @pytest.mark.asyncio
    async def test_update_status(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent())
        assert await mgr.update_agent_status("a1", "offline") is True
        assert (await mgr.get_agent("a1")).status == "offline"
        assert await mgr.update_agent_status("ghost", "offline") is False

    @pytest.mark.asyncio
    async def test_list_agents_online_only(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent("a1", status="online"))
        await mgr.register_agent(_agent("a2", status="offline"))
        all_a = await mgr.list_agents()
        online = await mgr.list_agents(online_only=True)
        assert len(all_a) == 2
        assert [a["id"] for a in online] == ["a1"]

    @pytest.mark.asyncio
    async def test_update_agent(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent())
        assert await mgr.update_agent(
            "a1", name="新名", description="desc", capabilities=["tool"], status="active"
        ) is True
        got = await mgr.get_agent("a1")
        assert got.name == "新名"
        assert got.metadata["description"] == "desc"
        assert got.capabilities == ["tool"]
        assert got.status == "online"  # active -> online
        assert await mgr.update_agent("ghost") is False

    @pytest.mark.asyncio
    async def test_remove_agent(self, tmp_path, monkeypatch):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent("a1"))
        monkeypatch.setattr(mgr, "cleanup_agent_resources", _noop)
        assert await mgr.remove_agent("a1") is True
        assert await mgr.get_agent("a1") is None
        assert await mgr.remove_agent("a1") is False

    @pytest.mark.asyncio
    async def test_remove_agent_cleans_group_members(self, tmp_path, monkeypatch):
        """M-E 定向: 删除 agent 同步清除群组成员引用并落盘（此前残留孤儿成员）。"""
        mgr = _make(tmp_path)
        monkeypatch.setattr(mgr, "cleanup_agent_resources", _noop)
        await mgr.register_agent(_agent("a1"))
        g = _group()
        await mgr.create_group(g)
        await mgr.add_group_member("g1", {"agent_id": "a1", "name": "a1"})
        await mgr.add_group_member("g1", {"agent_id": "a2", "name": "a2"})

        # 追加一个不受删除影响的第二群组
        g2 = _group(group_id="g2")
        await mgr.create_group(g2)
        await mgr.add_group_member("g2", {"agent_id": "a2"})

        saved_after = {"n": 0}
        orig_save = mgr._save_data

        async def spy_save():
            saved_after["n"] += 1
            return await orig_save()

        monkeypatch.setattr(mgr, "_save_data", spy_save)
        assert await mgr.remove_agent("a1") is True

        group = await mgr.get_group("g1")
        member_ids = [m.get("agent_id") for m in group.members]
        assert "a1" not in member_ids
        assert "a2" in member_ids
        group2 = await mgr.get_group("g2")
        assert [m.get("agent_id") for m in group2.members] == ["a2"]
        # 清理动作伴随一次落盘（remove_agent 内 _save_data）
        assert saved_after["n"] >= 1


# ================================================================ 消息历史上限
class TestMessageCap:
    @pytest.mark.asyncio
    async def test_send_message_capped_per_key(self, tmp_path, monkeypatch):
        """M-E 定向: 单 key 消息历史超上限从头部截断（防无界增长）。"""
        mgr = _make(tmp_path)
        monkeypatch.setattr(ACPManager, "MAX_MESSAGES_PER_KEY", 5)

        for i in range(8):
            await mgr.send_message(_msg(msg_id=f"m{i}", to_agent_id="a1"))

        bucket = mgr.messages["a1"]
        assert len(bucket) == 5
        # 最旧的 m0/m1/m2 被丢弃，保留最近 5 条
        assert [m.id for m in bucket] == ["m3", "m4", "m5", "m6", "m7"]

    @pytest.mark.asyncio
    async def test_group_message_capped_per_key(self, tmp_path, monkeypatch):
        mgr = _make(tmp_path)
        monkeypatch.setattr(ACPManager, "MAX_MESSAGES_PER_KEY", 4)

        for i in range(6):
            await mgr.send_message(
                _msg(msg_id=f"g{i}", to_agent_id=None, to_group_id="g1")
            )

        bucket = mgr.messages["g1"]
        assert len(bucket) == 4
        assert [m.id for m in bucket] == ["g2", "g3", "g4", "g5"]

    @pytest.mark.asyncio
    async def test_receive_external_message_capped(self, tmp_path, monkeypatch):
        mgr = _make(tmp_path)
        monkeypatch.setattr(ACPManager, "MAX_MESSAGES_PER_KEY", 3)
        monkeypatch.setattr(mgr, "_inject_into_chat_context", _anoop)

        async def _no_reply(*args, **kwargs):
            return None

        # _trigger_auto_reply 由 create_task 发起——替换为 no-op 防外部依赖
        monkeypatch.setattr(mgr, "_trigger_auto_reply", _no_reply)

        for i in range(5):
            incoming = ACPMessageInfo(id=f"in{i}", from_agent_id="peer", msg_type="chat")
            await mgr.receive_external_message(incoming)

        bucket = mgr.messages["peer"]
        assert len(bucket) == 3
        assert [m.id for m in bucket] == ["in2", "in3", "in4"]


# ================================================================ Connection CRUD
class TestConnectionCRUD:
    @pytest.mark.asyncio
    async def test_create_get(self, tmp_path):
        mgr = _make(tmp_path)
        mgr.initialize("local", "本地")
        await mgr.create_connection(_conn())
        got = await mgr.get_connection("c1")
        assert got is not None
        assert got.status == "connected"

    @pytest.mark.asyncio
    async def test_list_local_only(self, tmp_path):
        mgr = _make(tmp_path)
        mgr.initialize("local", "本地")
        await mgr.create_connection(_conn("c1", local_agent_id="local"))
        await mgr.create_connection(_conn("c2", local_agent_id="other"))
        local = await mgr.list_connections(local_only=True)
        all_c = await mgr.list_connections(local_only=False)
        assert [c["id"] for c in local] == ["c1"]
        assert len(all_c) == 2

    @pytest.mark.asyncio
    async def test_update_connection(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_connection(_conn())
        assert await mgr.update_connection("c1", status="disconnected") is True
        assert (await mgr.get_connection("c1")).status == "disconnected"
        # 未知字段被忽略，仍返回 True
        assert await mgr.update_connection("c1", nonexistent=1) is True
        assert await mgr.update_connection("ghost", status="x") is False

    @pytest.mark.asyncio
    async def test_delete_connection(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_connection(_conn())
        assert await mgr.delete_connection("c1") is True
        assert await mgr.get_connection("c1") is None
        assert await mgr.delete_connection("c1") is False


# ================================================================ Group CRUD
class TestGroupCRUD:
    @pytest.mark.asyncio
    async def test_create_get(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_group(_group())
        got = await mgr.get_group("g1")
        assert got is not None
        assert got.name == "g1"
        assert "g1" in mgr.messages  # create_group 初始化消息槽

    @pytest.mark.asyncio
    async def test_list_groups(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_group(_group("g1"))
        await mgr.create_group(_group("g2"))
        assert len(await mgr.list_groups()) == 2

    @pytest.mark.asyncio
    async def test_update_group(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_group(_group())
        assert await mgr.update_group("g1", name="新群") is True
        assert (await mgr.get_group("g1")).name == "新群"
        assert (await mgr.get_group("g1")).updated_at  # update 设 updated_at
        assert await mgr.update_group("ghost", name="x") is False

    @pytest.mark.asyncio
    async def test_delete_group_removes_messages(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_group(_group("g1"))
        await mgr.send_message(_msg("m1", to_group_id="g1"))
        assert "g1" in mgr.messages
        assert await mgr.delete_group("g1") is True
        assert "g1" not in mgr.messages
        assert await mgr.delete_group("g1") is False

    @pytest.mark.asyncio
    async def test_add_remove_member(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_group(_group())
        assert await mgr.add_group_member("g1", {"agent_id": "a1", "name": "A"}) is True
        assert len((await mgr.get_group("g1")).members) == 1
        assert await mgr.remove_group_member("g1", "a1") is True
        assert len((await mgr.get_group("g1")).members) == 0
        assert await mgr.add_group_member("ghost", {"agent_id": "a1"}) is False


# ================================================================ 消息
class TestMessage:
    @pytest.mark.asyncio
    async def test_send_to_group(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.create_group(_group("g1"))
        await mgr.send_message(_msg("m1", to_group_id="g1", content={"text": "hi"}))
        msgs = await mgr.get_messages("g1")
        assert len(msgs) == 1
        assert msgs[0]["from_agent_id"] == "local"

    @pytest.mark.asyncio
    async def test_send_to_agent_stores(self, tmp_path, monkeypatch):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent("a1", port=9999))  # 9999 跳过外部投递
        monkeypatch.setattr(mgr, "_deliver_to_external_agent", _anoop)
        monkeypatch.setattr(mgr, "_deliver_to_local_agent", _anoop)
        await mgr.send_message(_msg("m1", to_agent_id="a1"))
        msgs = await mgr.get_messages("a1")
        assert len(msgs) == 1

    @pytest.mark.asyncio
    async def test_send_lazy_creates_msg_slot(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.send_message(_msg("m1", to_agent_id="a1"))
        assert "a1" in mgr.messages

    @pytest.mark.asyncio
    async def test_get_messages_limit_unread(self, tmp_path):
        mgr = _make(tmp_path)
        for i in range(5):
            await mgr.send_message(_msg(f"m{i}", to_agent_id="a1"))
        assert len(await mgr.get_messages("a1")) == 5
        assert len(await mgr.get_messages("a1", limit=2)) == 2
        assert len(await mgr.get_messages("a1", unread_only=True)) == 5

    @pytest.mark.asyncio
    async def test_mark_messages_read(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.send_message(_msg("m1", to_agent_id="a1"))
        await mgr.send_message(_msg("m2", to_agent_id="a1"))
        marked = await mgr.mark_messages_read(["m1", "m2"])
        assert marked == 2
        assert len(await mgr.get_messages("a1", unread_only=True)) == 0
        # 已读消息再次标记不计数
        assert await mgr.mark_messages_read(["m1"]) == 0

    @pytest.mark.asyncio
    async def test_receive_external_message_stores(self, tmp_path, monkeypatch):
        mgr = _make(tmp_path)
        monkeypatch.setattr(mgr, "_inject_into_chat_context", _anoop)
        monkeypatch.setattr(mgr, "_trigger_auto_reply", _anoop)
        msg = await mgr.receive_external_message(_msg("ext1", from_agent_id="remote"))
        assert msg.id == "ext1"
        msgs = await mgr.get_messages("remote")
        assert len(msgs) == 1
        assert msgs[0]["id"] == "ext1"

    @pytest.mark.asyncio
    async def test_inject_into_chat_context_writes_to_context_manager(self, tmp_path, monkeypatch):
        """回归：ACP 消息注入必须真正写入 ContextManager 的 session。

        曾因误调用不存在的 add_message_async 被 except AttributeError 吞掉而静默失效，
        现改用同步 add_message 后应实际落库。
        """
        from server.core.context.manager import ContextManager

        cm = ContextManager(db_path=str(tmp_path / "sessions.db"))
        monkeypatch.setattr("server.dependencies.get_context_manager", lambda: cm)
        mgr = _make(tmp_path / "acp")
        mgr.initialize("sys", "系统")

        await mgr._inject_into_chat_context(
            _msg("m1", from_agent_id="remote", content={"text": "你好"}),
            target_agent_id="a1",
        )

        msgs = cm.get_messages("agent-a1")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "[ACP 消息]" in msgs[0]["content"]
        assert "你好" in msgs[0]["content"]
        cm.shutdown()


# ================================================================ 统计
class TestStatistics:
    @pytest.mark.asyncio
    async def test_get_statistics(self, tmp_path):
        mgr = _make(tmp_path)
        mgr.initialize("sys", "系统")
        await mgr.register_agent(_agent("a1", status="online"))
        await mgr.register_agent(_agent("a2", status="offline"))
        await mgr.create_connection(_conn("c1", local_agent_id="sys"))
        await mgr.create_group(_group("g1"))
        await mgr.send_message(_msg("m1", to_agent_id="a1"))
        stats = await mgr.get_statistics()
        assert stats["total_agents"] == 2
        assert stats["online_agents"] == 1
        assert stats["total_connections"] == 1
        assert stats["active_connections"] == 1
        assert stats["total_groups"] == 1
        assert stats["total_messages"] == 1
        assert stats["unread_messages"] == 1
        assert stats["local_agent_id"] == "sys"
        assert stats["local_agent_name"] == "系统"


# ================================================================ 端口
class TestAgentPort:
    @pytest.mark.asyncio
    async def test_update_valid(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent("a1", port=0))
        assert await mgr.update_agent_port("a1", 8081) is True
        assert (await mgr.get_agent("a1")).port == 8081

    @pytest.mark.asyncio
    async def test_update_invalid_port(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent("a1"))
        assert await mgr.update_agent_port("a1", 0) is False
        assert await mgr.update_agent_port("a1", -1) is False
        assert await mgr.update_agent_port("a1", 70000) is False
        assert await mgr.update_agent_port("a1", "8000") is False  # 非 int

    @pytest.mark.asyncio
    async def test_update_missing_agent(self, tmp_path):
        mgr = _make(tmp_path)
        assert await mgr.update_agent_port("ghost", 8081) is False


# ================================================================ per-agent 资源
class TestResources:
    @pytest.mark.asyncio
    async def test_cleanup_default_skips(self, tmp_path):
        # default 走共享资源跳过分支：不清理共享 collection/文件，直接返回 True
        mgr = _make(tmp_path)
        assert await mgr.cleanup_agent_resources("default") is True

    @pytest.mark.asyncio
    async def test_cleanup_removes_graph_files(self, tmp_path):
        # 非 default agent：清理 per-agent graph 文件及 -wal/-shm 侧车（前缀重定向到 tmp 隔离）
        mgr = _make(tmp_path)
        mgr.PER_AGENT_GRAPH_PREFIX = str(tmp_path / "graph_")
        graph_path = Path(f"{mgr.PER_AGENT_GRAPH_PREFIX}a1.db")
        graph_path.write_bytes(b"x")
        Path(f"{graph_path}-wal").write_bytes(b"w")
        Path(f"{graph_path}-shm").write_bytes(b"s")
        assert await mgr.cleanup_agent_resources("a1") is True
        assert not graph_path.exists()
        assert not Path(f"{graph_path}-wal").exists()
        assert not Path(f"{graph_path}-shm").exists()


# ================================================================ 持久化
class TestPersistence:
    @pytest.mark.asyncio
    async def test_register_persists_and_reloads(self, tmp_path):
        mgr = _make(tmp_path)
        await mgr.register_agent(_agent("a1", name="阿a"))
        mgr2 = _make(tmp_path)
        got = await mgr2.get_agent("a1")
        assert got is not None
        assert got.name == "阿a"

    @pytest.mark.asyncio
    async def test_local_source_not_persisted(self, tmp_path):
        mgr = _make(tmp_path)
        # source 属于 LOCAL_AGENT_SOURCES 的 agent 不落盘
        await mgr.register_agent(_agent("a1", metadata={"source": "cxo_local"}))
        mgr2 = _make(tmp_path)
        assert await mgr2.get_agent("a1") is None

    @pytest.mark.asyncio
    async def test_connection_group_persist(self, tmp_path):
        mgr = _make(tmp_path)
        mgr.initialize("local", "本地")
        await mgr.create_connection(_conn())
        await mgr.create_group(_group())
        mgr2 = _make(tmp_path)
        assert await mgr2.get_connection("c1") is not None
        assert await mgr2.get_group("g1") is not None