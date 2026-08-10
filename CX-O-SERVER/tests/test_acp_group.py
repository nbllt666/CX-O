"""server.core.acp.group (ACPGroupManager) 单元测试。

用真实 ACPManager + tmp data_dir 隔离 YAML 持久化，覆盖群组门面的：
创建/读取/列表/更新/删除、加入/退出（含群主禁止退出、群满、重复加入）、
邀请权限、踢人（admin 校验、禁踢群主）、群广播、群消息读取、成员群组查询、状态。

运行：python -m pytest tests/test_acp_group.py -v
"""
import pytest

from server.core.acp.group import ACPGroupManager
from server.core.acp.manager import ACPManager


@pytest.mark.asyncio
async def _make(tmp_path):
    mgr = ACPManager(data_dir=str(tmp_path))
    gm = ACPGroupManager(mgr)
    return mgr, gm


def _agent(agent_id="a1", **kw):
    from server.core.acp.manager import ACPAgentInfo
    base = dict(id=agent_id, name=agent_id, host="", port=0, status="online")
    base.update(kw)
    return ACPAgentInfo(**base)


@pytest.mark.asyncio
async def test_create_group(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A", creator_id="c1", creator_name="创")
    assert g.name == "群A"
    assert g.creator_id == "c1"
    assert len(g.members) == 1
    assert g.members[0]["role"] == "admin"
    assert await mgr.get_group(g.id) is not None


@pytest.mark.asyncio
async def test_get_list_update_delete(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A")
    assert (await gm.get_group(g.id)).name == "群A"
    assert await gm.update_group(g.id, name="群B") is True
    assert (await gm.get_group(g.id)).name == "群B"
    assert len(await gm.list_groups()) == 1
    assert await gm.delete_group(g.id) is True
    assert await gm.get_group(g.id) is None


@pytest.mark.asyncio
async def test_join_group(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A")
    assert await gm.join_group(g.id, "a1", "甲") is True
    assert len((await mgr.get_group(g.id)).members) == 2
    # 重复加入返回 True 不重复添加
    assert await gm.join_group(g.id, "a1", "甲") is True
    assert len((await mgr.get_group(g.id)).members) == 2


@pytest.mark.asyncio
async def test_join_group_not_found_or_inactive(tmp_path):
    mgr, gm = await _make(tmp_path)
    assert await gm.join_group("ghost", "a1", "甲") is False
    g = await gm.create_group("群A")
    await mgr.update_group(g.id, is_active=False)
    assert await gm.join_group(g.id, "a1", "甲") is False


@pytest.mark.asyncio
async def test_join_group_full(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A", max_members=2)  # 群主 + 1
    assert await gm.join_group(g.id, "a1", "甲") is True
    assert await gm.join_group(g.id, "a2", "乙") is False  # 已满


@pytest.mark.asyncio
async def test_leave_group(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A", creator_id="c1")
    await mgr.register_agent(_agent("a1"))
    assert await gm.join_group(g.id, "a1", "甲") is True
    assert await gm.leave_group(g.id, "a1") is True
    assert len((await mgr.get_group(g.id)).members) == 1


@pytest.mark.asyncio
async def test_creator_cannot_leave(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A", creator_id="c1")
    assert await gm.leave_group(g.id, "c1") is False


@pytest.mark.asyncio
async def test_invite_member(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A", creator_id="c1")
    # 邀请者不在成员列表 -> False
    assert await gm.invite_member(g.id, "c1", "a1") is True
    assert await gm.invite_member(g.id, "ghost", "a1") is False


@pytest.mark.asyncio
async def test_kick_member(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A")
    await gm.join_group(g.id, "a1", "甲")
    # 非 admin 不能踢
    assert await gm.kick_member(g.id, "a1", "ghost") is False
    # admin（群主）踢普通成员
    assert await gm.kick_member(g.id, g.creator_id, "a1") is True
    assert len((await mgr.get_group(g.id)).members) == 1
    # 不能踢群主
    await gm.join_group(g.id, "a2", "乙")
    await gm.update_group(g.id, is_active=True)
    # 提升 a2 为 admin 后踢群主仍失败
    group = await mgr.get_group(g.id)
    group.members[1]["role"] = "admin"
    assert await gm.kick_member(g.id, "a2", g.creator_id) is False


@pytest.mark.asyncio
async def test_broadcast_to_group(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A")
    msg = await gm.broadcast_to_group(g.id, "a1", "甲", {"text": "大家好"})
    assert msg.msg_type == "group_message"
    assert msg.is_sent is True
    msgs = await gm.get_group_messages(g.id)
    assert len(msgs) == 1
    assert msgs[0]["content"] == {"text": "大家好"}


@pytest.mark.asyncio
async def test_broadcast_inactive_group_raises(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A")
    await mgr.update_group(g.id, is_active=False)
    with pytest.raises(ValueError):
        await gm.broadcast_to_group(g.id, "a1", "甲", {"text": "x"})


@pytest.mark.asyncio
async def test_get_member_groups(tmp_path):
    mgr, gm = await _make(tmp_path)
    g1 = await gm.create_group("群A")
    g2 = await gm.create_group("群B")
    await gm.join_group(g1.id, "a1", "甲")
    await gm.join_group(g2.id, "a1", "甲")
    groups = await gm.get_member_groups("a1")
    assert len(groups) == 2
    assert await gm.get_member_groups("ghost") == []


@pytest.mark.asyncio
async def test_event_broadcast_on_join(tmp_path):
    mgr, gm = await _make(tmp_path)
    g = await gm.create_group("群A")
    await gm.join_group(g.id, "a1", "甲")
    msgs = await gm.get_group_messages(g.id)
    # join 触发 control 事件消息（to_dict 映射 msg_type -> type）
    assert any(m["type"] == "control" for m in msgs)