"""
server/core/distillation/distillation_service.py 单元测试
聚焦纯辅助方法（状态机、路径解析、rubric/decision 构造、质量评分、
内容切分、元数据、决策日志、session 持久化），注入假子系统隔离重依赖。
"""
import json
import os

import pytest

from server.core.distillation.distillation_service import (
    DistillationService,
    _iso_now,
    _new_uuid,
    _ensure_dir,
)


class FakePipeline:
    async def preprocess(self, source_type, source_ref):
        return {"source_type": source_type, "source_ref": source_ref}


class SimpleBox:
    """RubricSnapshot / DecisionInput 的假实现。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return dict(self.__dict__)


@pytest.fixture
def service(tmp_path):
    """构造注入假子系统的 DistillationService，避免加载真实 MultimodalPipeline/DecisionCore。"""
    cfg = {
        "session_storage_dir": str(tmp_path / "sessions"),
        "log_storage_dir": str(tmp_path / "logs"),
        "quality_llm_enabled": False,  # 跳过 LLM 质量评估
        "quality_llm_model": "",
        "quality_llm_timeout_seconds": 5,
    }
    svc = DistillationService(
        config=cfg,
        multimodal_pipeline=FakePipeline(),
        decision_core=None,
    )
    # 注入假数据模型类（rubric/decision input），覆盖类构造路径
    svc._rubric_cls = SimpleBox
    svc._decision_input_cls = SimpleBox
    return svc


# --------------------------------------------------------------------------- #
# 模块级工具函数
# --------------------------------------------------------------------------- #
class TestModuleUtils:
    def test_iso_now(self):
        s = _iso_now()
        assert isinstance(s, str) and len(s) >= 19

    def test_new_uuid(self):
        u1 = _new_uuid()
        u2 = _new_uuid()
        assert u1 != u2
        assert isinstance(u1, str)

    def test_ensure_dir(self, tmp_path):
        d = tmp_path / "a" / "b"
        _ensure_dir(str(d))
        assert d.is_dir()
        # 已存在不报错
        _ensure_dir(str(d))


# --------------------------------------------------------------------------- #
# 状态机 _transition_state
# --------------------------------------------------------------------------- #
class TestTransitionState:
    @pytest.mark.parametrize(
        "current,action,expected",
        [
            ("S_INIT", "proceed", "S_PREREAD"),
            ("S_PREREAD", "ask_user", "S_QUESTION"),
            ("S_QUESTION", "proceed", "S_REFLECT"),
            ("S_REFLECT", "reflect", "S_QUESTION"),
            ("S_CROSSVALIDATE", "cross_validate", "S_EXTRACT"),
            ("S_EXTRACT", "extract", "S_STORAGE_DECISION"),
            ("S_STORAGE_DECISION", "reject", "S_REJECT"),
            ("S_STORAGE_DECISION", "decide", "S_FINALIZE"),
        ],
    )
    def test_valid(self, service, current, action, expected):
        assert service._transition_state(current, action) == expected

    def test_invalid_state(self, service):
        with pytest.raises(ValueError, match="非法状态"):
            service._transition_state("S_BOGUS", "proceed")

    def test_invalid_action(self, service):
        with pytest.raises(ValueError, match="非法 agent_action"):
            service._transition_state("S_INIT", "bogus")

    def test_illegal_transition(self, service):
        with pytest.raises(ValueError, match="非法状态转移"):
            service._transition_state("S_INIT", "reject")


# --------------------------------------------------------------------------- #
# 路径解析 _resolve_path
# --------------------------------------------------------------------------- #
class TestResolvePath:
    def test_absolute_unchanged(self, service):
        assert service._resolve_path("C:/abs/path") == "C:/abs/path"

    def test_relative_joins_project_root(self, service):
        import server.core.distillation.distillation_service as mod

        out = service._resolve_path("data/x/sessions")
        assert out == os.path.join(mod._PROJECT_ROOT, "data", "x", "sessions")

    def test_relative_with_forward_slashes(self, service):
        import server.core.distillation.distillation_service as mod

        out = service._resolve_path("data/x")
        assert out == os.path.join(mod._PROJECT_ROOT, "data", "x")


# --------------------------------------------------------------------------- #
# rubric / decision 构造
# --------------------------------------------------------------------------- #
class TestRubricDecision:
    def test_build_default_rubric(self, service):
        service._decision_core_config = {
            "importance_threshold_permanent": 0.8,
            "quality_reject_threshold": 0.2,
            "max_redistill_turns": 3,
            "ask_user_confidence_threshold": 0.5,
            "cross_validate_sources": ["a", "b"],
        }
        r = service._build_default_rubric()
        assert r["importance_threshold_permanent"] == 0.8
        assert r["quality_reject_threshold"] == 0.2
        assert r["max_redistill_turns"] == 3
        assert r["cross_validate_sources"] == ["a", "b"]

    def test_build_default_rubric_missing_keys(self, service):
        service._decision_core_config = {}
        r = service._build_default_rubric()
        assert r["importance_threshold_permanent"] == 0.7
        assert r["quality_reject_threshold"] == 0.3
        assert r["max_redistill_turns"] == 2

    def test_build_rubric_snapshot_class(self, service):
        service._rubric = {
            "importance_threshold_permanent": 0.7,
            "quality_reject_threshold": 0.3,
            "max_redistill_turns": 2,
            "ask_user_confidence_threshold": 0.4,
            "cross_validate_sources": [],
        }
        snap = service._build_rubric_snapshot()
        assert isinstance(snap, SimpleBox)
        assert snap.importance_threshold_permanent == 0.7

    def test_build_rubric_snapshot_dict_fallback(self, service):
        service._rubric = {"importance_threshold_permanent": 0.7}
        service._rubric_cls = None
        assert service._build_rubric_snapshot() == {"importance_threshold_permanent": 0.7}

    def test_build_decision_input_class(self, service):
        session = {
            "preread_summary": "pre",
            "state": "S_QUESTION",
            "turns": [{"agent_action": "reflect"}, {"agent_action": "ask_user"}],
            "extracted_content": "ext",
        }
        di = service._build_decision_input(session, 0.8)
        assert isinstance(di, SimpleBox)
        assert di.quality_score == 0.8
        assert di.session_state == "S_QUESTION"
        assert "reflect" in di.turn_history_summary

    def test_build_decision_input_dict_fallback(self, service):
        service._decision_input_cls = None
        session = {"preread_summary": None, "state": "S_INIT", "turns": [], "extracted_content": None}
        di = service._build_decision_input(session, None)
        assert isinstance(di, dict)
        assert di["session_state"] == "S_INIT"


# --------------------------------------------------------------------------- #
# 质量评分 / 回环计数 / 内容抽取
# --------------------------------------------------------------------------- #
class TestQuality:
    def test_count_redistill_turns(self, service):
        session = {
            "turns": [
                {"state": "S_QUESTION", "agent_action": "reflect"},
                {"state": "S_QUESTION", "agent_action": "reflect"},
                {"state": "S_REFLECT", "agent_action": "reflect"},
                {"state": "S_QUESTION", "agent_action": "ask_user"},
            ]
        }
        assert service._count_redistill_turns(session) == 2

    def test_count_redistill_turns_empty(self, service):
        assert service._count_redistill_turns({"turns": []}) == 0

    def test_extract_content(self, service):
        session = {
            "source_type": "text",
            "template_id": "t1",
            "preread_summary": "p" * 400,
            "turns": [{"a": 1}],
        }
        out = service._extract_content(session)
        assert "text" in out
        assert "t1" in out
        # preread 截断到 300 字符
        assert "p" * 300 in out
        assert "p" * 301 not in out

    def test_estimate_quality_score_heuristic(self, service):
        # quality_llm_enabled=False → 纯启发式
        session = {"turns": [], "preread_summary": ""}
        score = service._estimate_quality_score(session)
        assert score == 0.4  # 基础分

    def test_estimate_quality_score_with_turns(self, service):
        session = {"turns": [{"a": 1}] * 10, "preread_summary": "x" * 5000}
        score = service._estimate_quality_score(session)
        assert 0.4 <= score <= 1.0
        # turns(10)*0.05=0.5→cap 0.2；preread 5000/1000=5→cap 0.2 → 0.4+0.2+0.2=0.8
        assert score == pytest.approx(0.8)

    def test_estimate_quality_score_llm_valid(self, service, monkeypatch):
        service._quality_llm_enabled = True

        def fake_llm(session):
            return 0.9

        monkeypatch.setattr(service, "_llm_estimate_quality_score", fake_llm)
        assert service._estimate_quality_score({"turns": [], "preread_summary": ""}) == 0.9

    def test_estimate_quality_score_llm_out_of_range(self, service, monkeypatch):
        service._quality_llm_enabled = True

        def fake_llm(session):
            return 5.0  # 超范围 → 回退启发式

        monkeypatch.setattr(service, "_llm_estimate_quality_score", fake_llm)
        assert service._estimate_quality_score({"turns": [], "preread_summary": ""}) == 0.4

    def test_estimate_quality_score_llm_error(self, service, monkeypatch):
        service._quality_llm_enabled = True

        def fake_llm(session):
            raise ConnectionError("down")

        monkeypatch.setattr(service, "_llm_estimate_quality_score", fake_llm)
        assert service._estimate_quality_score({"turns": [], "preread_summary": ""}) == 0.4


# --------------------------------------------------------------------------- #
# 元数据 / memory_id
# --------------------------------------------------------------------------- #
class TestMetadata:
    def test_build_metadata(self, service):
        session = {
            "source_type": "image",
            "template_id": "t9",
            "session_id": "sid1",
            "quality_score": 0.7,
        }
        md = service._build_metadata(session, "permanent")
        assert md["importance"] == 0.75
        assert md["source"] == "image"
        assert md["tags"] == ["radix", "distillation", "t9", "permanent"]
        assert md["session_id"] == "sid1"
        assert md["quality_score"] == 0.7

    def test_alloc_memory_id(self, service):
        mid = service._alloc_memory_id()
        assert 1 <= mid <= 1000000


# --------------------------------------------------------------------------- #
# 文本切分 _split_text_into_chunks
# --------------------------------------------------------------------------- #
class TestSplitChunks:
    def test_empty(self, service):
        assert service._split_text_into_chunks("", 100) == []

    def test_short_text_single_chunk(self, service):
        assert service._split_text_into_chunks("hello", 100) == ["hello"]

    def test_long_text_paragraph_split(self, service):
        # 每 10 token → 30 字符；文本含段落边界
        text = "a" * 40 + "\n\n" + "b" * 40
        chunks = service._split_text_into_chunks(text, 10)
        assert len(chunks) >= 2
        assert "".join(chunks) == text
        assert all(len(c) <= 30 + 200 for c in chunks)

    def test_long_text_no_boundary_forced_split(self, service):
        # 无分隔符的长文本，强制按 target_chars 切分
        text = "x" * 1000
        chunks = service._split_text_into_chunks(text, 10)  # target=30 chars
        assert len(chunks) > 1
        assert "".join(chunks) == text


# --------------------------------------------------------------------------- #
# 决策日志 / session 持久化
# --------------------------------------------------------------------------- #
class TestPersistence:
    def test_write_decision_log_new(self, service):
        service._write_decision_log(
            "s1", "D3", {"x": 1}, {"y": 2}, "store", "permanent", {"k": "v"}
        )
        log_path = os.path.join(service._log_dir, "s1.json")
        assert os.path.exists(log_path)
        data = json.loads(open(log_path, encoding="utf-8").read())
        assert len(data) == 1
        assert data[0]["session_id"] == "s1"
        assert data[0]["final_decision"]["action"] == "store"

    def test_write_decision_log_append(self, service):
        service._write_decision_log("s2", "D3", {}, {}, "store", "permanent", {})
        service._write_decision_log("s2", "D4", {}, {}, "reject", None, {})
        data = json.loads(open(os.path.join(service._log_dir, "s2.json"), encoding="utf-8").read())
        assert len(data) == 2

    def test_write_decision_log_best_effort_bad_dir(self, service):
        # 只读目录 → 写入失败不应抛异常
        service._log_dir = "Z:/nonexistent_dir/__bogus__"
        service._write_decision_log("s3", "D3", {}, {}, "store", "permanent", {})  # 不应抛

    def test_save_and_load_session(self, service):
        session = {"session_id": "s1", "state": "S_INIT", "turns": []}
        service._save_session(session)
        loaded = service._load_session("s1")
        assert loaded == session
        # 缓存命中
        assert service._sessions_cache["s1"] == session

    def test_load_session_missing(self, service):
        assert service._load_session("missing") is None

    def test_save_session_error_raises_runtime(self, service):
        service._session_dir = "Z:/nonexistent/__bogus__"
        with pytest.raises(RuntimeError, match="session 持久化失败"):
            service._save_session({"session_id": "s1", "state": "S_INIT"})