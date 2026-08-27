"""server/autonomy/dream/consolidator.py（DreamConsolidator 固化/清除/提起）单测。

覆盖：
1. consolidate 正常路径：buffer→memories 字段断言（type/source/is_ground_truth/
   lucidity_score/关联素材/consolidation_state/importance_score）+ buffer 置 approved
2. consolidate 已决策（rejected/approved）返回 None；候选不存在返回 None
3. reject 不写主库：缓冲置 rejected + reason，主库 list_dreams 为空
4. surface 概率门（命中/未命中）、每日次数上限、sync/async ws_sender、
   无 ws_sender 仅日志、空缓冲、surface_on_wake 关闭、推送异常不抛错

运行：python -m pytest tests/test_dream_consolidator.py -q
"""
from types import SimpleNamespace

import pytest

from server.autonomy.dream import consolidator as consolidator_mod
from server.autonomy.dream.buffer import DreamBuffer
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.consolidator import DreamConsolidator
from server.core.memory.manager import MemoryManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """每个用例独立的临时数据库 MemoryManager（禁用后台线程）。"""
    monkeypatch.setattr(MemoryManager, "_start_cleanup_task", lambda self: None)

    def _noop_init(self):
        self.archiver = None
        self.deduplication_engine = None
        self.vectorization_queue = None

    monkeypatch.setattr(MemoryManager, "_init_advanced_components", _noop_init)
    MemoryManager._instance = None
    m = MemoryManager(db_path=str(tmp_path / "memories.db"))
    yield m
    m.shutdown()
    MemoryManager._instance = None


@pytest.fixture
def buf(tmp_path):
    """每个用例独立的临时缓冲 SQLite。"""
    return DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))


def _sample_candidate(**overrides):
    """构造一条梦境候选（对齐 buffer.put 契约字段）。"""
    candidate = {
        "dream_session_id": "sess-001",
        "agent_id": "default",
        "candidate_content": "梦见在海边捡到一颗会发光的石头",
        "associated_memories": [{"id": 1, "content": "昨天傍晚在海边散步"}],
        "associated_entities": ["海边", "石头"],
        "lucidity_score": 0.8,
        "emotion_shift": {"from": "平静", "to": "好奇"},
    }
    candidate.update(overrides)
    return candidate


def _make(buf, mgr, config=None, ws_sender=None):
    """构造 DreamConsolidator 实例。"""
    return DreamConsolidator(buf, mgr, config=config, ws_sender=ws_sender)


# ================================================================ consolidate
class TestConsolidate:
    def test_consolidate_writes_memory_and_marks_approved(self, buf, mgr):
        buffer_id = buf.put(_sample_candidate())
        c = _make(buf, mgr)

        memory_id = c.consolidate(buffer_id)
        assert isinstance(memory_id, int) and memory_id > 0

        # buffer 置 approved
        item = buf.get(buffer_id)
        assert item["decision"] == "approved"
        assert item["decision_reason"] == "user_confirmed"

        # 主库字段断言
        mem = mgr.get_memory(memory_id)
        assert mem["type"] == "dream"
        assert mem["source"] == "dream_engine"
        assert mem["importance_score"] == pytest.approx(DreamConfig().confirmed_importance)
        meta = mem["metadata"]
        assert meta["source"] == "dream_engine"
        assert meta["dream_session_id"] == "sess-001"
        assert meta["is_ground_truth"] is False
        assert meta["lucidity_score"] == 0.8
        assert meta["associated_memories"] == [{"id": 1, "content": "昨天傍晚在海边散步"}]
        assert meta["associated_entities"] == ["海边", "石头"]
        assert meta["consolidation_state"] == "confirmed"
        assert meta["confirmed_at"] is not None

    def test_consolidate_uses_configured_importance(self, buf, mgr):
        cfg = DreamConfig(confirmed_importance=0.6)
        buffer_id = buf.put(_sample_candidate())
        memory_id = DreamConsolidator(buf, mgr, config=cfg).consolidate(buffer_id)
        assert mgr.get_memory(memory_id)["importance_score"] == pytest.approx(0.6)

    def test_consolidate_agent_isolation(self, buf, mgr):
        """agent 隔离：写入按 agent 落独立表。

        M4 旧行为契约更新（20260827 第四轮）：_DreamMixin.consolidate_dream 无
        agent 维度（仅查默认 memories 表），非默认 agent 的固化提级此前恒为
        False 却被 consolidator 忽略并照常置 approved（谎报成功）。修复后
        提级未生效 → consolidate 返回 None、缓冲保持 pending 可重试；写入行
        仍按 agent 隔离落在 alice 独立表且 consolidation_state 保持 pending。
        """
        buffer_id = buf.put(_sample_candidate(agent_id="alice"))
        memory_id = DreamConsolidator(buf, mgr).consolidate(buffer_id, agent_id="alice")
        # 提级未生效 → 不再返回 memory_id 谎报完成
        assert memory_id is None
        # 缓冲保持 pending（可重试）
        assert buf.get(buffer_id)["decision"] == "pending"
        # 写入行确实按 agent 隔离落库，但状态未提级
        dreams = mgr.list_dreams(agent_id="alice")
        assert len(dreams) == 1
        assert dreams[0]["metadata"]["dream_session_id"] == "sess-001"
        assert dreams[0]["metadata"]["consolidation_state"] == "pending"

    def test_consolidate_already_approved_returns_none(self, buf, mgr):
        buffer_id = buf.put(_sample_candidate())
        c = _make(buf, mgr)
        assert c.consolidate(buffer_id) is not None
        # 二次固化不重复写库
        assert c.consolidate(buffer_id) is None
        assert len(mgr.list_dreams()) == 1

    def test_consolidate_rejected_returns_none(self, buf, mgr):
        buffer_id = buf.put(_sample_candidate())
        c = _make(buf, mgr)
        c.reject(buffer_id, reason="用户否定")
        assert c.consolidate(buffer_id) is None
        assert mgr.list_dreams() == []

    def test_consolidate_missing_returns_none(self, buf, mgr):
        assert _make(buf, mgr).consolidate(9999) is None

    def test_consolidate_promotion_failure_keeps_pending_and_returns_none(
        self, buf, mgr, monkeypatch
    ):
        """M4 定向: 提级失败（confirmed=False）→ 不置 approved、返回 None 供上层感知。"""
        buffer_id = buf.put(_sample_candidate())
        c = _make(buf, mgr)
        monkeypatch.setattr(
            mgr, "consolidate_dream",
            lambda memory_id, confirmed_importance=0.4: False,
        )
        assert c.consolidate(buffer_id) is None
        assert buf.get(buffer_id)["decision"] == "pending"


# ================================================================ reject
class TestReject:
    def test_reject_marks_buffer_without_main_db_write(self, buf, mgr):
        buffer_id = buf.put(_sample_candidate())
        c = _make(buf, mgr)

        assert c.reject(buffer_id, reason="用户否定该联想") is True

        item = buf.get(buffer_id)
        assert item["decision"] == "rejected"
        assert item["decision_reason"] == "用户否定该联想"
        # 不写主库
        assert mgr.list_dreams() == []

    def test_reject_empty_reason_default(self, buf, mgr):
        buffer_id = buf.put(_sample_candidate())
        assert _make(buf, mgr).reject(buffer_id) is True
        assert buf.get(buffer_id)["decision_reason"] == ""

    def test_reject_missing_returns_false(self, buf, mgr):
        assert _make(buf, mgr).reject(9999) is False

    def test_reject_twice_second_returns_false(self, buf, mgr):
        buffer_id = buf.put(_sample_candidate())
        c = _make(buf, mgr)
        assert c.reject(buffer_id) is True
        assert c.reject(buffer_id) is False


# ================================================================ surface
class TestSurface:
    @staticmethod
    def _force_random(monkeypatch, value):
        """将 consolidator 模块 random 替换为返回固定值的桩（0.0 必中 / 0.99 必不中）。"""
        monkeypatch.setattr(
            consolidator_mod, "random", SimpleNamespace(random=lambda: value)
        )

    @pytest.mark.asyncio
    async def test_surface_pushes_when_probability_hit(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())
        sent = []

        async def ws(message):
            sent.append(message)

        c = _make(buf, mgr, ws_sender=ws)
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is True
        assert len(sent) == 1
        msg = sent[0]
        assert msg["type"] == "dream.surface"
        assert msg["data"]["content"] == "梦见在海边捡到一颗会发光的石头"
        assert msg["data"]["dream_session_id"] == "sess-001"
        assert msg["data"]["agent_id"] == "default"

    @pytest.mark.asyncio
    async def test_surface_skips_when_probability_miss(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())
        sent = []

        async def ws(message):
            sent.append(message)

        c = _make(buf, mgr, ws_sender=ws)
        self._force_random(monkeypatch, 0.99)

        assert await c.surface() is False
        assert sent == []

    @pytest.mark.asyncio
    async def test_surface_daily_limit(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())
        cfg = DreamConfig(max_surface_per_day=1)
        sent = []

        async def ws(message):
            sent.append(message)

        c = _make(buf, mgr, config=cfg, ws_sender=ws)
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is True
        assert await c.surface() is False
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_surface_supports_sync_sender(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())
        sent = []
        c = _make(buf, mgr, ws_sender=lambda message: sent.append(message))
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is True
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_surface_without_sender_logs_and_counts(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())
        c = _make(buf, mgr)  # ws_sender=None → 仅日志，照常计数
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is True
        # 默认 max_surface_per_day=1，第二次触达次数上限
        assert await c.surface() is False

    @pytest.mark.asyncio
    async def test_surface_empty_buffer_returns_false(self, buf, mgr, monkeypatch):
        c = _make(buf, mgr)
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is False

    @pytest.mark.asyncio
    async def test_surface_surface_on_wake_disabled(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())
        c = _make(buf, mgr, config=DreamConfig(surface_on_wake=False))
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is False

    @pytest.mark.asyncio
    async def test_surface_sender_failure_returns_false(self, buf, mgr, monkeypatch):
        buf.put(_sample_candidate())

        async def bad(message):
            raise RuntimeError("推送失败")

        c = _make(buf, mgr, ws_sender=bad)
        self._force_random(monkeypatch, 0.0)

        assert await c.surface() is False
