"""server.core.vision.narrative_memory (NarrativeVisionMemory) 单元测试。

用内存/真实 sqlite（tmp 临时库 + MemoryManager 单例）隔离验证：
- narrative_memory_enabled=False → sediment 返回 None 且不写入；
- D1 判定值得记（memories）→ 写入且 source 落列 'vision'（路径 A）；
- D1 判定拒绝 → written=False，写入 rejected_content；
- metadata 含 source/event_type/clip_ts/emotion/tags；
- 实体抽取在 graph 不可用/异常时静默降级，不阻断记忆写入。

运行：python -m pytest tests/test_narrative_memory.py -q
"""
import json

import pytest

from server.core.decision.decision_core import (
    DecisionCore,
    RubricSnapshot,
    _default_rubric_dict,
)
from server.core.memory.manager import MemoryManager
from server.core.vision.narrative_memory import NarrativeVisionMemory, VISION_SOURCE
from server.core.vision.video_understanding import NarrativeSummary


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """临时库 MemoryManager（禁用后台线程/高级组件），并重置单例。"""
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


def _rubric(**kw):
    base = _default_rubric_dict()
    base.update(kw)
    return RubricSnapshot(**base)


def _make_decision_core(tmp_path, llm_available=False):
    """构造隔离 DecisionCore（tmp agents/log，避免写入仓库 data 目录）。"""
    cfg = {
        "decision_core": {"rejected_content_retention_days": 30},
        "vllm": {"base_url": "http://127.0.0.1:8002", "timeout_seconds": 5},
    }
    return DecisionCore(
        config=cfg,
        agents_file=str(tmp_path / "agents.json"),
        log_dir=str(tmp_path / "logs"),
        llm_available=llm_available,
    )


def _camera_summary(content="用户点击了保存按钮", confidence=0.9) -> NarrativeSummary:
    return NarrativeSummary(
        content=content,
        events=["video_clip"],
        emotion="专注",
        clip_ts=12.5,
        source="screen",
        event_type="click_save",
        confidence=confidence,
        native_used=False,
        degraded=False,
    )


class TestSedimentGate:
    def test_disabled_returns_none_no_write(self, mgr, tmp_path):
        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(),
            enabled=False,
        )
        summary = _camera_summary()
        result = nvm.sediment(summary, "sess-1")
        assert result is None
        stats = mgr.get_statistics()
        assert stats["total"] == 0

    def test_empty_content_returns_none(self, mgr, tmp_path):
        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(),
            enabled=True,
        )
        result = nvm.sediment(_camera_summary(content="   "), "sess-1")
        assert result is None
        assert mgr.get_statistics()["total"] == 0


class TestSedimentWrite:
    def test_write_with_source_vision_column(self, mgr, tmp_path):
        # importance 回退 0.75；阈值 0.8 → 判定 memories
        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(importance_threshold_permanent=0.8),
            enabled=True,
        )
        result = nvm.sediment(_camera_summary(confidence=0.9), "sess-1")
        assert result is not None
        assert result["written"] is True
        assert result["location"] == "memories"
        assert result["memory_id"] is not None

        mem = mgr.get_memory(result["memory_id"])
        assert mem is not None
        # 路径 A：source 落 memories.source 列
        assert mem["source"] == VISION_SOURCE == "vision"
        # metadata 检索冗余字段
        md = mem["metadata"]
        assert md["source"] == "vision"
        assert md["event_type"] == "click_save"
        assert md["clip_ts"] == 12.5
        assert md["emotion"] == "专注"
        assert "visual" in md["tags"]
        assert "narrative" in md["tags"]
        assert "click_save" in md["tags"]
        # tags 列同步含视觉标签
        assert "visual" in mem["tags"]

    def test_decision_input_callback_custom(self, mgr, tmp_path):
        from server.core.decision.decision_core import DecisionInput

        def cb(narrative, session_id):
            return DecisionInput(
                session_state="S_CUSTOM",
                artifact_summary=narrative.content,
                extracted_content=narrative.content,
                quality_score=0.95,
            )

        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(importance_threshold_permanent=0.8),
            enabled=True,
        )
        result = nvm.sediment(_camera_summary(), "sess-x", decision_input_callback=cb)
        assert result is not None
        assert result["written"] is True


class TestRejected:
    def test_rejected_returns_written_false(self, mgr, tmp_path):
        # confidence 0.1 < quality_reject_threshold 0.5 → rejected
        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(quality_reject_threshold=0.5),
            enabled=True,
        )
        result = nvm.sediment(_camera_summary(confidence=0.1), "sess-r")
        assert result is not None
        assert result["written"] is False
        assert result["location"] == "rejected"
        assert result["memory_id"] is None
        assert result["rejected_id"] is not None
        # 主库未写入
        assert mgr.get_statistics()["total"] == 0
        # 被拒绝内容已入 rejected_content
        recs = mgr.get_rejected_content("sess-r")
        assert len(recs) == 1
        assert "vision" in json.dumps(recs[0].get("metadata", {}), ensure_ascii=False)


class TestEntityDegradation:
    def test_entity_linker_raises_does_not_block_write(self, mgr, tmp_path):
        def _boom(*args, **kwargs):
            raise RuntimeError("graph 不可用")

        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(importance_threshold_permanent=0.8),
            enabled=True,
            entity_linkers={"create_entity": _boom, "create_relation": _boom},
        )
        result = nvm.sediment(_camera_summary(), "sess-e")
        assert result is not None
        assert result["written"] is True
        assert result["memory_id"] is not None
        # 记忆已写入（实体入图异常被静默降级）
        assert mgr.get_memory(result["memory_id"]) is not None

    def test_no_linkers_skips_graph(self, mgr, tmp_path, monkeypatch):
        # 懒加载 graph_tools 失败（import 报错）→ 降级为空，不阻断
        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(importance_threshold_permanent=0.8),
            enabled=True,
        )
        result = nvm.sediment(_camera_summary(), "sess-g")
        assert result is not None
        assert result["written"] is True

    def test_extract_action_triples_basic(self):
        triples = NarrativeVisionMemory._extract_action_triples(
            _camera_summary(content="用户点击了保存按钮")
        )
        assert triples
        t = triples[0]
        assert t["action"] == "点击"
        assert "保存" in t["object"]


class TestConsumerWiring:
    def test_sediment_from_consumer(self, mgr, tmp_path):
        nvm = NarrativeVisionMemory(
            manager=mgr,
            decision_core=_make_decision_core(tmp_path),
            rubric=_rubric(importance_threshold_permanent=0.8),
            enabled=True,
        )
        item = {
            "clip_path": "/tmp/x.mp4",
            "event_meta": {"event_type": "click_save", "session_id": "sess-consumer"},
            "source": "screen",
            "ts": 1.5,
        }
        result = nvm.sediment_from_consumer(item, _camera_summary())
        assert result is not None
        assert result["written"] is True