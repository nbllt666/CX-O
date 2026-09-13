"""memory_decay suite：长期记忆劣化评测。

编排流程（逐场景）：
  1. 种入：逐条 create_memory（主服务 batch/write 不透传 agent_id，必须逐条走单条端点），
     记录 memory_id ↔ seed 映射；run 全程使用隔离 agent_id = eval-agent-{run_id}。
  2. decay 模式：对 interval_days 升序逐一到达——维护累计已回拨 shift_so_far，
     本轮 time_travel(D - shift_so_far) 差分回拨 → sync_decay → 逐 seed 提问（chat）
     → judge 判分（expected fact = seed.content，answer = chat 回复，
     memory_accuracy >= 3 记"保持"）→ search/rag 检索命中判定。
  3. reactivation_contrast 模式：从种入点到终点 1 年，每 reactivation_visit_every_days
     天一步 time_travel → 对再激活组逐条 recall（显式传 eval agent_id）；
     到终点后对照组/再激活组同终点提问+judge，对比保持率。
  4. 指标：retention_matrix（overall/重要性分层/permanent）、retrieval_hit_rate、
     monotonic_violations（±0.1 容差）、reactivation_contrast。
  5. 终态：permanent<1.0 / 单调违反 / 再激活未胜对照 / 1年overall<阈值 → failed；
     judge 网络不可用 → judge_unavailable（已完成部分照常汇总，命中率仍产出）；
     judge 单案例失败 → 计数并剔除出保持率分母。
  6. 清理：try/finally 保证无论成败都 list_memories → batch_delete 物理删除，
     清理结果写入 detail；清理自身异常吞掉并附注。

场景库：evalkit/scenarios/*.yaml（yaml.safe_load），mode 字段区分
decay / reactivation_contrast。
"""
from __future__ import annotations

import os
import traceback
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import yaml

from evalkit.config import EvalConfig
from evalkit.judge import JudgeUnavailableError, build_judge
from evalkit.store import EvalStore
from evalkit.suites._registry_core import register_suite
from evalkit.target import TargetClient, TargetHttpError, build_client

# 场景目录锚定到包内（基于 __file__ 解析，禁止相对路径漂移）
_SCENARIOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios"
)

RETAINED_SCORE_MIN = 3            # memory_accuracy >= 3 记"保持"
MONOTONIC_TOLERANCE = 0.1         # 单调检查允许的回升容差
REACTIVATION_ENDPOINT_DAYS = 365  # 再激活对照终点：1 年
REACTIVATED_TAG = "reactivated"   # 再激活组种子 tag 标记
ONE_YEAR_DAYS = 365               # 1 年保持率检查键
_EPS = 1e-9                       # 浮点比较容差

GROUP_OVERALL = "overall"
GROUP_PERMANENT = "permanent"
GROUP_LOW = "importance_low(1-2)"
GROUP_MID = "importance_mid(3)"
GROUP_HIGH = "importance_high(4-5)"

HIT_BOTH = "both"                          # 检索命中且答出
HIT_RETRIEVED_NOT_ANSWERED = "retrieved_not_answered"  # 检索到但答不出
HIT_NOT_RETRIEVED = "not_retrieved"        # 检索不到
HIT_RETRIEVED_UNJUDGED = "retrieved_unjudged"  # 检索命中但 judge 缺失（不可用/失败）

# 背景干扰记忆（默认集）：模拟真实记忆库规模，填满注入槽（inject_memories_count，
# 现为 5）制造排名竞争——遗忘的执行者是 top-k 竞争淘汰：低重要性/深度衰减记忆
# 排名塌缩被挤出注入窗口，agent 真实"忘记"；每月重访的再激活记忆靠 reactivation
# 加成挤回排名，为"再激活对照"指标提供区分度。内容须与评测问题语义无关，
# importance 混合 3/4（压过 imp≤2 衰减种子、不压 imp4-5 直接提问种子）。
DEFAULT_BACKGROUND_MEMORIES: List[Dict[str, Any]] = [
    {"content": "用户家的 Wi-Fi 密码贴在路由器底座上", "importance": 4},
    {"content": "用户去年双十一买过一台空气炸锅", "importance": 3},
    {"content": "用户说小区门口新开了一家兰州拉面馆", "importance": 3},
    {"content": "用户的工作电脑是公司配发的笔记本电脑", "importance": 4},
    {"content": "用户提到过办公桌靠窗，下午会有点晒", "importance": 3},
    {"content": "用户的手机壳是深蓝色的", "importance": 3},
    {"content": "用户通勤主要坐地铁，通勤大约四十分钟", "importance": 4},
    {"content": "用户说过不太会做饭，常点外卖", "importance": 3},
    {"content": "用户家里的绿植是一盆绿萝", "importance": 3},
    {"content": "用户提到过自己不喜欢香菜", "importance": 3},
    {"content": "用户的伞是黑色的长柄伞", "importance": 3},
    {"content": "用户说过周末偶尔会睡到中午", "importance": 3},
    {"content": "用户的鼠标是无线的双飞燕", "importance": 3},
    {"content": "用户提到过楼下的便利店晚上十一点关门", "importance": 3},
    {"content": "用户说过他的水杯是保温杯，白色的", "importance": 3},
    {"content": "用户提到过他家电梯需要刷门禁卡", "importance": 3},
    {"content": "用户说过他喜欢喝常温的水", "importance": 3},
    {"content": "用户的椅子是电竞椅，黑红配色", "importance": 4},
    {"content": "用户提到过阳台上有个晾衣架坏了", "importance": 3},
    {"content": "用户说过他一般在十一点半左右睡觉", "importance": 4},
]


# ---------------------------------------------------------------------------
# 场景库加载
# ---------------------------------------------------------------------------
def load_scenarios(scenarios_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载 scenarios 目录下全部 YAML 场景（按文件名升序），yaml.safe_load 读取。"""
    root = scenarios_dir or _SCENARIOS_DIR
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not name.endswith((".yaml", ".yml")):
            continue
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and data.get("scenario_id"):
            out.append(data)
    return out


def load_scenario(scenario_id: str, scenarios_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """按 scenario_id 加载单个场景；不存在返回 None。"""
    for scenario in load_scenarios(scenarios_dir):
        if str(scenario.get("scenario_id")) == scenario_id:
            return scenario
    return None


def build_judge_prompt(expected_fact: str, question: str, answer: str) -> str:
    """构造 judge prompt。

    约定（stub judge 与 fake judge 依赖此约定确定性判分）：
    prompt 中必须包含一行 `expected fact: {目标事实}` 和一段 `answer: {agent 回复}`。
    注意：answer: 之后不得再出现目标事实原文，避免误判。
    """
    return (
        "你是长期记忆保持评测裁判，判断 agent 回复是否保持了目标事实。\n"
        f"expected fact: {expected_fact}\n"
        f"question: {question}\n"
        f"answer: {answer}\n"
        "\n"
        "评分标准（scores.memory_accuracy，0-5）：5=准确说出目标事实；3=部分正确；1=遗忘或答错。\n"
        '仅输出 JSON：{"scores": {"memory_accuracy": <0-5>}, "reason": "<简要理由>"}'
    )


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _normalize_seeds(raw: List[Any]) -> List[Dict[str, Any]]:
    """归一化场景种子字段（id/content/importance/tags/permanent）。"""
    seeds: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        seeds.append(
            {
                "id": str(item.get("id")),
                "content": str(item.get("content", "")),
                "importance": int(item.get("importance", 3)),
                "tags": [str(t) for t in (item.get("tags") or [])],
                "permanent": bool(item.get("permanent", False)),
            }
        )
    return seeds


def _importance_group(importance: int) -> str:
    if importance <= 2:
        return GROUP_LOW
    if importance == 3:
        return GROUP_MID
    return GROUP_HIGH


def _extract_memory_ids(data: Any) -> set:
    """从 search/rag 返回体提取记忆 id 集合（兼容 memories/results 两种键）。"""
    ids: set = set()
    if not isinstance(data, dict):
        return ids
    items = data.get("memories") or data.get("results") or []
    for item in items:
        if isinstance(item, dict):
            mid = item.get("memory_id", item.get("id"))
            if mid is not None:
                try:
                    ids.add(int(mid))
                except (TypeError, ValueError):
                    continue
    return ids


def _rate(retained: int, total: int) -> Optional[float]:
    """保持率 = 保持数/该组种子数；分母为 0 时返回 None（不计入检查）。"""
    return round(retained / total, 6) if total > 0 else None


def _time_travel_safe(client: TargetClient, agent_id: str, shift_days: int, record: Dict[str, Any]) -> None:
    """time_travel 差分回拨；404（该 agent 无记忆）跳过并记注，其他异常上抛。

    tags=["eval"] 仅回拨种子：真实遗忘的本质是"老种子 vs 持续新进的记忆"竞争——
    若全表回拨，背景/对话记忆与种子同幅变老，时间通道在竞争中互相抵消，
    遗忘永远不会发生（新曲线 run 381c9467 全 1.0 的根因）。背景记忆
    （tag=eval-background）与对话记忆不回拨，保持新鲜以模拟真实记忆库更替。
    """
    try:
        client.time_travel(agent_id, shift_days, tags=["eval"])
    except TargetHttpError as exc:
        if exc.status_code == 404:
            record.setdefault("time_travel_notes", []).append(
                {"shift_days": shift_days, "skipped": "404 该 agent 无可操作记忆"}
            )
            return
        raise
    record["time_travel_shifts"].append(shift_days)


def _ask_case(
    client: TargetClient,
    judge: Any,
    agent_id: str,
    seed: Dict[str, Any],
    memory_id: int,
    question: str,
    interval_days: int,
    run_state: Dict[str, Any],
) -> Dict[str, Any]:
    """单案例：提问 → 检索命中判定 → judge 判分。retained=None 表示无有效判分（剔除分母）。"""
    resp = client.chat(question, agent_id)
    answer = str(resp.get("response", ""))
    search_ids = _extract_memory_ids(client.search_memories(question, agent_id, limit=5))
    rag_ids = _extract_memory_ids(client.rag_search(question, agent_id, limit=5))
    search_hit = memory_id in search_ids
    rag_hit = memory_id in rag_ids
    retrieved = search_hit or rag_hit

    case: Dict[str, Any] = {
        "interval_days": interval_days,
        "seed_id": seed["id"],
        "memory_id": memory_id,
        "importance": seed["importance"],
        "permanent": seed["permanent"],
        "expected_fact": seed["content"],
        "question": question,
        "answer": answer,
        "search_hit": search_hit,
        "rag_hit": rag_hit,
        "hit_type": HIT_NOT_RETRIEVED if not retrieved else None,
        "retained": None,
        "judge_scores": None,
        "judge_reason": None,
        "judge_failed": False,
        "judge_unavailable": False,
    }

    if run_state["judge_unavailable"]:
        case["judge_unavailable"] = True  # 首次不可用后终止对话层判分，后续案例直接跳过
    else:
        prompt = build_judge_prompt(seed["content"], question, answer)
        try:
            result = judge.score(prompt)
        except JudgeUnavailableError as exc:
            run_state["judge_unavailable"] = True
            run_state["judge_unavailable_reason"] = str(exc)
            case["judge_unavailable"] = True
            result = None
        if isinstance(result, dict):
            if result.get("judge_failed"):
                run_state["judge_failed_count"] += 1
                case["judge_failed"] = True
                case["judge_error"] = result.get("error")
            else:
                scores = result.get("scores") or {}
                try:
                    accuracy = float(scores.get("memory_accuracy", 0))
                except (TypeError, ValueError):
                    accuracy = 0.0
                case["judge_scores"] = scores
                case["judge_reason"] = result.get("reason")
                case["retained"] = accuracy >= RETAINED_SCORE_MIN

    # hit 类型：检索命中且答出=both；检索到但答不出=retrieved_not_answered；检索不到=not_retrieved
    if not retrieved:
        case["hit_type"] = HIT_NOT_RETRIEVED
    elif case["retained"] is True:
        case["hit_type"] = HIT_BOTH
    elif case["retained"] is False:
        case["hit_type"] = HIT_RETRIEVED_NOT_ANSWERED
    else:
        case["hit_type"] = HIT_RETRIEVED_UNJUDGED
    return case


def _accumulate_retention(case: Dict[str, Any], retention_acc: Dict[Any, Dict[str, List[int]]]) -> None:
    """把有有效判分的案例累计进 retention_acc[interval][group] = [retained, total]。"""
    if case["retained"] is None:
        return
    interval = case["interval_days"]
    groups = [GROUP_OVERALL]
    if case["permanent"]:
        groups.append(GROUP_PERMANENT)
    else:
        groups.append(_importance_group(case["importance"]))
    for group in groups:
        bucket = retention_acc[interval][group]
        bucket[0] += 1 if case["retained"] else 0
        bucket[1] += 1


def _accumulate_retrieval(case: Dict[str, Any], retrieval_acc: Dict[Any, Dict[str, List[int]]]) -> None:
    """检索命中率与 judge 无关，全部案例均累计（含 judge 不可用/失败案例）。"""
    interval = case["interval_days"]
    for method, hit in (("search", case["search_hit"]), ("rag", case["rag_hit"])):
        bucket = retrieval_acc[interval][method]
        bucket[0] += 1 if hit else 0
        bucket[1] += 1


# ---------------------------------------------------------------------------
# 场景执行流
# ---------------------------------------------------------------------------
def _run_decay_flow(
    client: TargetClient,
    judge: Any,
    agent_id: str,
    config: EvalConfig,
    run_state: Dict[str, Any],
    record: Dict[str, Any],
    seeds: List[Dict[str, Any]],
    seed_map: Dict[str, int],
    questions: Dict[str, str],
    retention_acc: Dict[Any, Dict[str, List[int]]],
    retrieval_acc: Dict[Any, Dict[str, List[int]]],
) -> None:
    """decay 模式：间隔升序差分回拨 → 逐 seed 提问+judge+检索命中。"""
    intervals = sorted({int(d) for d in config.memory_decay.interval_days})
    shift_so_far = 0
    for target_days in intervals:
        shift = target_days - shift_so_far
        if shift > 0:
            _time_travel_safe(client, agent_id, shift, record)
            shift_so_far += shift
            client.sync_decay()
        # 防历史泄漏：清空会话消息后再提问——上一时间点的问答对若留在会话里，
        # agent 会直接从对话历史复述答案，衰减/竞争被完全旁路（保持率虚高根因）。
        client.clear_session_messages(agent_id)
        for seed in seeds:
            question = questions.get(seed["id"])
            if not question:
                continue
            case = _ask_case(
                client, judge, agent_id, seed, seed_map[seed["id"]], question, target_days, run_state
            )
            record["cases"].append(case)
            _accumulate_retention(case, retention_acc)
            _accumulate_retrieval(case, retrieval_acc)


def _run_reactivation_flow(
    client: TargetClient,
    judge: Any,
    agent_id: str,
    config: EvalConfig,
    run_state: Dict[str, Any],
    record: Dict[str, Any],
    scenario: Dict[str, Any],
    seeds: List[Dict[str, Any]],
    seed_map: Dict[str, int],
    questions: Dict[str, str],
    react_acc: Dict[str, List[int]],
) -> None:
    """reactivation_contrast 模式：对照组不动，再激活组按月重访 recall，同终点对比。"""
    endpoint = int(scenario.get("endpoint_days") or REACTIVATION_ENDPOINT_DAYS)
    visit = int(config.memory_decay.reactivation_visit_every_days)
    reactivated_ids = {s["id"] for s in seeds if REACTIVATED_TAG in s["tags"]}
    groups: List[Tuple[str, List[Dict[str, Any]]]] = [
        ("control", [s for s in seeds if s["id"] not in reactivated_ids]),
        ("reactivated", [s for s in seeds if s["id"] in reactivated_ids]),
    ]
    record["reactivated_seed_ids"] = sorted(reactivated_ids)
    record["reactivation_recalls"] = []

    shifted = 0
    while visit > 0 and shifted + visit <= endpoint:
        _time_travel_safe(client, agent_id, visit, record)
        shifted += visit
        client.sync_decay()
        for seed in groups[1][1]:  # 再激活组逐条 recall（显式传 eval agent_id，防污染 default）
            client.recall(seed_map[seed["id"]], agent_id)
            record["reactivation_recalls"].append(seed["id"])
    if endpoint > shifted:  # 补齐到终点（如 365 = 12*30 + 5）
        _time_travel_safe(client, agent_id, endpoint - shifted, record)
        client.sync_decay()

    for group_name, group in groups:
        # 防历史泄漏：每组提问前清空会话（对照组先问会污染再激活组的历史）
        client.clear_session_messages(agent_id)
        for seed in group:
            question = questions.get(seed["id"])
            if not question:
                continue
            case = _ask_case(
                client, judge, agent_id, seed, seed_map[seed["id"]], question, endpoint, run_state
            )
            case["group"] = group_name
            record["cases"].append(case)
            if case["retained"] is not None:
                bucket = react_acc[group_name]
                bucket[0] += 1 if case["retained"] else 0
                bucket[1] += 1


def _run_scenario(
    scenario: Dict[str, Any],
    client: TargetClient,
    judge: Any,
    agent_id: str,
    config: EvalConfig,
    run_state: Dict[str, Any],
    detail: Dict[str, Any],
    retention_acc: Dict[Any, Dict[str, List[int]]],
    retrieval_acc: Dict[Any, Dict[str, List[int]]],
    react_acc: Dict[str, List[int]],
) -> None:
    """执行单场景：种入（逐条 create_memory，记录 memory_id↔seed 映射）→ 按模式流转。"""
    record: Dict[str, Any] = {
        "scenario_id": str(scenario.get("scenario_id", "unnamed")),
        "mode": str(scenario.get("mode", "decay")),
        "seeds": [],
        "cases": [],
        "time_travel_shifts": [],
    }
    detail["scenarios"].append(record)  # 先挂载再填充，中断时保留已完成部分

    seeds = _normalize_seeds(scenario.get("seeds") or [])
    questions = {
        str(q.get("seed_id")): str(q.get("question", ""))
        for q in (scenario.get("questions") or [])
        if isinstance(q, dict)
    }
    seed_map: Dict[str, int] = {}
    for seed in seeds:
        memory_id = client.create_memory(
            seed["content"],
            agent_id,
            memory_type="long_term",
            importance=seed["importance"],
            tags=seed["tags"],
            permanent=seed["permanent"],
        )
        seed_map[seed["id"]] = int(memory_id)
        record["seeds"].append(
            {
                "id": seed["id"],
                "memory_id": int(memory_id),
                "importance": seed["importance"],
                "permanent": seed["permanent"],
                "tags": seed["tags"],
            }
        )

    # 背景干扰记忆：模拟真实记忆库规模，填满注入槽制造 top-k 竞争淘汰
    # （遗忘的执行者）。场景 YAML 可用 background_memories 覆盖默认集，
    # 显式传 [] 关闭。不回拨时钟（保持"新鲜"以参与竞争）、不进判分映射。
    background_raw = scenario.get("background_memories", DEFAULT_BACKGROUND_MEMORIES)
    background: List[Dict[str, Any]] = []
    if isinstance(background_raw, list):
        for item in background_raw:
            if isinstance(item, dict) and item.get("content"):
                background.append(
                    {"content": str(item["content"]), "importance": int(item.get("importance", 3))}
                )
            elif isinstance(item, str):
                background.append({"content": item, "importance": 3})
    background_ids: List[int] = []
    for item in background:
        try:
            mid = client.create_memory(
                item["content"],
                agent_id,
                memory_type="long_term",
                importance=item["importance"],
                tags=["eval-background"],
                permanent=False,
            )
            background_ids.append(int(mid))
        except (TargetHttpError, ValueError):
            continue  # 单条背景失败不影响评测主流程
    record["background_memories"] = {
        "requested": len(background),
        "seeded": len(background_ids),
        "memory_ids": background_ids,
    }
    if background_ids:
        # 等向量化队列消化背景记忆，保证首轮 time_travel 前背景已可参与检索竞争
        import time as _time

        _time.sleep(min(15.0, 0.5 * len(background_ids)))

    if record["mode"] == "reactivation_contrast":
        _run_reactivation_flow(
            client, judge, agent_id, config, run_state, record, scenario, seeds, seed_map, questions, react_acc
        )
    else:
        _run_decay_flow(
            client, judge, agent_id, config, run_state, record, seeds, seed_map, questions,
            retention_acc, retrieval_acc,
        )


# ---------------------------------------------------------------------------
# 指标汇总与终态判定
# ---------------------------------------------------------------------------
def _check_monotonic(retention_matrix: Dict[Any, Dict[str, Optional[float]]]) -> List[Dict[str, Any]]:
    """劣化曲线单调不增检查：间隔升序保持率回升超过容差记违反相邻对。"""
    violations: List[Dict[str, Any]] = []
    last_seen: Dict[str, Tuple[int, float]] = {}
    for interval in sorted(retention_matrix):
        for group in sorted(retention_matrix[interval]):
            rate = retention_matrix[interval][group]
            if rate is None:
                continue
            if group in last_seen:
                prev_interval, prev_rate = last_seen[group]
                if rate - prev_rate > MONOTONIC_TOLERANCE + _EPS:
                    violations.append(
                        {
                            "group": group,
                            "prev_interval": prev_interval,
                            "curr_interval": interval,
                            "prev_rate": prev_rate,
                            "curr_rate": rate,
                        }
                    )
            last_seen[group] = (interval, rate)
    return violations


def _cleanup(client: TargetClient, agent_id: str) -> Dict[str, Any]:
    """物理清理 eval agent 全部记忆：list → batch_delete → 复核 remaining。"""
    items = client.list_memories(agent_id, limit=1000)
    ids: List[int] = []
    for item in items:
        if isinstance(item, dict):
            mid = item.get("memory_id", item.get("id"))
            if mid is not None:
                ids.append(int(mid))
    deleted = 0
    if ids:
        resp = client.batch_delete(ids, agent_id)
        deleted = int(resp.get("deleted", len(ids))) if isinstance(resp, dict) else len(ids)
    remaining = client.list_memories(agent_id, limit=1000)
    return {"attempted": len(ids), "deleted": deleted, "remaining": len(remaining)}


@register_suite("memory_decay")
def run_memory_decay(
    run_id: str,
    config: EvalConfig,
    store: EvalStore,
    *,
    client: Optional[TargetClient] = None,
    judge: Any = None,
    scenarios_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """长期记忆劣化评测 suite 入口。client/judge kwarg 注入供单测，默认自动构建。

    真实模式适配（实测发现）：主服务按 data/agents.json 校验 agent，虚拟
    eval-agent-{run_id} 不可用——改为按 run 注册一次性真实 agent（服务端生成 id），
    清理时 delete_agent 由服务端连带清理记忆表/Weaviate/图库，隔离性更强。
    """
    if client is None:
        client = build_client(config)
    if judge is None:
        judge = build_judge(config)
    agent_meta = client.create_eval_agent(run_id)
    agent_id = str(agent_meta["id"])
    detail: Dict[str, Any] = {
        "run_id": run_id,
        "agent_id": agent_id,
        "agent_name": agent_meta.get("name"),
        "suite": "memory_decay",
        "scenarios": [],
    }
    run_state: Dict[str, Any] = {
        "judge_unavailable": False,
        "judge_unavailable_reason": None,
        "judge_failed_count": 0,
    }
    retention_acc: Dict[Any, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    retrieval_acc: Dict[Any, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    react_acc: Dict[str, List[int]] = {"control": [0, 0], "reactivated": [0, 0]}
    error_text: Optional[str] = None

    try:
        for scenario in load_scenarios(scenarios_dir):
            _run_scenario(
                scenario, client, judge, agent_id, config, run_state, detail,
                retention_acc, retrieval_acc, react_acc,
            )
    except Exception as exc:  # 兜底：异常也先走 finally 清理，再终态化 error
        error_text = f"{exc}\n{traceback.format_exc()}"
    finally:
        try:
            cleanup_result = _cleanup(client, agent_id)
        except Exception as exc:  # 清理自身异常吞掉，附注记入 detail
            cleanup_result = {
                "attempted": 0,
                "deleted": 0,
                "remaining": None,
                "note": f"清理自身异常(已吞掉): {exc}",
            }
        try:
            # 删除一次性 eval agent：服务端连带清理记忆表/Weaviate/图库
            client.delete_agent(agent_id)
            cleanup_result["agent_deleted"] = True
        except Exception as exc:
            cleanup_result["agent_deleted"] = False
            cleanup_result["agent_delete_note"] = f"删除 eval agent 异常(已吞掉): {exc}"
        detail["cleanup"] = cleanup_result

    # ---- 指标汇总（summary 不放种子原文）----
    retention_matrix: Dict[Any, Dict[str, Optional[float]]] = {}
    for interval in sorted(retention_acc):
        retention_matrix[interval] = {
            group: _rate(bucket[0], bucket[1])
            for group, bucket in sorted(retention_acc[interval].items())
        }
    retrieval_hit_rate: Dict[str, Dict[Any, Optional[float]]] = {"search": {}, "rag": {}}
    for interval in sorted(retrieval_acc):
        for method in ("search", "rag"):
            bucket = retrieval_acc[interval][method]
            retrieval_hit_rate[method][interval] = _rate(bucket[0], bucket[1])
    monotonic_violations = _check_monotonic(retention_matrix)

    reactivation_contrast: Optional[Dict[str, Any]] = None
    if react_acc["control"][1] > 0 or react_acc["reactivated"][1] > 0:
        control_rate = _rate(*react_acc["control"])
        reactivated_rate = _rate(*react_acc["reactivated"])
        computable = control_rate is not None and reactivated_rate is not None
        reactivation_contrast = {
            "control": control_rate,
            "reactivated": reactivated_rate,
            "passes": bool(computable and reactivated_rate > control_rate),
            "computable": computable,
        }

    # ---- 终态判定 ----
    thresholds = config.thresholds.memory
    failure_reasons: List[str] = []
    if not error_text:
        for interval in sorted(retention_matrix):
            permanent_rate = retention_matrix[interval].get(GROUP_PERMANENT)
            if permanent_rate is not None and permanent_rate + _EPS < thresholds.permanent_retention:
                failure_reasons.append(
                    f"permanent 种子在 {interval} 天保持率 {permanent_rate} < {thresholds.permanent_retention}"
                )
        if monotonic_violations:
            failure_reasons.append(f"劣化曲线单调性违反 {len(monotonic_violations)} 处")
        if (
            thresholds.reactivation_must_beat_control
            and reactivation_contrast is not None
            and not reactivation_contrast["passes"]
        ):
            failure_reasons.append(
                f"再激活组保持率 {reactivation_contrast['reactivated']} 未胜过对照组 "
                f"{reactivation_contrast['control']}"
            )
        one_year_rate = retention_matrix.get(ONE_YEAR_DAYS, {}).get(GROUP_OVERALL)
        if one_year_rate is not None and one_year_rate + _EPS < thresholds.retention_1y_min:
            failure_reasons.append(
                f"1 年 overall 保持率 {one_year_rate} < {thresholds.retention_1y_min}"
            )

    if error_text:
        status = "error"
    elif run_state["judge_unavailable"]:
        status = "judge_unavailable"
    elif failure_reasons:
        status = "failed"
    else:
        status = "passed"

    metrics: Dict[str, Any] = {
        "retention_matrix": retention_matrix,
        "retrieval_hit_rate": retrieval_hit_rate,
        "monotonic_violations": monotonic_violations,
        "reactivation_contrast": reactivation_contrast,
        "judge_failed_count": run_state["judge_failed_count"],
        "judge_unavailable": run_state["judge_unavailable"],
        "failure_reasons": failure_reasons,
    }

    store.finish_run(run_id, status, metrics_summary=metrics, error=error_text)
    detail["status"] = status
    detail["error"] = error_text
    store.save_run_artifacts(run_id, detail)
    return metrics
