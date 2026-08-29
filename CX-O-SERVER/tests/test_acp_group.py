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


# ================================================================ 并发 join 上限（第十轮 TOCTOU 修复）
class TestConcurrentJoinMaxMembers:
    @pytest.mark.asyncio
    async def test_concurrent_join_respects_max_members(self, tmp_path):
        """N 个并发 join 对 max_members=2：最终成员数 ≤ 2（锁内复检兜底）。"""
        import asyncio

        mgr, gm = await _make(tmp_path)
        g = await gm.create_group("群A", max_members=2)  # 群主 + 1 个空位

        results = await asyncio.gather(
            *[gm.join_group(g.id, f"a{i}", f"成员{i}") for i in range(8)]
        )

        group = await mgr.get_group(g.id)
        # 核心断言：无论锁外预检还是锁内复检拦截，成员数绝不超过上限
        assert len(group.members) <= 2
        # 返回 True 的 join 数与实际新增成员数一致
        assert sum(1 for r in results if r) == len(group.members) - 1
        # 所有成功加入者确实在成员列表中
        joined = {f"a{i}" for i, r in enumerate(results) if r}
        in_group = {m["agent_id"] for m in group.members}
        assert joined <= in_group

    @pytest.mark.asyncio
    async def test_try_add_group_member_lock_recheck(self, tmp_path):
        """绕过 join_group 锁外预检、直接并发调用 try_add_group_member：
        锁内"活跃/上限/重复"复检保证幂等与上限不可突破。"""
        import asyncio

        mgr, gm = await _make(tmp_path)
        g = await gm.create_group("群B", max_members=3)  # 群主 + 2 个空位

        # 场景1：同一成员并发 join 5 次（幂等）——仅追加一次
        member = {"agent_id": "x1", "agent_name": "X1", "role": "member"}
        results = await asyncio.gather(
            *[mgr.try_add_group_member(g.id, dict(member), 3) for _ in range(5)]
        )
        assert all(results)  # 幂等语义：全部 True
        group = await mgr.get_group(g.id)
        assert len(group.members) == 2  # 群主 + 仅一个 x1

        # 场景2：6 个不同成员并发争抢最后 1 个空位——最多再进 1 人
        others = [
            {"agent_id": f"y{i}", "agent_name": f"Y{i}", "role": "member"}
            for i in range(6)
        ]
        results2 = await asyncio.gather(
            *[mgr.try_add_group_member(g.id, m, 3) for m in others]
        )
        group = await mgr.get_group(g.id)
        assert len(group.members) <= 3
        assert sum(1 for r in results2 if r) == len(group.members) - 2
        # 被拒绝者确实不在组内
        admitted = {m["agent_id"] for i, m in enumerate(others) if results2[i]}
        in_group = {m["agent_id"] for m in group.members}
        assert admitted <= in_group

    @pytest.mark.asyncio
    async def test_try_add_group_member_rejects_inactive_or_missing(self, tmp_path):
        """锁内复检同样拦截组不存在 / 组不活跃（与 join_group 对外行为一致）。"""
        mgr, gm = await _make(tmp_path)
        member = {"agent_id": "z1", "agent_name": "Z1", "role": "member"}

        # 组不存在
        assert await mgr.try_add_group_member("ghost", dict(member), 50) is False

        # 组不活跃
        g = await gm.create_group("群C", max_members=5)
        await mgr.update_group(g.id, is_active=False)
        assert await mgr.try_add_group_member(g.id, dict(member), 5) is False