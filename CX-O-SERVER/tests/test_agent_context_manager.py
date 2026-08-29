"""server.core.context.agent_context_manager 单元测试。

覆盖 AgentContextManager：save/load 持久化往返、append_message、get_message_history、
load_context limit 边界（0/超出）、clear_context、get_context_summary、update_last_active、
cleanup_old_messages（keep_count 0/超出）、损坏文件容错、线程安全单例。用 tmp_path 隔离。

运行：python -m pytest tests/test_agent_context_manager.py -v
"""
import json

import pytest

from server.core.context.agent_context_manager import (
    AgentContextData,
    AgentContextManager,
    get_agent_context_manager,
)


@pytest.fixture
def mgr(tmp_path):
    return AgentContextManager(str(tmp_path))


# ---------------------------------------------------------------- 保存/加载
def test_save_and_load_context(mgr):
    mgr.save_context(
        "a1",
        [{"role": "user", "content": "你好"}],
        memory_state={"mem": 1},
        session_id="s1",
    )
    ctx = mgr._get_or_load("a1")
    assert ctx.agent_id == "a1"
    assert ctx.session_id == "s1"
    assert ctx.memory_state == {"mem": 1}
    assert len(ctx.messages) == 1
    assert ctx.created_at is not None
    assert ctx.updated_at is not None


def test_save_persists_to_file(mgr):
    mgr.save_context("a1", [{"role": "user", "content": "hello"}])
    file_path = mgr._get_file_path("a1")
    assert file_path.exists()
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["agent_id"] == "a1"
    assert data["messages"][0]["content"] == "hello"


def test_load_context_returns_messages(mgr):
    mgr.save_context("a1", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])
    msgs = mgr.load_context("a1")
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "hi"}


def test_load_unexisting_agent_returns_empty(mgr):
    assert mgr.load_context("ghost") == []


def test_load_context_limit_zero(mgr):
    mgr.save_context("a1", [{"role": "user", "content": "x"}])
    assert mgr.load_context("a1", limit=0) == []


def test_load_context_limit_less_than_len(mgr):
    mgr.save_context("a1", [{"role": "user", "content": f"m{i}"} for i in range(5)])
    msgs = mgr.load_context("a1", limit=2)
    assert len(msgs) == 2
    assert msgs[-1]["content"] == "m4"


# ---------------------------------------------------------------- 追加
def test_append_message(mgr):
    mgr.append_message("a1", "user", "第一条")
    mgr.append_message("a1", "assistant", "第二条")
    hist = mgr.get_message_history("a1")
    assert len(hist) == 2
    assert hist[1]["role"] == "assistant"
    assert hist[1]["content"] == "第二条"
    assert "created_at" in hist[0]


def test_append_message_with_metadata(mgr):
    mgr.append_message("a1", "user", "带元数据", metadata={"k": "v"})
    hist = mgr.get_message_history("a1")
    assert hist[0]["metadata"] == {"k": "v"}


# ---------------------------------------------------------------- 历史查询
def test_get_message_history_limit(mgr):
    for i in range(10):
        mgr.append_message("a1", "user", f"m{i}")
    hist = mgr.get_message_history("a1", limit=3)
    assert len(hist) == 3
    assert hist[-1]["content"] == "m9"


def test_get_message_history_limit_zero(mgr):
    mgr.append_message("a1", "user", "x")
    assert mgr.get_message_history("a1", limit=0) == []


def test_get_message_history_unexisting(mgr):
    assert mgr.get_message_history("ghost") == []


# ---------------------------------------------------------------- 清空
def test_clear_context(mgr):
    mgr.save_context("a1", [{"role": "user", "content": "x"}])
    mgr.clear_context("a1")
    assert not mgr._get_file_path("a1").exists()
    assert mgr.load_context("a1") == []


def test_clear_unexisting_no_error(mgr):
    mgr.clear_context("ghost")  # 不应抛错


# ---------------------------------------------------------------- 摘要
def test_get_context_summary(mgr):
    mgr.append_message("a1", "user", "u1")
    mgr.append_message("a1", "assistant", "a1")
    summary = mgr.get_context_summary("a1")
    assert summary["agent_id"] == "a1"
    assert summary["has_context"] is True
    assert summary["total_messages"] == 2
    assert summary["role_counts"] == {"user": 1, "assistant": 1}


def test_get_context_summary_empty(mgr):
    summary = mgr.get_context_summary("ghost")
    assert summary["has_context"] is False
    assert summary["total_messages"] == 0


# ---------------------------------------------------------------- 活跃时间
def test_update_last_active_sets_timestamp(mgr):
    mgr.update_last_active("a1")
    ctx = mgr._get_or_load("a1")
    assert ctx.last_active is not None
    assert ctx.created_at is not None


# ---------------------------------------------------------------- 清理
def test_cleanup_old_messages_keep(mgr):
    for i in range(10):
        mgr.append_message("a1", "user", f"m{i}")
    mgr.cleanup_old_messages("a1", keep_count=3)
    hist = mgr.get_message_history("a1")
    assert len(hist) == 3
    assert hist[-1]["content"] == "m9"


def test_cleanup_old_messages_keep_zero(mgr):
    for i in range(3):
        mgr.append_message("a1", "user", f"m{i}")
    mgr.cleanup_old_messages("a1", keep_count=0)
    assert mgr.get_message_history("a1") == []


def test_cleanup_old_messages_no_trim_when_under(mgr):
    mgr.append_message("a1", "user", "only")
    mgr.cleanup_old_messages("a1", keep_count=100)
    assert len(mgr.get_message_history("a1")) == 1


# ---------------------------------------------------------------- 容错/单例
def test_corrupt_file_returns_none(mgr):
    file_path = mgr._get_file_path("a1")
    file_path.write_text("not json", encoding="utf-8")
    assert mgr._load_from_file("a1") is None


def test_no_cache_for_empty(mgr):
    mgr._get_or_load("ghost")
    assert "ghost" not in mgr._cache


def test_singleton_returns_same_instance():
    a = get_agent_context_manager()
    b = get_agent_context_manager()
    assert a is b


def test_agent_context_data_defaults():
    d = AgentContextData(agent_id="x")
    assert d.messages == []
    assert d.memory_state is None
    assert d.created_at is None


# ---------------------------------------------------------------- 原子写
def test_save_atomic_no_tmp_residue(mgr):
    """原子写：保存后目录内无 .tmp 残留，且内容完整可解析。"""
    mgr.save_context("a1", [{"role": "user", "content": "原子写"}])
    file_path = mgr._get_file_path("a1")
    assert file_path.exists()
    leftovers = [p.name for p in file_path.parent.iterdir() if p.name != file_path.name]
    assert leftovers == []
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["agent_id"] == "a1"
    assert data["messages"][0]["content"] == "原子写"


def test_save_atomic_crash_keeps_old_file(mgr, monkeypatch):
    """原子写中途失败（os.replace 抛错）：旧文件保持完整，目录无 .tmp 残留。"""
    import server.config as config_mod

    mgr.save_context("a1", [{"role": "user", "content": "v1"}])
    file_path = mgr._get_file_path("a1")

    def _boom(*args, **kwargs):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(config_mod.os, "replace", _boom)
    with pytest.raises(OSError):
        mgr.save_context("a1", [{"role": "user", "content": "v2"}])

    # 旧内容完整保留（未出现半写截断），finally 分支已清理临时文件
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data["messages"][0]["content"] == "v1"
    leftovers = [p.name for p in file_path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []