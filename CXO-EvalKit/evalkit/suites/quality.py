"""LLM 评判质量 suite（quality）。

评测范围:
1. 回放: SCRIPTS 固定回放脚本（陪伴语境中文，每脚本多轮固定用户消息）逐轮
   client.chat(message, agent_id="eval-agent-{run_id}")（隔离约定；quality 只读
   对话，不种记忆不清理）。
2. 判分: 每轮回复一个 judge 案例，prompt 含本轮上下文（用户消息 + agent 回复）、
   `expected fact:` 期望要点行与 `answer:` 回复段（stub judge 依赖此约定确定性
   判分）。维度固定三维: memory_accuracy / persona_consistency / coherence（1-5）。
   judge 网络失败已在 judge 内部重试 ≤2 次，suite 不再重试。

失败口径:
- 某轮 TargetHttpError/TargetError → 记入 failed_turns 并继续；
  全部轮失败 → finish_run(error)。
- JudgeUnavailableError（judge 服务网络层不可用）→ 整个 run 降级
  finish_run(judge_unavailable)，此时无判分数据，summary 只留 failed 结构。
- 单案例 judge 输出不可解析（{"judge_failed": True}）→ 计 judge_failed_count；
  全部案例 judge_failed（成功判分数=0 且非 judge_unavailable）→ finish_run(error)。

终态判定: 有判分数据时 overall_avg（三维全案例均分的均值）
≥ config.thresholds.quality.avg_min（默认 3.5）→ passed，否则 failed。

汇总（metrics_summary）: 每维 mean/std（总体标准差）/count（成功判分数）、
overall_avg、low_scores（任一维 < 3 分的案例清单，含回复原文与判分理由，
summary 与 detail 均保留）、judge_failed_count、failed_turns。

明细（save_run_artifacts）: 逐脚本逐轮完整记录（用户消息/回复/judge prompt/
scores/reason）；正常案例回复原文只进 detail（low_scores 案例在 summary 保留原文）。

纯函数: mean/_pstd（总体标准差）与 TargetClient/JudgeClient 解耦，
Mock 注入单测下统计口径经手工精确值断言保证。

终态义务: suite 结束调用 store.finish_run(run_id, status, metrics_summary=summary)，
status ∈ {"passed", "failed", "judge_unavailable", "error"}；明细经
store.save_run_artifacts(run_id, detail) 落盘；返回值即 metrics_summary。
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from evalkit.config import EvalConfig
from evalkit.judge import JudgeUnavailableError
from evalkit.suites._registry_core import register_suite
from evalkit.target import TargetError

if TYPE_CHECKING:
    from evalkit.store import EvalStore

SUITE_NAME = "quality"
# 判分维度（固定三维，1-5 分）
SCORE_DIMENSIONS = ("memory_accuracy", "persona_consistency", "coherence")
LOW_SCORE_THRESHOLD = 3.0  # 任一维 < 3 分 → 记入 low_scores

# 回放脚本: 陪伴语境中文固定对话（turns 与 expects 逐轮对齐，expects 单行文本，
# 供 judge prompt 的 expected fact 行——stub judge 按单行正则提取）
SCRIPTS: List[Dict[str, Any]] = [
    {
        "script_id": "evening_debrief",
        "description": "晚间倾诉：加班疲惫与情绪回应的陪伴对话",
        "turns": [
            "今天加班到九点才到家，累得一句话都不想说。",
            "会上方案被领导当众否了，其实那版是我熬了两个晚上赶出来的。",
            "回来路上买了份炸鸡，吃着吃着眼泪就下来了，我是不是太没出息了。",
            "算了不说了，周末想一个人去海边待两天，你觉得这个主意怎么样？",
        ],
        "expects": [
            "reply 接住了用户的疲惫情绪并表达关心",
            "reply 站在用户一边肯定其付出并提到方案被否这件事",
            "reply 安慰用户哭出来没关系并宽慰其不必自责",
            "reply 呼应了去海边休息的愿望并给出温暖建议",
        ],
    },
    {
        "script_id": "old_photo_memory",
        "description": "旧照片回忆：室友往事与人际疏远的陪伴对话",
        "turns": [
            "周末翻旧照片，看到大学时和室友在天台吃泡面的合照，突然好想她们。",
            "那时候我们总在熄灯后聊到半夜，聊未来聊到睡不着。",
            "上个月给其中一个室友发消息，她到现在都没回，我有点失落。",
            "你说人与人是不是走着走着就散了？",
        ],
        "expects": [
            "reply 回应了用户对室友的想念并提到天台吃泡面的合照",
            "reply 呼应了熄灯后卧谈聊到半夜的回忆细节",
            "reply 安抚了用户对室友未回消息的失落",
            "reply 温柔回应了人际关系疏远的话题并给出慰藉",
        ],
    },
]

_JUDGE_PROMPT_TEMPLATE = (
    "你是中文陪伴语境下的对话质量评判员。请依据「期望事实要点」与「agent 回复」，"
    "从 memory_accuracy（记忆与事实准确）、persona_consistency（陪伴人设一致性）、"
    "coherence（对话连贯性）三个维度分别打 1-5 分，并输出 JSON：\n"
    '{{"scores": {{"memory_accuracy": <1-5>, "persona_consistency": <1-5>, '
    '"coherence": <1-5>}}, "reason": "<评分理由>"}}\n'
    "\n"
    "[本轮对话]\n"
    "用户消息: {message}\n"
    "agent 回复: {reply}\n"
    "\n"
    "expected fact: {expect}\n"
    "answer: {reply}"
)


def _now() -> str:
    """UTC ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _error_label(exc: BaseException) -> str:
    """异常统一标签（类型名: 消息），供失败明细记录。"""
    return f"{type(exc).__name__}: {exc}"


def _round3(value: Optional[float]) -> Optional[float]:
    """统计值统一保留 3 位小数；None 透传。"""
    return None if value is None else round(float(value), 3)


def mean(values: Sequence[float]) -> float:
    """算术均值（空集由调用方保证不传入）。"""
    return sum(float(v) for v in values) / len(values)


def _pstd(values: Sequence[float]) -> float:
    """总体标准差（除以 n，非样本标准差）。空集返回 0.0。"""
    if not values:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((float(v) - avg) ** 2 for v in values) / len(values))


def build_judge_prompt(message: str, reply: str, expect: str) -> str:
    """构造 judge 评判 prompt。

    约定（stub judge 依赖）: 含单行 `expected fact: {期望要点}` 与 `answer: {回复}`
    段；其余说明文字不得出现 `expected fact:` / `answer:` 字样以免误提取。
    """
    return _JUDGE_PROMPT_TEMPLATE.format(message=message, reply=reply, expect=expect)


def _failed_summary(
    suite_status: str,
    started_at: str,
    agent_id: str,
    avg_min: float,
    judge_failed_count: int,
    failed_turns: List[Dict[str, Any]],
    error: str,
) -> Dict[str, Any]:
    """error / judge_unavailable 终态的 summary（failed 结构，无判分统计）。"""
    return {
        "suite": SUITE_NAME,
        "status": suite_status,
        "started_at": started_at,
        "finished_at": _now(),
        "config": {"agent_id": agent_id, "avg_min": avg_min},
        "judge_failed_count": judge_failed_count,
        "failed_turns": failed_turns,
        "error": error,
    }


def _write_terminal(
    store: "EvalStore",
    run_id: str,
    summary: Dict[str, Any],
    detail: Dict[str, Any],
    error: Optional[str],
) -> None:
    """统一终态: 明细落盘 + finish_run 终态化。"""
    store.save_run_artifacts(run_id, detail)
    store.finish_run(run_id, summary["status"], metrics_summary=summary, error=error)


@register_suite(SUITE_NAME)
def run_quality_suite(
    run_id: str,
    config: EvalConfig,
    store: "EvalStore",
    *,
    client: Optional[Any] = None,
    judge: Optional[Any] = None,
) -> Dict[str, Any]:
    """质量评测主流程（签名约定: (run_id, config, store, *, client=None, judge=None)）。

    client/judge 为 None 时经 build_client / build_judge 构造（Mock 模式自动接
    stub）；kwarg 注入供单测使用。返回值即 metrics_summary（JSON 可序列化）；
    suite 内部完成 finish_run 终态化与 save_run_artifacts 明细落盘。
    """
    started_at = _now()
    if client is None:
        from evalkit.target import build_client  # 局部导入避免环

        client = build_client(config)
    if judge is None:
        from evalkit.judge import build_judge  # 局部导入避免环

        judge = build_judge(config)

    agent_meta = client.create_eval_agent(run_id)  # 真实模式：须注册真实 agent（服务端生成 id）
    agent_id = str(agent_meta["id"])
    avg_min = float(config.thresholds.quality.avg_min)

    def _finish(store, run_id, summary, detail, error):
        """终态化前删除一次性 eval agent（服务端连带清理记忆表/向量/图），异常吞掉。"""
        try:
            client.delete_agent(agent_id)
            detail.setdefault("cleanup", {})["agent_deleted"] = True
        except TargetError as exc:
            detail.setdefault("cleanup", {})["agent_deleted"] = False
            detail["cleanup"]["note"] = f"删除 eval agent 异常(已吞掉): {exc}"
        _write_terminal(store, run_id, summary, detail, error)  # 原始终态化（勿改为 _finish）

    # ---- 回放阶段: 逐脚本逐轮 chat，网络失败记入 failed_turns 并继续 ----
    failed_turns: List[Dict[str, Any]] = []
    turn_records: List[Dict[str, Any]] = []  # 成功获得回复的轮（同 detail 引用）
    detail_scripts: List[Dict[str, Any]] = []
    total_turns = 0
    for script in SCRIPTS:
        script_id = script["script_id"]
        expects: List[str] = script["expects"]
        script_entry: Dict[str, Any] = {
            "script_id": script_id,
            "description": script["description"],
            "turns": [],
        }
        for turn_index, message in enumerate(script["turns"]):
            total_turns += 1
            try:
                data = client.chat(message, agent_id=agent_id)
            except TargetError as exc:  # 含 TargetHttpError
                failed_turns.append(
                    {"script_id": script_id, "turn_index": turn_index, "error": _error_label(exc)}
                )
                script_entry["turns"].append(
                    {
                        "turn_index": turn_index,
                        "user_message": message,
                        "reply": None,
                        "network_error": _error_label(exc),
                    }
                )
                continue
            reply = str(data.get("response", ""))
            rec: Dict[str, Any] = {
                "script_id": script_id,
                "turn_index": turn_index,
                "user_message": message,
                "reply": reply,
                "expect": expects[turn_index] if turn_index < len(expects) else "（期望要点缺失）",
            }
            turn_records.append(rec)
            script_entry["turns"].append(rec)
        detail_scripts.append(script_entry)

    # ---- 全部轮网络失败 → error（无回复可判分）----
    if not turn_records:
        error = f"全部 {total_turns} 轮对话失败（TargetError/TargetHttpError），无回复可判分"
        summary = _failed_summary("error", started_at, agent_id, avg_min, 0, failed_turns, error)
        detail = {
            "suite": SUITE_NAME,
            "run_id": run_id,
            "status": "error",
            "agent_id": agent_id,
            "scripts": detail_scripts,
            "summary": summary,
        }
        _finish(store, run_id, summary, detail, error)
        return summary

    # ---- 判分阶段: 每轮回复一个 judge 案例；judge 重试已内部完成，不重试 ----
    scored: List[Dict[str, Any]] = []  # [{"record": rec, "scores": {dim: float}}]
    low_scores: List[Dict[str, Any]] = []
    judge_failed_count = 0
    judge_unavailable_error: Optional[str] = None

    for rec in turn_records:
        prompt = build_judge_prompt(rec["user_message"], rec["reply"], rec["expect"])
        rec["judge_prompt"] = prompt
        try:
            result = judge.score(prompt)
        except JudgeUnavailableError as exc:
            judge_unavailable_error = _error_label(exc)
            break  # judge 服务不可用 → 整个 run 降级
        if isinstance(result, dict) and result.get("judge_failed"):
            judge_failed_count += 1
            rec["judge_failed"] = True
            rec["judge_error"] = str(result.get("error", ""))
            continue
        raw_scores = result.get("scores") or {}
        scores: Dict[str, float] = {}
        for dim in SCORE_DIMENSIONS:
            value = raw_scores.get(dim)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                scores[dim] = float(value)
        rec["judge_failed"] = False
        rec["scores"] = scores
        rec["reason"] = str(result.get("reason", ""))
        if scores:
            scored.append({"record": rec, "scores": scores})
            if any(v < LOW_SCORE_THRESHOLD for v in scores.values()):
                low_scores.append(
                    {
                        "script_id": rec["script_id"],
                        "turn_index": rec["turn_index"],
                        "scores": dict(scores),
                        "reason": rec["reason"],
                        "reply": rec["reply"],
                    }
                )

    def _detail(status: str) -> Dict[str, Any]:
        return {
            "suite": SUITE_NAME,
            "run_id": run_id,
            "status": status,
            "agent_id": agent_id,
            "scripts": detail_scripts,
            "low_scores": low_scores,
        }

    # ---- judge 服务不可用 → 整个 run 降级（无判分数据，只留 failed 结构）----
    if judge_unavailable_error is not None:
        error = f"judge 服务不可用（JudgeUnavailableError），整个 run 降级: {judge_unavailable_error}"
        summary = _failed_summary(
            "judge_unavailable", started_at, agent_id, avg_min, judge_failed_count,
            failed_turns, error,
        )
        detail = _detail("judge_unavailable")
        detail["summary"] = summary
        _finish(store, run_id, summary, detail, error)
        return summary

    # ---- 全案例 judge_failed（成功判分数=0 且非 judge_unavailable）→ error ----
    if not scored:
        error = (
            f"全部 {judge_failed_count} 个 judge 案例判分失败（judge_failed），"
            "无可统计判分数据"
        )
        summary = _failed_summary(
            "error", started_at, agent_id, avg_min, judge_failed_count, failed_turns, error
        )
        detail = _detail("error")
        detail["summary"] = summary
        _finish(store, run_id, summary, detail, error)
        return summary

    # ---- 汇总: 每维 mean/std（总体标准差）/count + overall_avg + 终态判定 ----
    dimensions: Dict[str, Dict[str, Any]] = {}
    for dim in SCORE_DIMENSIONS:
        values = [c["scores"][dim] for c in scored if dim in c["scores"]]
        dimensions[dim] = {
            "count": len(values),
            "mean": _round3(mean(values)) if values else None,
            "std": _round3(_pstd(values)) if values else None,
        }
    case_avgs = [
        mean([c["scores"][d] for d in SCORE_DIMENSIONS if d in c["scores"]]) for c in scored
    ]
    overall_avg = mean(case_avgs)
    passed = overall_avg >= avg_min

    summary: Dict[str, Any] = {
        "suite": SUITE_NAME,
        "status": "passed" if passed else "failed",
        "started_at": started_at,
        "finished_at": _now(),
        "config": {
            "agent_id": agent_id,
            "scripts": [s["script_id"] for s in SCRIPTS],
            "turn_count": total_turns,
        },
        "thresholds": {"avg_min": avg_min},
        "dimensions": dimensions,
        "overall_avg": _round3(overall_avg),
        "judgment": {
            "overall_avg": _round3(overall_avg),
            "threshold_avg_min": avg_min,
            "passed": passed,
        },
        "judge_failed_count": judge_failed_count,
        "failed_turns": failed_turns,
        "low_scores": low_scores,
        "scored_case_count": len(scored),
    }

    detail = _detail(summary["status"])
    detail["summary"] = summary
    _finish(store, run_id, summary, detail, None)
    return summary
