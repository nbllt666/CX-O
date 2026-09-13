"""memory_decay suite 单测（全 Mock，禁真实网络）。

- target：httpx.MockTransport 造 fake stub（种入/对话/检索/时间旅行/recall/删除），
  支持注入"遗忘规则"（按内容子串 + 生效天数窗口 + 是否同时从检索剔除）驱动 failed 路径。
- judge：注入 fake judge（按 prompt 中 expected fact / answer 约定判 5 或 1），
  支持 unavailable / judge_failed 模式。
- 覆盖：passed+矩阵结构、permanent 失忆、单调违反、再激活对照胜/负、
  judge 不可用、judge_failed 分母剔除、finally 清理（含中途异常）、
  时间旅行差分序列、agent_id 隔离、注册与内置场景加载。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
import pytest

from evalkit.config import EvalConfig
from evalkit.judge import JudgeUnavailableError
from evalkit.store import EvalStore
from evalkit.suites import list_suites
from evalkit.suites.memory_decay import load_scenario, load_scenarios, run_memory_decay
from evalkit.target import TargetClient

CONFIG = EvalConfig(target={"admin_api_key": "test-admin-key"})

# 与内置场景同构的临时基线场景（重要性 2/3/4 分层 + permanent 5）
# background_memories: [] 显式关闭背景干扰（背景逻辑由独立用例验证）
TMP_BASIC_YAML = """
scenario_id: tmp-decay-basic
description: 临时基线场景（测试用）
mode: decay
background_memories: []
seeds:
  - id: low_fact
    content: 我上周开始每天晨跑两公里
    importance: 2
    tags: [eval, habit]
    permanent: false
  - id: mid_fact
    content: 我最喜欢的电影是《千与千寻》，每次看都会哭
    importance: 3
    tags: [eval, movie]
    permanent: false
  - id: high_fact
    content: 我决定明年去冰岛看极光，已经在存钱了
    importance: 4
    tags: [eval, plan]
    permanent: false
  - id: core_personality
    content: 我永远记得用户在我最难过的时候陪我聊到天亮
    importance: 5
    tags: [eval, core]
    permanent: true
questions:
  - seed_id: low_fact
    question: 我最近每天坚持什么运动习惯？
  - seed_id: mid_fact
    question: 你还记得我最喜欢的电影是什么吗？
  - seed_id: high_fact
    question: 我之前说过想去哪里旅行？
  - seed_id: core_personality
    question: 在我最难过的时候发生过什么？
"""

TMP_REACT_YAML = """
scenario_id: tmp-react-contrast
description: 临时再激活对照场景（测试用）
mode: reactivation_contrast
endpoint_days: 365
background_memories: []
seeds:
  - id: control_pet
    content: 我家里养了一只叫小灰的猫，它很怕生
    importance: 3
    tags: [eval, control]
    permanent: false
  - id: control_guitar
    content: 我平时喜欢用木吉他弹民谣
    importance: 3
    tags: [eval, control]
    permanent: false
  - id: react_snow
    content: 我在北海道看过一场最大的雪
    importance: 3
    tags: [eval, reactivated]
    permanent: false
  - id: react_call
    content: 我每周五都会给外婆打一通电话
    importance: 3
    tags: [eval, reactivated]
    permanent: false
questions:
  - seed_id: control_pet
    question: 我家养的宠物叫什么名字？
  - seed_id: control_guitar
    question: 我平时喜欢弹什么乐器？
  - seed_id: react_snow
    question: 我在哪里看过一场大雪？
  - seed_id: react_call
    question: 我每周几会给外婆打电话？
"""


# ---------------------------------------------------------------------------
# Fake target（httpx.MockTransport）
# ---------------------------------------------------------------------------
class FakeTargetState:
    """fake 主服务状态：记忆表、时间旅行调用序列、遗忘规则、注入式故障。"""

    def __init__(self) -> None:
        self.next_id = 1
        self.memories: Dict[int, Dict[str, Any]] = {}
        self.time_travel_calls: List[int] = []
        self.recall_calls: List[int] = []
        self.delete_batches: List[List[int]] = []
        self.agent_ids: set = set()
        self.created_agents: List[Dict[str, Any]] = []
        self.deleted_agents: List[str] = []
        self.cumulative_shift = 0
        self.forget_rules: List[Dict[str, Any]] = []
        self.fail_chat_contains: Optional[str] = None

    def add_rule(self, contains: str, after_days: int = 0, until_days: Optional[int] = None,
                 drop_retrieval: bool = False) -> None:
        """遗忘规则：内容含 contains 且 cumulative_shift 落在 [after_days, until_days) 时遗忘。"""
        self.forget_rules.append(
            {"contains": contains, "after_days": after_days, "until_days": until_days,
             "drop_retrieval": drop_retrieval}
        )

    def active_rules(self, content: str) -> List[Dict[str, Any]]:
        return [
            r for r in self.forget_rules
            if r["contains"] in content
            and self.cumulative_shift >= r["after_days"]
            and (r["until_days"] is None or self.cumulative_shift < r["until_days"])
        ]


def _json_response(payload: Dict[str, Any], status: int = 200) -> httpx.Response:
    """构造 JSON 响应。必须用流式 content（而非 json= 预置）：
    httpx 0.28 下 resp.elapsed 依赖响应流关闭回调，预置 content 会短路该回调，
    导致 TargetClient.chat/search/rag 的 elapsed_ms 访问失败。"""
    return httpx.Response(
        status,
        content=[json.dumps(payload, ensure_ascii=False).encode("utf-8")],
        headers={"content-type": "application/json"},
    )


def build_fake_transport(state: FakeTargetState) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body: Dict[str, Any] = {}
        if method == "POST":
            try:
                body = json.loads(request.content.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {}

        if method == "POST" and path == "/api/agents":
            aid = f"agent-fake{len(state.created_agents):04d}"
            state.created_agents.append({**body, "id": aid})
            return _json_response({"status": "success", "agent": {**body, "id": aid}})

        if method == "DELETE" and path.startswith("/api/agents/"):
            aid = path.rsplit("/", 1)[1]
            state.deleted_agents.append(aid)
            return _json_response({"status": "success", "message": "已删除"})

        if method == "POST" and path == "/api/memories":
            state.agent_ids.add(str(body.get("agent_id")))
            mid = state.next_id
            state.next_id += 1
            state.memories[mid] = {**body, "id": mid}
            return _json_response({"status": "success", "memory_id": mid})

        if method == "GET" and path == "/api/memories":
            mems = [
                {"id": m["id"], "content": m.get("content", ""), "agent_id": m.get("agent_id")}
                for m in sorted(state.memories.values(), key=lambda x: x["id"])
            ]
            return _json_response({"status": "success", "memories": mems, "total": len(mems)})

        if method == "POST" and path == "/api/chat":
            state.agent_ids.add(str(body.get("agent_id")))
            message = str(body.get("message", ""))
            if state.fail_chat_contains and state.fail_chat_contains in message:
                raise RuntimeError(f"注入的 chat 故障: {message}")
            parts = [
                f"我记得，{m['content']}"
                for m in sorted(state.memories.values(), key=lambda x: x["id"])
                if not state.active_rules(str(m.get("content", "")))
                and set(message) & set(str(m.get("content", "")))
            ]
            return _json_response(
                {"status": "success", "response": "；".join(parts) or "我不记得了",
                 "session_id": "fake-session"}
            )

        if method == "POST" and path in ("/api/memories/search", "/api/memories/rag"):
            state.agent_ids.add(str(body.get("agent_id", request.url.params.get("agent_id"))))
            query = str(body.get("query", request.url.params.get("query", "")))
            limit = int(body.get("limit", request.url.params.get("limit", 5)) or 5)
            hits = []
            for m in sorted(state.memories.values(), key=lambda x: x["id"]):
                content = str(m.get("content", ""))
                if any(r["drop_retrieval"] for r in state.active_rules(content)):
                    continue  # drop_retrieval 规则：同时从检索剔除
                if set(query) & set(content):
                    hits.append(dict(m))
                if len(hits) >= limit:
                    break
            key = "memories" if path.endswith("/search") else "results"
            return _json_response({"status": "success", key: hits, "total": len(hits)})

        if method == "POST" and path.startswith("/api/memories/recall/"):
            state.agent_ids.add(str(request.url.params.get("agent_id")))
            mid = int(path.rsplit("/", 1)[1])
            mem = state.memories.get(mid)
            if mem is None:
                return _json_response({"detail": "记忆不存在"}, status=404)
            state.recall_calls.append(mid)
            return _json_response({"status": "success", "memory": mem})

        if method == "POST" and path == "/api/memories/eval/time-travel":
            state.agent_ids.add(str(body.get("agent_id")))
            shift = int(body.get("shift_days", 0))
            if not state.memories:
                return _json_response({"detail": "该 agent 下没有可操作的记忆"}, status=404)
            state.time_travel_calls.append(shift)
            state.cumulative_shift += shift
            return _json_response({"status": "success", "shifted_count": len(state.memories)})

        if method == "POST" and path == "/api/memories/sync-decay":
            return _json_response({"status": "success", "result": {"ok": True}})

        if method == "POST" and path == "/api/memories/batch/delete":
            state.agent_ids.add(str(body.get("agent_id")))
            ids = [int(i) for i in (body.get("ids") or [])]
            state.delete_batches.append(list(ids))
            for i in ids:
                state.memories.pop(i, None)
            return _json_response({"status": "success", "deleted": len(ids)})

        return _json_response({"detail": f"fake 未实现: {method} {path}"}, status=404)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Fake judge（按 prompt 约定确定性判分）
# ---------------------------------------------------------------------------
class FakeJudge:
    """mode: normal（expected in answer → 5 否则 1）/ unavailable（抛 JudgeUnavailableError）；
    fail_when(prompt) 为真时返回 judge_failed（单案例失败）。"""

    def __init__(self, mode: str = "normal", fail_when=None):
        self.mode = mode
        self.fail_when = fail_when
        self.prompts: List[str] = []

    def score(self, prompt: str) -> Dict[str, Any]:
        self.prompts.append(prompt)
        if self.mode == "unavailable":
            raise JudgeUnavailableError("judge 服务不可达")
        if self.fail_when and self.fail_when(prompt):
            return {"judge_failed": True, "error": "judge 输出不可解析"}
        m_exp = re.search(r"expected fact:\s*(.+)", prompt)
        m_ans = re.search(r"answer:\s*(.+)", prompt, re.S)
        expected = m_exp.group(1).strip() if m_exp else ""
        answer = m_ans.group(1).strip() if m_ans else ""
        score = 5.0 if expected and expected in answer else 1.0
        return {"scores": {"memory_accuracy": score}, "reason": "fake"}


# ---------------------------------------------------------------------------
# 测试工具
# ---------------------------------------------------------------------------
def make_store(tmp_path) -> EvalStore:
    return EvalStore(str(tmp_path / "data"))


def make_client(state: FakeTargetState) -> TargetClient:
    return TargetClient(CONFIG, transport=build_fake_transport(state))


def write_scenarios(tmp_path, yaml_texts: List[str]) -> str:
    d = tmp_path / "scenarios"
    d.mkdir()
    for i, text in enumerate(yaml_texts):
        (d / f"s{i}.yaml").write_text(text.strip() + "\n", encoding="utf-8")
    return str(d)


def run_suite(tmp_path, state: FakeTargetState, judge: FakeJudge, yaml_texts: List[str],
              run_id: str = "test-run") -> Dict[str, Any]:
    scenarios_dir = write_scenarios(tmp_path, yaml_texts)
    store = make_store(tmp_path)
    store.create_run(run_id, "memory_decay", CONFIG.to_safe_dict())  # 生产由 runner 创建，直调需自建
    client = make_client(state)
    return run_memory_decay(
        run_id, CONFIG, store, client=client, judge=judge, scenarios_dir=scenarios_dir
    )


def read_detail(store: EvalStore, run_id: str) -> Dict[str, Any]:
    path = os.path.join(store.data_dir, "runs", run_id, "detail.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_store(tmp_path) -> EvalStore:
    return make_store(tmp_path)


# ---------------------------------------------------------------------------
# 注册与场景库
# ---------------------------------------------------------------------------
def test_memory_decay_registered():
    assert "memory_decay" in list_suites()


def test_load_builtin_scenarios():
    scenarios = load_scenarios()
    ids = [s["scenario_id"] for s in scenarios]
    assert len(ids) >= 2
    assert "long-term-decay-basic" in ids
    assert "reactivation-contrast" in ids
    basic = load_scenario("long-term-decay-basic")
    assert basic["mode"] == "decay"
    assert {s["importance"] for s in basic["seeds"]} == {2, 3, 4, 5}
    react = load_scenario("reactivation-contrast")
    assert react["mode"] == "reactivation_contrast"
    tags = {t for s in react["seeds"] for t in s["tags"]}
    assert {"control", "reactivated"} <= tags
    assert load_scenario("nonexistent-scenario") is None


# ---------------------------------------------------------------------------
# 正常路径
# ---------------------------------------------------------------------------
def test_passed_run_retention_matrix_and_time_travel_sequence(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    metrics = run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "passed"
    # retention_matrix 结构：4 个间隔 × 5 组
    assert set(metrics["retention_matrix"]) == {30, 180, 365, 1095}
    assert metrics["retention_matrix"][30] == {
        "overall": 1.0,
        "importance_low(1-2)": 1.0,
        "importance_mid(3)": 1.0,
        "importance_high(4-5)": 1.0,
        "permanent": 1.0,
    }
    assert metrics["retention_matrix"][1095]["overall"] == 1.0
    assert metrics["retrieval_hit_rate"]["search"][365] == 1.0
    assert metrics["retrieval_hit_rate"]["rag"][30] == 1.0
    assert metrics["monotonic_violations"] == []
    assert metrics["reactivation_contrast"] is None  # 无再激活场景
    assert metrics["failure_reasons"] == []
    assert metrics["judge_failed_count"] == 0
    # 时间旅行差分序列：D 升序 [30,180,365,1095] → 差分 [30,150,185,730]
    assert state.time_travel_calls == [30, 150, 185, 730]
    # agent_id 隔离：全部请求只用按 run 注册的真实 eval agent（服务端生成 id）
    assert len(state.created_agents) == 1
    assert state.agent_ids == {state.created_agents[0]["id"]}
    assert state.deleted_agents == [state.created_agents[0]["id"]]


def test_hit_type_distribution(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    state.add_rule("千与千寻", after_days=180)                       # 遗忘但仍可检索
    state.add_rule("晨跑", after_days=180, drop_retrieval=True)      # 遗忘且检索剔除
    metrics = run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    detail = read_detail(get_store(tmp_path), "test-run")
    cases = detail["scenarios"][0]["cases"]
    at_30 = [c for c in cases if c["interval_days"] == 30]
    assert all(c["hit_type"] == "both" for c in at_30)
    at_365 = [c for c in cases if c["interval_days"] == 365]
    types = {c["hit_type"] for c in at_365}
    assert "retrieved_not_answered" in types  # 检索到但答不出
    assert "not_retrieved" in types           # 检索不到
    # 命中率仍按 judge 无关口径累计（365 天：low 被剔除，其余 3 条命中 → 0.75）
    assert metrics["retrieval_hit_rate"]["search"][30] == 1.0
    assert metrics["retrieval_hit_rate"]["search"][365] == 0.75


# ---------------------------------------------------------------------------
# failed 路径
# ---------------------------------------------------------------------------
def test_permanent_forgotten_failed(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    state.add_rule("陪我聊到天亮", after_days=30)  # permanent 种子从 30 天起失忆
    metrics = run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "failed"
    assert metrics["retention_matrix"][365]["permanent"] == 0.0
    assert any("permanent" in r for r in metrics["failure_reasons"])


def test_monotonic_violation_failed(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    # 遗忘窗口 [180, 365)：180 天时忘、365 天时"记起来" → 保持率回升 → 单调违反
    state.add_rule("千与千寻", after_days=180, until_days=365)
    metrics = run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "failed"
    assert metrics["retention_matrix"][180]["overall"] == 0.75
    assert metrics["retention_matrix"][365]["overall"] == 1.0
    assert metrics["monotonic_violations"]
    assert any(
        v["prev_interval"] == 180 and v["curr_interval"] == 365
        for v in metrics["monotonic_violations"]
    )


def test_reactivation_pass_and_time_travel_sequence(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    state.add_rule("小灰", after_days=60)    # 对照组遗忘
    state.add_rule("木吉他", after_days=60)
    metrics = run_suite(tmp_path, state, judge, [TMP_REACT_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "passed"
    contrast = metrics["reactivation_contrast"]
    assert contrast["control"] == 0.0
    assert contrast["reactivated"] == 1.0
    assert contrast["passes"] is True
    # 再激活组时间旅行序列：终点 365 = 12 步 × 30 天 + 补齐 5 天
    assert state.time_travel_calls == [30] * 12 + [5]
    # 再激活组每步每条 seed 各 recall 一次：2 条 × 12 步 = 24
    assert len(state.recall_calls) == 24
    assert set(state.recall_calls) == {3, 4}  # 再激活组 memory_id（对照组 1/2 不 recall）


def test_reactivation_fail_when_not_beat_control(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    state.add_rule("北海道", after_days=60)  # 再激活组被遗忘，对照组健全
    state.add_rule("外婆", after_days=60)
    metrics = run_suite(tmp_path, state, judge, [TMP_REACT_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "failed"
    contrast = metrics["reactivation_contrast"]
    assert contrast["control"] == 1.0
    assert contrast["reactivated"] == 0.0
    assert contrast["passes"] is False
    assert any("再激活" in r for r in metrics["failure_reasons"])


# ---------------------------------------------------------------------------
# judge 异常路径
# ---------------------------------------------------------------------------
def test_judge_unavailable_partial_metrics_and_stop(tmp_path):
    state = FakeTargetState()
    judge = FakeJudge(mode="unavailable")
    metrics = run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "judge_unavailable"
    assert metrics["judge_unavailable"] is True
    # 首次 score 即终止对话层判分：仅第 1 个案例调用过 judge
    assert len(judge.prompts) == 1
    # 无有效判分 → 保持率矩阵无条目（分母剔除）
    assert metrics["retention_matrix"] == {}
    # 非 judge 指标必须仍产出
    assert metrics["retrieval_hit_rate"]["search"] == {30: 1.0, 180: 1.0, 365: 1.0, 1095: 1.0}
    assert metrics["retrieval_hit_rate"]["rag"][180] == 1.0
    # 清理照常生效
    assert state.delete_batches and read_detail(store, "test-run")["cleanup"]["remaining"] == 0


def test_judge_failed_count_and_denominator_exclusion(tmp_path):
    state = FakeTargetState()
    # 仅 low_fact 的 4 个案例判分失败（锚定 expected fact 行；chat 回复串会携带其他种子内容，
    # 不能用裸子串判断，否则全部 16 个案例都会被判 judge_failed）
    judge = FakeJudge(fail_when=lambda p: bool(re.search(r"expected fact:.*晨跑", p)))
    metrics = run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    store = get_store(tmp_path)
    assert store.get_run("test-run")["status"] == "passed"
    assert metrics["judge_failed_count"] == 4
    # judge_failed 案例不计入分母：low 组无有效案例 → 无条目
    assert "importance_low(1-2)" not in metrics["retention_matrix"][30]
    # overall 分母仅剩 3 个有效案例且全部保持
    assert metrics["retention_matrix"][30]["overall"] == 1.0
    assert metrics["retention_matrix"][30]["importance_mid(3)"] == 1.0
    assert metrics["retention_matrix"][365]["overall"] == 1.0


# ---------------------------------------------------------------------------
# 清理（try/finally）
# ---------------------------------------------------------------------------
def test_cleanup_on_success(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    run_suite(tmp_path, state, judge, [TMP_BASIC_YAML])
    store = get_store(tmp_path)
    detail = read_detail(store, "test-run")
    assert state.delete_batches == [[1, 2, 3, 4]]
    assert detail["cleanup"]["attempted"] == 4
    assert detail["cleanup"]["deleted"] == 4
    assert detail["cleanup"]["remaining"] == 0
    assert detail["cleanup"]["agent_deleted"] is True  # 一次性 eval agent 已删除
    assert state.memories == {}


def test_cleanup_on_midway_exception(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    state.fail_chat_contains = "炸"  # 第 1 个案例 chat 即抛异常
    tmp_yaml = TMP_BASIC_YAML.replace(
        "我最近每天坚持什么运动习惯？", "我最近每天坚持什么运动习惯？这条记忆炸了吗？"
    )
    metrics = run_suite(tmp_path, state, judge, [tmp_yaml])
    store = get_store(tmp_path)
    run = store.get_run("test-run")
    assert run["status"] == "error"
    assert run["error"] and "注入的 chat 故障" in run["error"]
    detail = read_detail(store, "test-run")
    # 中途异常仍触发 finally 清理，且清理结果写入 detail
    assert state.delete_batches == [[1, 2, 3, 4]]
    assert detail["cleanup"]["attempted"] == 4
    assert detail["cleanup"]["remaining"] == 0
    assert detail["status"] == "error"


# ---------------------------------------------------------------------------
# 内置场景端到端（默认 scenarios 目录，仍全 Mock）
# ---------------------------------------------------------------------------
def test_builtin_scenarios_end_to_end(tmp_path):
    state, judge = FakeTargetState(), FakeJudge()
    store = make_store(tmp_path)
    store.create_run("builtin-run", "memory_decay", CONFIG.to_safe_dict())
    client = make_client(state)
    metrics = run_memory_decay(
        "builtin-run", CONFIG, store, client=client, judge=judge  # scenarios_dir=None → 包内置场景
    )
    detail = read_detail(store, "builtin-run")
    # 两个内置场景都执行：decay 基线 + 再激活对照
    assert [s["scenario_id"] for s in detail["scenarios"]] == [
        "long-term-decay-basic", "reactivation-contrast",
    ]
    assert set(metrics["retention_matrix"]) == {30, 180, 365, 1095}
    assert metrics["retention_matrix"][30]["permanent"] == 1.0
    # 无遗忘规则下再激活两组全部保持 → 平局 → 未严格胜出 → failed（reactivation_must_beat_control）
    contrast = metrics["reactivation_contrast"]
    assert contrast["control"] == 1.0 and contrast["reactivated"] == 1.0
    assert contrast["passes"] is False
    assert any("再激活" in r for r in metrics["failure_reasons"])
    # 时间旅行：decay 4 次 + 再激活 13 次
    assert state.time_travel_calls[:4] == [30, 150, 185, 730]
    assert len(state.time_travel_calls) == 17
    # 背景干扰记忆：两场景各默认种入 20 条（背景不参与判分/时间旅行）
    bg = {s["scenario_id"]: s["background_memories"] for s in detail["scenarios"]}
    assert bg["long-term-decay-basic"]["requested"] == 20
    assert bg["long-term-decay-basic"]["seeded"] == 20
    assert bg["reactivation-contrast"]["seeded"] == 20
    # 清理：8 条种子 + 2×20 条背景全部物理删除
    assert detail["cleanup"]["attempted"] == 48
    assert detail["cleanup"]["remaining"] == 0
