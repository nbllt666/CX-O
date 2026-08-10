"""server.core.decision.decision_core (DecisionCore) 单元测试。

构造隔离实例（tmp agents_file/log_dir + 显式 config + llm_available 注入），覆盖：
RubricSnapshot 模型、6 决策点（D1-D6）的 rubric 驱动分支与校验、
LLM 不可用回退 system_prompt 规则、LLM 可用路径、rubric 加载、
LLM 输出解析。

运行：python -m pytest tests/test_decision_core.py -v
"""
import json
from pathlib import Path

import pytest

from server.core.decision.decision_core import (
    DecisionCore,
    DecisionInput,
    RubricSnapshot,
    _default_rubric_dict,
)


def _make_core(tmp_path, monkeypatch, llm_available=False, agents=None, config=None):
    agents_file_path = tmp_path / "agents.json"
    if agents is not None:
        agents_file_path.write_text(json.dumps(agents, ensure_ascii=False), encoding="utf-8")
    agents_file = str(agents_file_path)
    cfg = {
        "decision_core": {"rejected_content_retention_days": 30},
        "vllm": {"base_url": "http://127.0.0.1:8002", "timeout_seconds": 5},
    }
    if config:
        cfg.update(config)
    return DecisionCore(
        config=cfg,
        agents_file=agents_file,
        log_dir=str(tmp_path / "logs"),
        llm_available=llm_available,
    )


def _rubric(**kw):
    base = _default_rubric_dict()
    base.update(kw)
    return RubricSnapshot(**base)


# ================================================================ 模型
class TestModels:
    def test_rubric_defaults(self):
        r = RubricSnapshot(
            importance_threshold_permanent=0.7,
            quality_reject_threshold=0.3,
            max_redistill_turns=2,
            ask_user_confidence_threshold=0.4,
        )
        assert r.cross_validate_sources == []
        assert r.importance_threshold_permanent == 0.7

    def test_decision_input_defaults(self):
        d = DecisionInput(session_state="S_INIT")
        assert d.quality_score is None
        assert d.artifact_summary is None


# ================================================================ D1 位置
class TestDecideLocation:
    def test_empty_session_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(KeyError):
            core.decide_location("", DecisionInput(session_state="S"), _rubric())

    def test_quality_score_out_of_range(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S", quality_score=1.5)
        with pytest.raises(ValueError):
            core.decide_location("s1", di, _rubric())

    def test_quality_below_threshold_rejects(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S", quality_score=0.1)
        dec = core.decide_location("s1", di, _rubric(quality_reject_threshold=0.3))
        assert dec.decision_point == "D1_LOCATION"
        assert dec.location == "rejected"
        assert dec.memory_id is None

    def test_importance_high_permanent(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        # llm_available=False → 回退 importance=_FALLBACK_IMPORTANCE(0.75)
        di = DecisionInput(session_state="S", quality_score=0.9)
        dec = core.decide_location("s1", di, _rubric(importance_threshold_permanent=0.7))
        assert dec.location == "permanent_memories"
        assert dec.memory_id is not None

    def test_importance_low_memories(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S", quality_score=0.9)
        dec = core.decide_location("s1", di, _rubric(importance_threshold_permanent=0.8))
        assert dec.location == "memories"
        assert dec.memory_id is not None

    def test_quality_score_defaults_to_082(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S")  # quality_score=None
        dec = core.decide_location("s1", di, _rubric(quality_reject_threshold=0.5))
        assert dec.quality_score == 0.82

    def test_llm_importance_used(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        core._llm_call = lambda prompt: "importance:0.9 confidence:0.95"
        di = DecisionInput(session_state="S", quality_score=0.9)
        dec = core.decide_location("s1", di, _rubric(importance_threshold_permanent=0.7))
        assert dec.location == "permanent_memories"
        assert dec.llm_confidence == 0.95

    def test_llm_importance_low(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        core._llm_call = lambda prompt: "importance:0.5 confidence:0.9"
        di = DecisionInput(session_state="S", quality_score=0.9)
        dec = core.decide_location("s1", di, _rubric(importance_threshold_permanent=0.7))
        assert dec.location == "memories"


# ================================================================ D2 元数据
class TestDecideMetadata:
    def test_fallback_metadata(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        md = core.decide_metadata("s1", DecisionInput(session_state="S", artifact_summary="摘要"))
        assert set(md) == {"time", "importance", "source", "tags"}
        assert md["source"] == "摘要"
        assert "fallback" in md["tags"]

    def test_empty_session_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(KeyError):
            core.decide_metadata("", DecisionInput(session_state="S"))

    def test_llm_metadata(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        core._llm_call = lambda prompt: '{"source": "视频", "tags": ["radix", "video"], "importance": 5}'
        md = core.decide_metadata("s1", DecisionInput(session_state="S", artifact_summary="备选"))
        assert md["source"] == "视频"
        assert md["tags"] == ["radix", "video"]
        assert md["importance"] == 5


# ================================================================ D3 追问
class TestDecideAskUser:
    def test_empty_session_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(KeyError):
            core.decide_ask_user("", 0.5, _rubric())

    def test_confidence_out_of_range(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            core.decide_ask_user("s1", 1.5, _rubric())

    def test_low_confidence_asks(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        assert core.decide_ask_user("s1", 0.2, _rubric(ask_user_confidence_threshold=0.4)) is True

    def test_high_confidence_no_ask(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        assert core.decide_ask_user("s1", 0.9, _rubric(ask_user_confidence_threshold=0.4)) is False


# ================================================================ D4 再次蒸馏
class TestDecideRedistill:
    def test_empty_session_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(KeyError):
            core.decide_redistill("", 1, _rubric())

    def test_negative_turn_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            core.decide_redistill("s1", -1, _rubric())

    def test_below_max_redistill(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        assert core.decide_redistill("s1", 1, _rubric(max_redistill_turns=2)) is True

    def test_at_max_no_redistill(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        assert core.decide_redistill("s1", 2, _rubric(max_redistill_turns=2)) is False


# ================================================================ D5 跨源验证
class TestDecideCrossValidate:
    def test_empty_session_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(KeyError):
            core.decide_cross_validate("", DecisionInput(session_state="S"), _rubric())

    def test_no_sources_false(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S", extracted_content="内容")
        assert core.decide_cross_validate("s1", di, _rubric(cross_validate_sources=[])) is False

    def test_sources_and_content_true(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S", extracted_content="内容")
        r = _rubric(cross_validate_sources=["baidu", "wiki"])
        assert core.decide_cross_validate("s1", di, r) is True

    def test_sources_but_no_content_false(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        di = DecisionInput(session_state="S")
        r = _rubric(cross_validate_sources=["wiki"])
        assert core.decide_cross_validate("s1", di, r) is False


# ================================================================ D6 拒绝
class TestDecideReject:
    def test_empty_session_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(KeyError):
            core.decide_reject("", 0.1, _rubric())

    def test_out_of_range_raises(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            core.decide_reject("s1", 1.5, _rubric())

    def test_reject_decision(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        dec = core.decide_reject("s1", 0.1, _rubric(quality_reject_threshold=0.3))
        assert dec.decision_point == "D6_REJECT"
        assert dec.location == "rejected"
        assert dec.memory_id is None
        assert dec.metadata["retention_days"] == 30


# ================================================================ rubric 加载
class TestLoadRubric:
    def test_missing_agents_file_uses_default(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch)
        r = core._load_rubric("any")
        assert r.importance_threshold_permanent == _default_rubric_dict()["importance_threshold_permanent"]

    def test_load_agent_rubric(self, tmp_path, monkeypatch):
        agents = {"agents": [{"agent_id": "a1", "decision_rubric": {
            "importance_threshold_permanent": 0.9,
            "quality_reject_threshold": 0.5,
            "max_redistill_turns": 2,
            "ask_user_confidence_threshold": 0.4,
        }}]}
        core = _make_core(tmp_path, monkeypatch, agents=agents)
        r = core._load_rubric("a1")
        assert r.importance_threshold_permanent == 0.9
        assert r.quality_reject_threshold == 0.5

    def test_missing_agent_raises(self, tmp_path, monkeypatch):
        agents = {"agents": [{"agent_id": "a1", "decision_rubric": {}}]}
        core = _make_core(tmp_path, monkeypatch, agents=agents)
        with pytest.raises(KeyError):
            core._load_rubric("ghost")


# ================================================================ LLM 输出解析
class TestParse:
    def test_parse_llm_output_plain(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        out = core._parse_llm_output("importance:0.6 confidence:0.85")
        assert out["importance"] == 0.6
        assert out["confidence"] == 0.85
        assert out["decision"] == "store"

    def test_parse_llm_output_markdown(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        out = core._parse_llm_output("importance:0.6 decision:reject confidence:0.85")
        assert out["importance"] == 0.6
        assert out["decision"] == "reject"

    def test_parse_metadata_output(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        out = core._parse_metadata_output('{"source": "x", "tags": ["a"], "importance": 2}')
        assert out["source"] == "x"
        assert out["importance"] == 2

    def test_parse_metadata_output_empty(self, tmp_path, monkeypatch):
        core = _make_core(tmp_path, monkeypatch, llm_available=True)
        out = core._parse_metadata_output("")
        assert out["importance"] > 0  # 默认值