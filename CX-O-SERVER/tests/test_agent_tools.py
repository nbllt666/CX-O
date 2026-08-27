"""AgentToolsV2（server.core.decision.agent_tools）回归保护测试。

覆盖 8 个工具（Agent CRUD / 蒸馏 / 模板 / 决策）、tools_config 与蒸馏开关
权限检查、agents.json 读写（tmp_path 隔离）。蒸馏/模板/决策依赖用轻量替身注入，
避免网络与真实服务。
"""
import json

import pytest

from server.core.decision.agent_tools import (
    AddAgentRequest,
    AdvanceDistillationToolRequest,
    AgentToolsV2,
    DecideStorageToolRequest,
    FinalizeDistillationToolRequest,
    RenderTemplateToolRequest,
    StartDistillationToolRequest,
    UpdateAgentRequest,
    _DEFAULT_DECISION_RUBRIC,
    _DEFAULT_TOOLS_CONFIG,
    _REQUIRED_RUBRIC_FIELDS,
)


# --------------------------------------------------------------------------- #
# 替身
# --------------------------------------------------------------------------- #
class FakeService:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _default_rubric():
    return dict(_DEFAULT_DECISION_RUBRIC)


def _make_tools(tmp_path, caller=None, **deps):
    return AgentToolsV2(
        caller_agent_id=caller,
        agents_file=str(tmp_path / "agents.json"),
        **deps,
    )


# --------------------------------------------------------------------------- #
# 工具启用 / 蒸馏开关检查
# --------------------------------------------------------------------------- #
class TestPermissionChecks:
    def test_no_caller_skips_check(self, tmp_path):
        t = _make_tools(tmp_path)
        t._check_tool_enabled("add_agent")  # 不抛
        t._check_distillation_enabled()  # 不抛

    def test_caller_missing_agent_passes(self, tmp_path):
        t = _make_tools(tmp_path, caller="ghost")
        t._check_tool_enabled("add_agent")  # best-effort 放行

    def test_disabled_tool_raises(self, tmp_path):
        t = _make_tools(tmp_path, caller="default")
        # default agent 的 add_agent 默认启用，先手动改配置
        data = t._load_agents()
        for rec in data["agents"]:
            if rec["agent_id"] == "default":
                rec["tools_config"]["add_agent"] = False
        t._save_agents(data)
        with pytest.raises(PermissionError):
            t._check_tool_enabled("add_agent")

    def test_distillation_disabled_raises(self, tmp_path):
        t = _make_tools(tmp_path, caller="default")  # default 蒸馏未启用
        with pytest.raises(PermissionError):
            t._check_distillation_enabled()


# --------------------------------------------------------------------------- #
# agents.json 加载/保存
# --------------------------------------------------------------------------- #
class TestLoadSave:
    def test_load_defaults_when_missing(self, tmp_path):
        t = _make_tools(tmp_path)
        data = t._load_agents()
        ids = {r["agent_id"] for r in data["agents"]}
        assert "default" in ids
        assert "memory-agent" in ids

    def test_load_corrupt_json_raises(self, tmp_path):
        """M-E 旧行为契约更新（20260827 第四轮）: 损坏 JSON 不再静默返回空结构
        （写路径会以空结构覆写丢掉全部 agent），改为抛 IOError 中断。"""
        p = tmp_path / "agents.json"
        p.write_text("{bad json", encoding="utf-8")
        t = _make_tools(tmp_path)
        with pytest.raises(IOError, match="解析失败"):
            t._load_agents()

    def test_load_non_dict_raises(self, tmp_path):
        """M-E 定向: 顶层非对象（结构损坏）同样 fail-fast 抛 IOError。"""
        p = tmp_path / "agents.json"
        p.write_text("[1,2]", encoding="utf-8")
        t = _make_tools(tmp_path)
        with pytest.raises(IOError, match="结构损坏"):
            t._load_agents()

    def test_corrupt_file_not_overwritten_by_write_path(self, tmp_path):
        """M-E 定向: agents.json 损坏时 add_agent 直接失败，不覆写原文件。"""
        p = tmp_path / "agents.json"
        broken = "{bad json"
        p.write_text(broken, encoding="utf-8")
        t = _make_tools(tmp_path)
        req = AddAgentRequest(
            agent_id="boom", name="B", config={"decision_rubric": _default_rubric()}
        )
        with pytest.raises(IOError):
            t.add_agent(req)
        assert p.read_text(encoding="utf-8") == broken  # 原文件字节未动

    def test_save_atomic_no_tmp_leftovers(self, tmp_path):
        """M-E 定向: _save_agents 经临时文件 + os.replace，成功后无 .tmp 残留。"""
        t = _make_tools(tmp_path)
        data = t._load_agents()
        t._save_agents(data)
        leftovers = list(tmp_path.glob(".agents-*.json.tmp"))
        assert leftovers == []
        # 落盘内容可再次合法解析（原子替换完整写入）
        assert t._load_agents()["agents"]

    def test_save_and_reload(self, tmp_path):
        t = _make_tools(tmp_path)
        data = t._load_agents()
        data["agents"].append({"agent_id": "x", "name": "X"})
        t._save_agents(data)
        t2 = _make_tools(tmp_path)
        loaded = t2._load_agents()
        assert any(r["agent_id"] == "x" for r in loaded["agents"])


# --------------------------------------------------------------------------- #
# Agent CRUD
# --------------------------------------------------------------------------- #
class TestAgentCRUD:
    def _rubric(self):
        return _default_rubric()

    def test_add_agent(self, tmp_path):
        t = _make_tools(tmp_path)
        rec = t.add_agent(
            AddAgentRequest(
                agent_id="a1", name="Agent1", config={"decision_rubric": self._rubric()}
            )
        )
        assert rec.agent_id == "a1"
        assert rec.distillation_enabled is False
        # 持久化
        assert any(r["agent_id"] == "a1" for r in t._load_agents()["agents"])

    def test_add_agent_empty_id(self, tmp_path):
        t = _make_tools(tmp_path)
        with pytest.raises(ValueError):
            t.add_agent(AddAgentRequest(agent_id="", name="x", config={"decision_rubric": self._rubric()}))
        with pytest.raises(ValueError):
            t.add_agent(AddAgentRequest(agent_id="a", name="", config={"decision_rubric": self._rubric()}))

    def test_add_agent_duplicate(self, tmp_path):
        t = _make_tools(tmp_path)
        t.add_agent(AddAgentRequest(agent_id="a1", name="x", config={"decision_rubric": self._rubric()}))
        with pytest.raises(FileExistsError):
            t.add_agent(AddAgentRequest(agent_id="a1", name="y", config={"decision_rubric": self._rubric()}))

    def test_add_agent_missing_rubric(self, tmp_path):
        t = _make_tools(tmp_path)
        with pytest.raises(ValueError):
            t.add_agent(AddAgentRequest(agent_id="a1", name="x", config={}))

    def test_add_agent_partial_rubric(self, tmp_path):
        t = _make_tools(tmp_path)
        rubric = self._rubric()
        rubric.pop("quality_reject_threshold")
        with pytest.raises(ValueError):
            t.add_agent(AddAgentRequest(agent_id="a1", name="x", config={"decision_rubric": rubric}))

    def test_update_agent_name(self, tmp_path):
        t = _make_tools(tmp_path)
        t.add_agent(AddAgentRequest(agent_id="a1", name="x", config={"decision_rubric": self._rubric()}))
        rec = t.update_agent("a1", UpdateAgentRequest(name="新名"))
        assert rec.name == "新名"

    def test_update_agent_missing(self, tmp_path):
        t = _make_tools(tmp_path)
        with pytest.raises(KeyError):
            t.update_agent("nope", UpdateAgentRequest(name="x"))

    def test_update_agent_bad_rubric(self, tmp_path):
        t = _make_tools(tmp_path)
        t.add_agent(AddAgentRequest(agent_id="a1", name="x", config={"decision_rubric": self._rubric()}))
        bad = self._rubric()
        bad.pop("max_redistill_turns")
        with pytest.raises(ValueError):
            t.update_agent("a1", UpdateAgentRequest(config={"decision_rubric": bad}))

    def test_delete_agent(self, tmp_path):
        t = _make_tools(tmp_path)
        t.add_agent(AddAgentRequest(agent_id="a1", name="x", config={"decision_rubric": self._rubric()}))
        assert t.delete_agent("a1") is True
        with pytest.raises(KeyError):
            t.delete_agent("a1")

    def test_delete_missing(self, tmp_path):
        t = _make_tools(tmp_path)
        with pytest.raises(KeyError):
            t.delete_agent("nope")


# --------------------------------------------------------------------------- #
# 蒸馏工具
# --------------------------------------------------------------------------- #
class TestDistillation:
    def _svc(self):
        async def start(**k):
            return FakeService(session_id="s1", initial_state="S0", preread_summary="sum")

        async def advance(**k):
            return FakeService(session_id="s1", current_state="S1", agent_action="ask", next_needed="resp")

        async def finalize(**k):
            return FakeService(stored=True, location="permanent", memory_id=1, metadata={}, reason="ok")

        return FakeService(
            start_distillation=start,
            advance_distillation=advance,
            finalize_distillation=finalize,
        )

    def test_start(self, tmp_path):
        t = _make_tools(tmp_path, caller=None, distillation_service=self._svc())
        res = t.start_distillation(
            StartDistillationToolRequest(source_type="text", template_id="t1")
        )
        assert res["session_id"] == "s1"

    def test_start_invalid_source_type(self, tmp_path):
        t = _make_tools(tmp_path, distillation_service=self._svc())
        with pytest.raises(ValueError):
            t.start_distillation(StartDistillationToolRequest(source_type="video", template_id="t1"))

    def test_start_max_turns_range(self, tmp_path):
        t = _make_tools(tmp_path, distillation_service=self._svc())
        with pytest.raises(ValueError):
            t.start_distillation(
                StartDistillationToolRequest(source_type="text", template_id="t1", max_turns=0)
            )
        with pytest.raises(ValueError):
            t.start_distillation(
                StartDistillationToolRequest(source_type="text", template_id="t1", max_turns=7)
            )

    def test_start_empty_template(self, tmp_path):
        t = _make_tools(tmp_path, distillation_service=self._svc())
        with pytest.raises(ValueError):
            t.start_distillation(StartDistillationToolRequest(source_type="text", template_id=""))

    def test_start_service_error(self, tmp_path):
        async def bad(**k):
            raise RuntimeError("x")

        svc = FakeService(start_distillation=bad)
        t = _make_tools(tmp_path, distillation_service=svc)
        with pytest.raises(ConnectionError):
            t.start_distillation(
                StartDistillationToolRequest(source_type="text", template_id="t1")
            )

    def test_advance(self, tmp_path):
        t = _make_tools(tmp_path, distillation_service=self._svc())
        res = t.advance_distillation(AdvanceDistillationToolRequest(session_id="s1"))
        assert res["current_state"] == "S1"

    def test_advance_empty_session(self, tmp_path):
        t = _make_tools(tmp_path, distillation_service=self._svc())
        with pytest.raises(KeyError):
            t.advance_distillation(AdvanceDistillationToolRequest(session_id=""))

    def test_finalize(self, tmp_path):
        t = _make_tools(tmp_path, distillation_service=self._svc())
        res = t.finalize_distillation(FinalizeDistillationToolRequest(session_id="s1"))
        assert res["stored"] is True
        assert res["memory_id"] == 1


# --------------------------------------------------------------------------- #
# 模板工具
# --------------------------------------------------------------------------- #
class TestTemplate:
    def test_render(self, tmp_path):
        engine = FakeService(
            render_template=lambda **k: FakeService(
                rendered_prompt="OUT", workflow_definition={"steps": 1}, expected_turns=2
            )
        )
        t = _make_tools(tmp_path, template_engine=engine)
        res = t.render_template(RenderTemplateToolRequest(template_id="t1", variables={}))
        assert res["rendered_prompt"] == "OUT"
        assert res["expected_turns"] == 2

    def test_render_missing_template(self, tmp_path):
        t = _make_tools(tmp_path, template_engine=FakeService(render_template=lambda **k: None))
        with pytest.raises(KeyError):
            t.render_template(RenderTemplateToolRequest(template_id="", variables={}))


# --------------------------------------------------------------------------- #
# 决策工具
# --------------------------------------------------------------------------- #
class TestDecision:
    def _decision_core(self):
        from server.core.decision.decision_core import RubricSnapshot, StorageDecision

        class FakeCore:
            def __init__(self):
                self.rubric = _default_rubric()

            def _load_rubric(self, agent_id):
                return self.rubric

            def decide_location(self, **kwargs):
                return StorageDecision(
                    decision_id="d1",
                    session_id=kwargs["session_id"],
                    decision_point="D1",
                    location="permanent_memories",
                    memory_id=1,
                    metadata={},
                    reason="auto",
                    quality_score=0.82,
                    rubric_snapshot=RubricSnapshot(
                        importance_threshold_permanent=0.7,
                        quality_reject_threshold=0.3,
                        max_redistill_turns=2,
                        ask_user_confidence_threshold=0.4,
                        cross_validate_sources=[],
                    ),
                    llm_confidence=None,
                    override_decision=None,
                    created_at="2026-08-08T00:00:00",
                )

        return FakeCore()

    def test_decide(self, tmp_path):
        t = _make_tools(tmp_path, caller=None, decision_core=self._decision_core())
        res = t.decide_storage(DecideStorageToolRequest(session_id="s1"))
        assert res["decision_point"] == "D1"
        assert res["location"] == "permanent_memories"

    def test_decide_override_permanent(self, tmp_path):
        t = _make_tools(tmp_path, caller=None, decision_core=self._decision_core())
        res = t.decide_storage(
            DecideStorageToolRequest(session_id="s1", override_decision="permanent")
        )
        assert res["location"] == "permanent_memories"
        assert res["reason"].startswith("人类 override=")

    def test_decide_override_reject(self, tmp_path):
        t = _make_tools(tmp_path, caller=None, decision_core=self._decision_core())
        res = t.decide_storage(
            DecideStorageToolRequest(session_id="s1", override_decision="reject")
        )
        assert res["location"] == "rejected"
        assert res["memory_id"] is None

    def test_decide_empty_session(self, tmp_path):
        t = _make_tools(tmp_path, caller=None, decision_core=self._decision_core())
        with pytest.raises(KeyError):
            t.decide_storage(DecideStorageToolRequest(session_id=""))


# --------------------------------------------------------------------------- #
# 懒加载依赖
# --------------------------------------------------------------------------- #
class TestLazyDependencies:
    def test_injected_distillation_service_returned(self, tmp_path):
        svc = FakeService(marker="x")
        t = _make_tools(tmp_path, distillation_service=svc)
        assert t._get_distillation_service() is svc

    def test_lazy_load_resolves_real_distillation_module(self, tmp_path, monkeypatch):
        """懒加载路径应解析到真实 distillation_service 模块（修复导入路径错误）。"""
        import server.core.distillation.distillation_service as real_mod

        fake_cls = type("FakeDistillation", (FakeService,), {})
        monkeypatch.setattr(real_mod, "DistillationService", fake_cls)
        t = _make_tools(tmp_path)
        t._distillation_service = None
        svc = t._get_distillation_service()
        assert isinstance(svc, fake_cls)

    def test_injected_template_engine_returned(self, tmp_path):
        engine = FakeService(marker="y")
        t = _make_tools(tmp_path, template_engine=engine)
        assert t._get_template_engine() is engine

    def test_injected_decision_core_returned(self, tmp_path):
        core = FakeService(marker="z")
        t = _make_tools(tmp_path, decision_core=core)
        assert t._get_decision_core() is core


# --------------------------------------------------------------------------- #
# 工具配置默认值
# --------------------------------------------------------------------------- #
class TestDefaults:
    def test_default_tools_config_all_enabled(self):
        assert set(_DEFAULT_TOOLS_CONFIG.values()) == {True}
        assert len(_DEFAULT_TOOLS_CONFIG) == 8

    def test_required_rubric_fields_present(self):
        for f in _REQUIRED_RUBRIC_FIELDS:
            assert f in _DEFAULT_DECISION_RUBRIC