"""quality suite 单测（全 Mock，禁真实网络）。

覆盖:
- 注册: pkgutil 自动发现生效（"quality" in list_suites()）
- SCRIPTS 契约: ≥2 脚本、每脚本 ≥4 轮、expects 与 turns 逐轮对齐、消息互不重复
- 正常回放 + 判分 → passed；每维 mean/std（总体标准差）与 overall_avg 手工精确断言
- judge prompt 约定: 含单行 `expected fact: ` 与 `answer: ` 段（stub judge 依赖）；
  prompt 含本轮用户消息与回复原文；agent_id 隔离约定 eval-agent-{run_id}
- 某维低分（< 3）→ low_scores 含案例（script_id/turn_index/scores/reason/reply 原文）
- overall_avg 恰好低于阈值 → failed（3 分不触发 low_scores）；恰好等于阈值 → passed（≥ 语义）
- judge 全部 judge_failed → error；judge 抛 JudgeUnavailableError → judge_unavailable
  （两者 summary 均无 dimensions/overall_avg 判分结构）
- 部分轮网络失败（TargetHttpError/TargetError）→ failed_turns 记录且不影响其余轮判分；
  全部轮失败 → error 且 judge 未被调用
- detail.json 落盘: 逐脚本逐轮完整记录（用户消息/回复/judge_prompt/scores/reason）

Mock 设计: FakeTarget.chat 按 (script_id, turn_index) 返回预设回复或抛网络异常；
FakeJudge.score 按预设序列逐次返回判分结果 / judge_failed 结构 / 异常。
判分序列按 SCRIPTS 固定顺序（脚本序 × 轮序）弹出，统计值手工可精确计算。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from evalkit.config import EvalConfig
from evalkit.judge import JudgeUnavailableError
from evalkit.suites import list_suites
from evalkit.suites.quality import (
    SCRIPTS,
    SCORE_DIMENSIONS,
    build_judge_prompt,
    run_quality_suite,
)
from evalkit.store import EvalStore
from evalkit.target import TargetError, TargetHttpError

SCRIPT_A = SCRIPTS[0]["script_id"]
SCRIPT_B = SCRIPTS[1]["script_id"]


# ---------------------------------------------------------------------------
# Mock 基础设施
# ---------------------------------------------------------------------------
def _locate(message: str) -> Tuple[str, int]:
    """按消息文本定位 (script_id, turn_index)。"""
    for script in SCRIPTS:
        if message in script["turns"]:
            return script["script_id"], script["turns"].index(message)
    raise AssertionError(f"未知回放消息: {message!r}")


class FakeTarget:
    """Mock target: 按 (script_id, turn_index) 返回预设回复或抛网络异常。"""

    def __init__(
        self,
        replies: Optional[Dict[Tuple[str, int], str]] = None,
        fails: Optional[Dict[Tuple[str, int], BaseException]] = None,
    ):
        self._replies = dict(replies or {})
        self._fails = dict(fails or {})
        self.calls: List[Dict[str, Any]] = []

    def chat(self, message: str, agent_id: str = "", timeout: float = 0.0) -> Dict[str, Any]:
        self.calls.append(
            {"message": message, "agent_id": agent_id, "timeout": timeout}
        )
        key = _locate(message)
        if key in self._fails:
            raise self._fails[key]
        default = f"陪伴回复[{key[0]}#t{key[1]}]"
        return {"response": self._replies.get(key, default), "session_id": "fake"}

    def create_eval_agent(self, run_id: str) -> Dict[str, Any]:
        return {"id": f"agent-fake{run_id[:6]}", "name": f"CXO-Eval-{run_id[:8]}"}

    def delete_agent(self, agent_id: str) -> Dict[str, Any]:
        self.deleted_agents = getattr(self, "deleted_agents", [])
        self.deleted_agents.append(agent_id)
        return {"status": "success"}


class FakeJudge:
    """Mock judge: 按预设序列逐次返回结果结构 / judge_failed 结构 / 异常。"""

    def __init__(self, sequence: List[Any]):
        self._sequence = list(sequence)
        self.prompts: List[str] = []

    def score(self, prompt: str) -> Dict[str, Any]:
        self.prompts.append(prompt)
        item = self._sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _scores(value: float) -> Dict[str, float]:
    """三维同值的分数 dict。"""
    return {dim: value for dim in SCORE_DIMENSIONS}


def _case(
    value: Optional[float] = None,
    scores: Optional[Dict[str, float]] = None,
    reason: str = "fake reason",
) -> Dict[str, Any]:
    """FakeJudge 的单次返回结构（score() 直接透传）。"""
    return {"scores": scores if scores is not None else _scores(value or 0), "reason": reason}


def _default_sequence(value: float, n: int) -> List[Dict[str, Any]]:
    return [_case(value) for _ in range(n)]


@pytest.fixture()
def store(tmp_path):
    s = EvalStore(str(tmp_path / "data"))
    yield s
    s.close()


def _run(store, target, judge, run_id: str, config: Optional[EvalConfig] = None) -> Dict[str, Any]:
    store.create_run(run_id, "quality")
    return run_quality_suite(
        run_id, config or EvalConfig(), store, client=target, judge=judge
    )


def _detail_json(store: EvalStore, run_id: str) -> Dict[str, Any]:
    path = Path(store.data_dir) / "runs" / run_id / "detail.json"
    assert path.exists(), f"detail.json 未落盘: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 注册与脚本契约
# ---------------------------------------------------------------------------
def test_quality_registered():
    """pkgutil 自动发现生效。"""
    assert "quality" in list_suites()


def test_scripts_contract():
    """≥2 脚本、每脚本 ≥4 轮、expects 逐轮对齐、消息互不重复、期望要点单行。"""
    assert len(SCRIPTS) >= 2
    all_messages: List[str] = []
    for script in SCRIPTS:
        assert script["script_id"] and script["description"]
        turns, expects = script["turns"], script["expects"]
        assert len(turns) >= 4
        assert len(expects) == len(turns)  # 每轮对应一条期望要点
        assert all("\n" not in e for e in expects)  # expected fact 行必须单行
        all_messages.extend(turns)
    assert len(set(all_messages)) == len(all_messages)  # 消息互不重复（可定位）


# ---------------------------------------------------------------------------
# 正常回放 + 判分
# ---------------------------------------------------------------------------
def test_run_quality_passed_exact_stats(store):
    """正常回放+判分 → passed；每维 mean/std（总体标准差）手工精确断言。

    判分序列（脚本序 × 轮序）: A=[5,4,5,4] B=[3,3,5,5]（三维同值）。
    每维样本同集 [5,4,5,4,3,3,5,5]: mean=34/8=4.25，
    总体 std=sqrt(5.5/8)=sqrt(0.6875)≈0.829156。
    overall_avg=mean(案例均分)=4.25 ≥ 3.5 → passed。
    """
    sequence = [_case(5), _case(4), _case(5), _case(4), _case(3), _case(3), _case(5), _case(5)]
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-pass")

    assert summary["status"] == "passed"
    assert summary["overall_avg"] == pytest.approx(4.25)
    for dim in SCORE_DIMENSIONS:
        d = summary["dimensions"][dim]
        assert d["count"] == 8
        assert d["mean"] == pytest.approx(4.25)
        assert d["std"] == pytest.approx(round(math.sqrt(0.6875), 3))
    assert summary["judgment"]["passed"] is True
    assert summary["judgment"]["threshold_avg_min"] == 3.5
    assert summary["low_scores"] == []
    assert summary["judge_failed_count"] == 0
    assert summary["failed_turns"] == []
    assert summary["scored_case_count"] == 8

    run = store.get_run("run-q-pass")
    assert run["status"] == "passed"
    assert run["metrics_summary"]["overall_avg"] == pytest.approx(4.25)
    assert len(target.calls) == 8 and len(judge.prompts) == 8


def test_dimensions_independent_stats(store):
    """三维分数互不相同时各维独立统计。

    A 全 4 轮: memory=5 / persona=4 / coherence=3；B 同。
    → memory mean=5 std=0，persona mean=4 std=0，coherence mean=3 std=0，
    案例均分=4.0 → overall_avg=4.0。
    """
    per_dim = {"memory_accuracy": 5.0, "persona_consistency": 4.0, "coherence": 3.0}
    sequence = [_case(scores=dict(per_dim)) for _ in range(8)]
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-dims")

    assert summary["status"] == "passed"
    assert summary["dimensions"]["memory_accuracy"]["mean"] == pytest.approx(5.0)
    assert summary["dimensions"]["persona_consistency"]["mean"] == pytest.approx(4.0)
    assert summary["dimensions"]["coherence"]["mean"] == pytest.approx(3.0)
    for dim in SCORE_DIMENSIONS:
        assert summary["dimensions"][dim]["std"] == pytest.approx(0.0)
    assert summary["overall_avg"] == pytest.approx(4.0)


def test_judge_prompt_convention_and_agent_isolation(store):
    """judge prompt 约定（expected fact: / answer: 行 + 本轮上下文）与 agent_id 隔离。"""
    custom_reply = "抱抱你，加班到这么晚一定很累吧，先吃点热乎的。"
    target = FakeTarget(replies={(SCRIPT_A, 0): custom_reply})
    judge = FakeJudge(_default_sequence(5, 8))
    run_id = "run-q-prompt"
    _run(store, target, judge, run_id=run_id)

    assert all(c["agent_id"].startswith("agent-fake") for c in target.calls)  # 按 run 注册的真实 agent id
    assert len(judge.prompts) == 8
    for i, prompt in enumerate(judge.prompts):
        assert "expected fact: " in prompt
        assert "\nanswer: " in prompt
        # prompt 不得提前出现约定的提取标记（首个 expected fact:/answer: 即约定行）
        assert prompt.index("expected fact: ") < prompt.index("\nanswer: ")
        # 轮次上下文: 第 i 个案例对应脚本序 × 轮序的用户消息与回复
        script = SCRIPTS[i // 4]
        turn_index = i % 4
        assert script["turns"][turn_index] in prompt
    # 首案例: expected fact 行与 answer 段内容与脚本/回复对齐
    first = judge.prompts[0]
    expect_lines = [ln for ln in first.splitlines() if ln.startswith("expected fact: ")]
    assert expect_lines == [f"expected fact: {SCRIPTS[0]['expects'][0]}"]
    assert first.endswith(f"answer: {custom_reply}")


def test_build_judge_prompt_pure_function():
    """纯函数: prompt 含约定行、期望要点单行、answer 段承载完整回复。"""
    prompt = build_judge_prompt("今天很累。", "抱抱你。", "reply 接住了疲惫情绪")
    assert "用户消息: 今天很累。" in prompt
    assert "agent 回复: 抱抱你。" in prompt
    assert "expected fact: reply 接住了疲惫情绪\n" in prompt
    assert prompt.rstrip().endswith("answer: 抱抱你。")


# ---------------------------------------------------------------------------
# low_scores 与终态判定
# ---------------------------------------------------------------------------
def test_low_scores_recorded_with_reply_and_reason(store):
    """某维低分（< 3）→ low_scores 含案例（原文 + 判分理由）；3 分不触发。"""
    sequence = [
        _case(4), _case(4), _case(4), _case(4),  # A0..A3
        _case(scores={"memory_accuracy": 2, "persona_consistency": 4, "coherence": 4}),  # B0
        _case(scores={"memory_accuracy": 4, "persona_consistency": 2, "coherence": 4}),  # B1
        _case(4), _case(4),  # B2, B3
    ]
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-low")

    assert len(summary["low_scores"]) == 2
    first, second = summary["low_scores"]
    assert first["script_id"] == SCRIPT_B and first["turn_index"] == 0
    assert first["scores"]["memory_accuracy"] == 2
    assert first["reason"] == "fake reason"
    assert first["reply"] == f"陪伴回复[{SCRIPT_B}#t0]"  # 回复原文保留在 summary
    assert second["script_id"] == SCRIPT_B and second["turn_index"] == 1
    assert second["scores"]["persona_consistency"] == 2
    # 3 分的维度不触发 low_scores: B2/B3 未入清单
    assert all(s["turn_index"] not in (2, 3) for s in summary["low_scores"])
    # 案例均分: A=4.0×4, B0=B1=(2+4+4)/3=10/3, B2=B3=4.0
    # overall_avg = (16 + 20/3) / 8 = 92/24 ≈ 3.833 ≥ 3.5 → passed
    assert summary["status"] == "passed"
    assert summary["overall_avg"] == pytest.approx(round(92 / 24, 3))


def test_failed_below_threshold(store):
    """overall_avg 恰好低于阈值（全 3 分 → 3.0 < 3.5）→ failed；3 分不触发 low_scores。"""
    sequence = _default_sequence(3, 8)
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-failed")

    assert summary["status"] == "failed"
    assert summary["overall_avg"] == pytest.approx(3.0)
    assert summary["judgment"]["passed"] is False
    assert summary["low_scores"] == []  # 3 分不算低分（严格 < 3）
    assert store.get_run("run-q-failed")["status"] == "failed"


def test_passed_at_exact_threshold(store):
    """overall_avg 恰好等于阈值 → passed（≥ 语义）。

    5 案例 (3,3,3) + 3 案例 (5,4,4): 总分 5×9+3×13=84，84/24=3.5 → passed。
    """
    three = _case(3)
    custom = _case(scores={"memory_accuracy": 5, "persona_consistency": 4, "coherence": 4})
    sequence = [three, three, three, custom, three, three, custom, custom]
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-boundary")

    assert summary["overall_avg"] == pytest.approx(3.5)
    assert summary["status"] == "passed"


# ---------------------------------------------------------------------------
# judge 失败降级
# ---------------------------------------------------------------------------
def test_all_judge_failed_error(store):
    """全案例 judge_failed（成功判分数=0）→ error，summary 无判分统计。"""
    sequence = [{"judge_failed": True, "error": "judge 输出 JSON 解析失败"}] * 8
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-jf")

    assert summary["status"] == "error"
    assert summary["judge_failed_count"] == 8
    assert "dimensions" not in summary and "overall_avg" not in summary
    assert len(judge.prompts) == 8  # 8 个案例都被判分（judge_failed 是案例级失败）
    run = store.get_run("run-q-jf")
    assert run["status"] == "error"
    assert "judge" in (run.get("error") or "")


def test_judge_unavailable_degrades_whole_run(store):
    """judge 抛 JudgeUnavailableError → 整个 run 降级 judge_unavailable，无判分统计。"""
    sequence = [JudgeUnavailableError("judge 连接失败")]
    target, judge = FakeTarget(), FakeJudge(sequence)
    summary = _run(store, target, judge, run_id="run-q-ju")

    assert summary["status"] == "judge_unavailable"
    assert "dimensions" not in summary and "overall_avg" not in summary
    assert "low_scores" not in summary
    assert len(judge.prompts) == 1  # 首案例即降级，不再继续判分
    assert summary["failed_turns"] == []
    run = store.get_run("run-q-ju")
    assert run["status"] == "judge_unavailable"
    assert "JudgeUnavailableError" in (run.get("error") or "")


# ---------------------------------------------------------------------------
# 网络失败
# ---------------------------------------------------------------------------
def test_partial_network_failure_continues_scoring(store):
    """部分轮网络失败 → failed_turns 记录（script/turn/error）且不影响其余轮判分。"""
    fails = {(SCRIPT_B, 0): TargetHttpError(500, "internal error")}
    target, judge = FakeTarget(fails=fails), FakeJudge(_default_sequence(4, 7))
    summary = _run(store, target, judge, run_id="run-q-net")

    assert summary["status"] == "passed"  # 其余 7 轮全 4 分 → 4.0 ≥ 3.5
    assert summary["overall_avg"] == pytest.approx(4.0)
    assert len(summary["failed_turns"]) == 1
    ft = summary["failed_turns"][0]
    assert ft["script_id"] == SCRIPT_B and ft["turn_index"] == 0
    assert "HTTP 500" in ft["error"]
    assert len(target.calls) == 8 and len(judge.prompts) == 7  # 失败轮不判分
    assert summary["judge_failed_count"] == 0


def test_all_network_failure_error(store):
    """全部轮失败 → error，judge 未被调用。"""
    fails = {
        (sid, t): TargetError("connection refused")
        for sid in (SCRIPT_A, SCRIPT_B)
        for t in range(4)
    }
    target, judge = FakeTarget(fails=fails), FakeJudge([])
    summary = _run(store, target, judge, run_id="run-q-allnet")

    assert summary["status"] == "error"
    assert len(summary["failed_turns"]) == 8
    assert all("TargetError" in ft["error"] for ft in summary["failed_turns"])
    assert judge.prompts == []  # 无回复可判分
    assert "dimensions" not in summary and "overall_avg" not in summary
    assert store.get_run("run-q-allnet")["status"] == "error"


# ---------------------------------------------------------------------------
# detail 落盘
# ---------------------------------------------------------------------------
def test_detail_artifacts_records_every_turn(store):
    """detail.json: 逐脚本逐轮完整记录（用户消息/回复/judge_prompt/scores/reason）。"""
    target, judge = FakeTarget(), FakeJudge(_default_sequence(4, 8))
    run_id = "run-q-detail"
    _run(store, target, judge, run_id=run_id)

    detail = _detail_json(store, run_id)
    assert detail["suite"] == "quality" and detail["run_id"] == run_id
    assert detail["status"] == "passed"
    assert len(detail["scripts"]) == len(SCRIPTS)
    for entry, script in zip(detail["scripts"], SCRIPTS):
        assert entry["script_id"] == script["script_id"]
        assert entry["description"] == script["description"]
        assert len(entry["turns"]) == len(script["turns"])
        for turn in entry["turns"]:
            assert turn["user_message"] in script["turns"]
            assert turn["reply"]
            assert turn["judge_prompt"].startswith("你是中文陪伴语境下的对话质量评判员")
            assert turn["scores"]["memory_accuracy"] == 4
            assert turn["reason"] == "fake reason"
            assert "judge_prompt" in turn  # prompt 完整进 detail
    # low_scores 案例在 detail 中同样保留
    assert detail["low_scores"] == []
