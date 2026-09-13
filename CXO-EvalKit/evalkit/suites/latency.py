"""延迟评测 suite（latency）。

测量范围:
1. E2E 对话延迟: PROBES 探针 × config.latency.rounds 轮 chat（agent_id="default"，
   只读对话不种记忆），取 TargetClient 客户端计时 elapsed_ms。
2. 检索延迟: RETRIEVAL_QUERIES 固定查询 × search_memories / rag_search
   （limit=RETRIEVAL_LIMIT）× RETRIEVAL_ROUNDS 轮，各自输出 P50/P95。
3. 并发退化: config.latency.concurrency_levels 各档执行一轮全探针
   （concurrent.futures.ThreadPoolExecutor），输出各档 P50/P95、失败率，
   以及相对 1 并发的 P95 退化倍率（P95 并发档 / P95 并发1）。
4. 基线对比: config.latency.baseline_run_id 非空时，从 store 读取基线 run 的
   metrics_summary（同结构，读 overall.p50/p95），输出变化量 ms、变化百分比与
   regressed 标记；基线不存在或结构缺失 → 对比段标 baseline_missing=true（不报错）。
5. 全双工语音链路（REST 探测完成后追加）: config.latency.ws_full_duplex.enabled 且非
   mock 模式时，经 WS voice.dual_stream 逐轮探测语音链路（音频流→ASR→LLM→TTS 首包），
   主指标 = speech_end → tts_first_audio 的 P95（能量法"说完"→ 首包音频，用户体感
   口径，含容器分句等待；服务端 VAD 不参与判定），阈值
   config.thresholds.latency.ws_p95_ms（=阈值判达标）；speech_end_to_first_audio 无样本
   （全部超时/错误）→ 判失败并注明"全双工无有效轮次"；WsProbeError（探测不可用，
   如音频资产缺失）→ 记入 ws_full_duplex.error。mock 模式无 WS stub / 配置禁用 →
   skipped（不影响终态）。全双工判定与既有 REST 阈值判定取与，共同决定 run 终态。

失败口径:
- TargetHttpError（主服务返回 4xx/5xx，业务失败）→ 计入失败率，继续跑完不中断；
- 连接层失败（TargetError 非 HTTP 语义 / httpx 传输错误 / OSError / TimeoutError）
  → 仅当"首个探针请求"（全 run 第 1 次 chat 调用）即失败时判定主服务不可达
  （finish_run(error)）；其余情况一律计入失败率继续。

阈值判定: 总体 P95 ≤ config.thresholds.latency.p95_ms → passed，否则 failed；
无成功样本（P95 为 None）→ failed。summary 与 detail 均体现判定。

分位数算法: percentile() 线性插值法（与 numpy 默认一致）。
"原始样本列表 → 统计 dict"抽为纯函数 summarize()，与 TargetClient 解耦——
MockTransport 单测下 elapsed 近 0 且统计口径需独立验证，分位数正确性经
summarize/percentile 直接单测保证。

终态义务: suite 结束调用 store.finish_run(run_id, status, metrics_summary=summary)，
status ∈ {"passed", "failed", "error"}（latency 不依赖 judge，不使用 judge_unavailable）；
明细经 store.save_run_artifacts(run_id, detail) 落盘；返回值即 metrics_summary。
"""
from __future__ import annotations

import concurrent.futures
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import httpx

from evalkit.config import EvalConfig
from evalkit.suites._registry_core import register_suite
from evalkit.target import TargetClient, TargetError, TargetHttpError
from evalkit.ws_probe import FullDuplexProbe, WsProbeError, summarize_ws_turns

if TYPE_CHECKING:
    from evalkit.store import EvalStore

SUITE_NAME = "latency"
AGENT_ID = "default"  # 延迟探针走 default agent，只读对话不种记忆
RETRIEVAL_LIMIT = 5
RETRIEVAL_ROUNDS = 5

# 探针集: 长短混合中文陪伴语境消息（一句话问候 → 三行生活倾诉），每条带 id
PROBES: List[Dict[str, str]] = [
    {"id": "greet_short", "message": "在吗？"},
    {"id": "greet_morning", "message": "早上好呀，今天天气不错，你那边怎么样？"},
    {"id": "daily_medium", "message": "今天上班有点累，晚上想看点轻松的东西，有什么推荐吗？"},
    {
        "id": "mood_long",
        "message": (
            "最近有点迷茫，工作节奏很快，感觉自己一直在赶进度，很难停下来好好想想"
            "自己真正想要什么。\n你也会有这种感觉吗？如果有的话，你一般是怎么调适的？"
        ),
    },
    {
        "id": "story_long",
        "message": (
            "跟你说个事，今天回家路上遇到一只流浪猫，蹲在便利店门口，看起来好几天没吃东西了。\n"
            "我买了点火腿肠喂它，它吃完也不走，就那样一直看着我。\n"
            "我有点纠结要不要带回家养，又担心自己照顾不好它。"
        ),
    },
    {
        "id": "nostalgia_long",
        "message": (
            "这周末整理旧照片，翻到几年前的旅行合集，突然特别想念那时候的自己，说走就走，也不怕迷路。\n"
            "现在做任何决定之前都要反复权衡，好像快乐变复杂了。\n"
            "你会怀念以前的自己吗？还是觉得成长本来就是这样？"
        ),
    },
    {"id": "goodnight_short", "message": "晚安，做个好梦。"},
]

# 检索延迟固定查询（search_memories 与 rag_search 共用）
RETRIEVAL_QUERIES: List[Dict[str, str]] = [
    {"id": "q_self_preference", "query": "我之前说过自己喜欢的电影是什么来着？"},
    {"id": "q_recent_event", "query": "帮我回忆一下我上周提到的那家餐厅叫什么名字。"},
]

# 计入失败率的异常集合: 业务 HTTP 错误 + 连接层/传输层失败
_FAILURE_ERRORS = (TargetError, httpx.HTTPError, OSError, TimeoutError)


class _TargetUnreachable(Exception):
    """首个探针请求即连接层失败 → 主服务不可达，run 终态 error。"""


def _now() -> str:
    """UTC ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _error_label(exc: BaseException) -> str:
    """异常统一标签（类型名: 消息），供失败明细记录。"""
    return f"{type(exc).__name__}: {exc}"


def _round3(value: Optional[float]) -> Optional[float]:
    """统计值统一保留 3 位小数；None 透传。"""
    return None if value is None else round(float(value), 3)


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    """线性插值分位数（与 numpy 默认 percentile 一致）。

    空集返回 None；单元素返回该值；p 自动截断到 [0, 100]。
    """
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    p = min(100.0, max(0.0, float(p)))
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def summarize(samples: Sequence[float]) -> Dict[str, Any]:
    """纯函数: 原始延迟样本列表 → 统计 dict（count/mean/P50/P95/P99/min/max）。

    与 TargetClient 解耦，便于在 MockTransport（elapsed 近 0）下单测分位数正确性。
    空样本集返回 count=0 且各统计值为 None。
    """
    if not samples:
        return {
            "count": 0,
            "mean": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "min": None,
            "max": None,
        }
    values = [float(v) for v in samples]
    return {
        "count": len(values),
        "mean": _round3(sum(values) / len(values)),
        "p50": _round3(percentile(values, 50)),
        "p95": _round3(percentile(values, 95)),
        "p99": _round3(percentile(values, 99)),
        "min": _round3(min(values)),
        "max": _round3(max(values)),
    }


def compare_baseline_metrics(
    current_overall: Dict[str, Any],
    baseline_overall: Dict[str, Any],
    regression_pct: float,
) -> Dict[str, Any]:
    """纯函数: 当前总体统计 vs 基线总体统计，对比 P50/P95。

    变化百分比 = (当前 - 基线) / 基线 * 100；正值代表劣化。
    |pct| > regression_pct 且为正 → 该指标 regressed=true；
    顶层 regressed 由 P95 驱动（延迟回归以 P95 为准）。
    任一侧指标缺失 → 对应条目标 missing=true，regressed 保持 false。
    """
    comparison: Dict[str, Any] = {"regressed": False, "metrics": {}}
    for name in ("p50", "p95"):
        current = current_overall.get(name)
        baseline = baseline_overall.get(name)
        if current is None or baseline is None:
            comparison["metrics"][name] = {"missing": True}
            continue
        base_ms = float(baseline)
        cur_ms = float(current)
        delta_ms = cur_ms - base_ms
        delta_pct = (delta_ms / base_ms * 100.0) if base_ms != 0 else None
        regressed = bool(
            delta_pct is not None and delta_pct > 0 and abs(delta_pct) > regression_pct
        )
        comparison["metrics"][name] = {
            "current_ms": _round3(cur_ms),
            "baseline_ms": _round3(base_ms),
            "delta_ms": _round3(delta_ms),
            "delta_pct": _round3(delta_pct) if delta_pct is not None else None,
            "regressed": regressed,
        }
    p95_entry = comparison["metrics"].get("p95", {})
    if isinstance(p95_entry, dict) and not p95_entry.get("missing"):
        comparison["regressed"] = bool(p95_entry.get("regressed"))
    return comparison


def _sanitize_levels(raw: Any) -> List[int]:
    """并发档位清洗: 去重、升序、剔除非正整数；空则回退 [1]。"""
    levels = sorted({int(v) for v in (raw or [1]) if int(v) >= 1})
    return levels or [1]


def _chat_once(client: TargetClient, message: str, timeout: float) -> float:
    """单次 chat 采样，返回客户端计时 elapsed_ms。"""
    result = client.chat(message, agent_id=AGENT_ID, timeout=timeout)
    return float(result["elapsed_ms"])


def _degradation_ratios(
    levels_stats: Dict[str, Dict[str, Any]], levels: List[int]
) -> Dict[str, Any]:
    """各档相对 1 并发的 P95 退化倍率。

    基准（并发 1）不可用或该档无成功样本 → p95_ratio 置 None 并注明原因。
    """
    base_p95 = levels_stats.get("1", {}).get("p95")
    out: Dict[str, Any] = {}
    for level in levels:
        key = str(level)
        p95 = levels_stats[key]["p95"]
        if key == "1":
            out[key] = {"p95_ratio": 1.0 if p95 is not None else None}
        elif base_p95 is None or base_p95 <= 0 or p95 is None:
            out[key] = {"p95_ratio": None, "note": "并发1基准P95不可用或本档无成功样本"}
        else:
            out[key] = {"p95_ratio": round(p95 / base_p95, 4)}
    return out


def _run_e2e_phase(
    client: TargetClient, rounds: int, timeout: float
) -> Dict[str, Any]:
    """E2E 阶段: 每条探针 × rounds 轮 chat 采样。

    返回 {"samples_by_probe": {probe_id: [elapsed_ms]}, "failures": [...], "rounds": rounds}。
    全 run 第 1 次 chat 即连接层失败 → 抛 _TargetUnreachable（主服务不可达）。
    """
    samples_by_probe: Dict[str, List[float]] = {}
    failures: List[Dict[str, str]] = []
    attempt_index = 0
    for probe in PROBES:
        samples: List[float] = []
        for _ in range(rounds):
            try:
                elapsed = _chat_once(client, probe["message"], timeout)
            except _FAILURE_ERRORS as exc:
                if attempt_index == 0 and not isinstance(exc, TargetHttpError):
                    # 首个探针请求即连接层失败 → 主服务不可达
                    raise _TargetUnreachable(_error_label(exc)) from exc
                failures.append({"probe_id": probe["id"], "error": _error_label(exc)})
            else:
                samples.append(elapsed)
            attempt_index += 1
        samples_by_probe[probe["id"]] = samples
    return {"samples_by_probe": samples_by_probe, "failures": failures, "rounds": rounds}


def _run_retrieval_phase(
    client: TargetClient, timeout: float
) -> tuple[Dict[str, Dict[str, List[float]]], List[Dict[str, str]]]:
    """检索阶段: 固定查询 × search_memories / rag_search（limit=5）× RETRIEVAL_ROUNDS 轮。

    失败计入各自 failed_count，不中断。返回 (原始样本, 失败明细)。
    """
    raw: Dict[str, Dict[str, List[float]]] = {
        "search_memories": {q["id"]: [] for q in RETRIEVAL_QUERIES},
        "rag_search": {q["id"]: [] for q in RETRIEVAL_QUERIES},
    }
    failures: List[Dict[str, str]] = []
    for query in RETRIEVAL_QUERIES:
        for method in ("search_memories", "rag_search"):
            for _ in range(RETRIEVAL_ROUNDS):
                try:
                    if method == "search_memories":
                        result = client.search_memories(
                            query["query"], agent_id=AGENT_ID,
                            limit=RETRIEVAL_LIMIT, timeout=timeout,
                        )
                    else:
                        result = client.rag_search(
                            query["query"], agent_id=AGENT_ID,
                            limit=RETRIEVAL_LIMIT, timeout=timeout,
                        )
                    raw[method][query["id"]].append(float(result["elapsed_ms"]))
                except _FAILURE_ERRORS as exc:
                    failures.append(
                        {"endpoint": method, "query_id": query["id"], "error": _error_label(exc)}
                    )
    return raw, failures


def _run_concurrency_phase(
    client: TargetClient, levels: List[int], timeout: float
) -> Dict[int, Dict[str, Any]]:
    """并发阶段: 各档一轮全探针（线程池），失败计入该档 failed_count。

    返回 {level: {"samples": [...], "failures": [...]}}。
    """
    raw: Dict[int, Dict[str, Any]] = {}
    for level in levels:
        samples: List[float] = []
        failures: List[Dict[str, str]] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=level, thread_name_prefix=f"latency-l{level}"
        ) as pool:
            future_to_probe = {
                pool.submit(_chat_once, client, probe["message"], timeout): probe["id"]
                for probe in PROBES
            }
            for future in concurrent.futures.as_completed(future_to_probe):
                probe_id = future_to_probe[future]
                try:
                    samples.append(future.result())
                except _FAILURE_ERRORS as exc:
                    failures.append({"probe_id": probe_id, "error": _error_label(exc)})
        raw[level] = {"samples": samples, "failures": failures}
    return raw


def _build_baseline_section(
    store: "EvalStore", config: EvalConfig, overall: Dict[str, Any]
) -> Dict[str, Any]:
    """基线对比段: 基线缺失/结构缺失 → baseline_missing=true（不报错）。"""
    baseline_run_id = config.latency.baseline_run_id
    section: Dict[str, Any] = {"baseline_run_id": baseline_run_id, "baseline_missing": False}
    if not baseline_run_id:
        section["baseline_missing"] = True
        section["reason"] = "未配置 baseline_run_id"
        return section
    run = store.get_run(baseline_run_id)
    if run is None:
        section["baseline_missing"] = True
        section["reason"] = f"基线 run 不存在: {baseline_run_id}"
        return section
    summary = run.get("metrics_summary")
    baseline_overall = summary.get("overall") if isinstance(summary, dict) else None
    if (
        not isinstance(baseline_overall, dict)
        or baseline_overall.get("p50") is None
        or baseline_overall.get("p95") is None
    ):
        section["baseline_missing"] = True
        section["reason"] = "基线 metrics_summary 缺少 overall.p50/p95 延迟结构"
        return section
    section["baseline_status"] = run.get("status")
    section["comparison"] = compare_baseline_metrics(
        overall, baseline_overall, float(config.thresholds.latency.regression_pct)
    )
    return section


def _run_ws_full_duplex_phase(
    config: EvalConfig,
    client: Any,
    run_id: str,
    ws_probe_factory: Optional[Any],
) -> Dict[str, Any]:
    """全双工语音链路探测段（REST 探测完成后追加，结果写入 summary.ws_full_duplex）。

    mock 模式无 WS stub / 配置禁用 → {"skipped": True, "reason": ...}（不影响终态）。
    否则: ws_probe_factory()（单测注入）或 FullDuplexProbe(config) 构造探测器 →
    创建一次性 eval agent（真实模式须注册 agent 才能对话，与 REST 段共用同一 client）
    → 逐轮 run_turn → summarize_ws_turns 统计 → 阈值判定。
    finally 中删除一次性 agent（异常吞掉记 note，模式同 quality suite）。
    WsProbeError（探测不可用，如音频资产缺失）→ 记入 error；意外异常兜底同口径，
    两者均由调用方并入 run 终态判定（failed）。
    """
    ws_cfg = config.latency.ws_full_duplex
    if config.mock.enabled:
        return {"skipped": True, "reason": "mock 模式无 WS stub"}
    if not ws_cfg.enabled:
        return {"skipped": True, "reason": "配置禁用"}

    section: Dict[str, Any] = {"enabled": True}
    agent_id: Optional[str] = None
    try:
        probe = ws_probe_factory() if ws_probe_factory is not None else FullDuplexProbe(config)
        agent_meta = client.create_eval_agent(run_id)
        agent_id = str(agent_meta["id"])
        turns: List[Dict[str, Any]] = []
        for index in range(max(1, int(ws_cfg.turns))):
            turns.append(probe.run_turn(agent_id, index))
        stats = summarize_ws_turns(turns)
        section["turns"] = turns
        section["stats"] = stats

        # 判定口径: 主指标 first_partial_to_first_audio（首个 ASR 中间结果 → 首包音频，
        # 投机响应模式的真实体感；服务端 VAD 不参与判定）P95 ≤ ws_p95_ms（=阈值判达标）；
        # 无有效轮次（全部超时/错误，count=0）→ failed 并注明原因
        threshold = float(config.thresholds.latency.ws_p95_ms)
        main = stats.get("first_partial_to_first_audio") or {}
        ws_p95: Optional[float] = main.get("p95") if main.get("count", 0) > 0 else None
        if ws_p95 is None:
            ws_passed = False
            section["failure_reason"] = "全双工无有效轮次（全部超时/错误，first_partial_to_first_audio 无样本）"
        else:
            ws_passed = bool(float(ws_p95) <= threshold)
            if not ws_passed:
                section["failure_reason"] = f"全双工首包 P95 {ws_p95} ms 超过阈值 {threshold} ms"
        section["judgment"] = {
            "ws_p95": ws_p95,
            "threshold_ws_p95_ms": threshold,
            "passed": ws_passed,
        }
    except WsProbeError as exc:
        section["error"] = f"WsProbeError: {exc}"
    except Exception as exc:  # 防御兜底: agent 创建等意外异常不使 suite 崩溃，并入失败口径
        section["error"] = _error_label(exc)
    finally:
        if agent_id is not None:
            try:
                client.delete_agent(agent_id)
                section.setdefault("cleanup", {})["agent_deleted"] = True
            except Exception as exc:
                section.setdefault("cleanup", {})["agent_deleted"] = False
                section["cleanup"]["note"] = f"删除 eval agent 异常(已吞掉): {exc}"
    return section


@register_suite(SUITE_NAME)
def run_latency_suite(
    run_id: str,
    config: EvalConfig,
    store: "EvalStore",
    *,
    client: Optional[TargetClient] = None,
    ws_probe_factory: Optional[Any] = None,
) -> Dict[str, Any]:
    """延迟评测主流程（签名约定: (run_id, config, store, *, client=None) -> summary）。

    client 为 None 时经 build_client 构造（Mock 模式自动接 stub）；注入供单测使用。
    ws_probe_factory 注入全双工探测器工厂（factory() -> 具有 run_turn(agent_id,
    turn_index) 方法的对象），供单测替换真实 WS 探测；None 时用 FullDuplexProbe。
    返回值即 metrics_summary（JSON 可序列化）；suite 内部完成 finish_run 终态化
    与 save_run_artifacts 明细落盘。
    """
    started_at = _now()
    if client is None:
        from evalkit.target import build_client  # 局部导入避免环

        client = build_client(config)

    rounds = max(1, int(config.latency.rounds))
    timeout = float(config.latency.probe_timeout_seconds)
    levels = _sanitize_levels(config.latency.concurrency_levels)
    thresholds = {
        "p95_ms": float(config.thresholds.latency.p95_ms),
        "regression_pct": float(config.thresholds.latency.regression_pct),
    }

    try:
        e2e = _run_e2e_phase(client, rounds, timeout)
    except _TargetUnreachable as exc:
        error = f"主服务不可达（首个探针即连接层失败）: {exc}"
        store.save_run_artifacts(
            run_id,
            {"suite": SUITE_NAME, "run_id": run_id, "status": "error", "error": error},
        )
        store.finish_run(run_id, "error", error=error)
        return {"suite": SUITE_NAME, "status": "error", "error": error, "finished_at": _now()}

    # ---- 检索与并发采样 ----
    retrieval_raw, retrieval_failures = _run_retrieval_phase(client, timeout)
    concurrency_raw = _run_concurrency_phase(client, levels, timeout)

    # ---- 全双工语音链路探测（REST 探测完成后追加；mock/禁用 → skipped）----
    ws_section = _run_ws_full_duplex_phase(config, client, run_id, ws_probe_factory)

    # ---- 统计: 总体 + 按探针分组 ----
    all_samples = [v for samples in e2e["samples_by_probe"].values() for v in samples]
    total_attempts = len(PROBES) * rounds
    overall = summarize(all_samples)
    overall["failed_count"] = total_attempts - len(all_samples)
    overall["failure_rate"] = (
        _round3(overall["failed_count"] / total_attempts) if total_attempts else 0.0
    )
    by_probe = {pid: summarize(samples) for pid, samples in e2e["samples_by_probe"].items()}

    # ---- 检索延迟统计 ----
    retrieval_stats: Dict[str, Any] = {
        "rounds": RETRIEVAL_ROUNDS,
        "limit": RETRIEVAL_LIMIT,
        "search_memories": {},
        "rag_search": {},
    }
    for method, per_query in retrieval_raw.items():
        for query_id, samples in per_query.items():
            stats = summarize(samples)
            stats["failed_count"] = RETRIEVAL_ROUNDS - len(samples)
            retrieval_stats[method][query_id] = stats

    # ---- 并发档位统计 ----
    levels_stats: Dict[str, Any] = {}
    for level in levels:
        raw = concurrency_raw[level]
        stats = summarize(raw["samples"])
        stats["failed_count"] = len(raw["failures"])
        stats["failure_rate"] = (
            _round3(len(raw["failures"]) / len(PROBES)) if PROBES else 0.0
        )
        levels_stats[str(level)] = stats
    degradation = _degradation_ratios(levels_stats, levels)

    # ---- 阈值判定: 总体 P95（无成功样本 → failed）----
    # 终态判定 = REST 判定 与 全双工判定 取与（skipped 不影响；WsProbeError → failed）
    overall_p95 = overall["p95"]
    rest_passed = bool(overall_p95 is not None and overall_p95 <= thresholds["p95_ms"])
    if ws_section.get("skipped"):
        ws_ok = True
    elif ws_section.get("error"):
        ws_ok = False
    else:
        ws_ok = bool((ws_section.get("judgment") or {}).get("passed"))
    passed = bool(rest_passed and ws_ok)
    judgment = {
        "overall_p95_ms": overall_p95,
        "threshold_p95_ms": thresholds["p95_ms"],
        "passed": passed,
    }

    # ---- 基线对比 ----
    baseline_section = _build_baseline_section(store, config, overall)

    summary: Dict[str, Any] = {
        "suite": SUITE_NAME,
        "status": "passed" if passed else "failed",
        "started_at": started_at,
        "finished_at": _now(),
        "config": {
            "rounds": rounds,
            "probe_timeout_seconds": timeout,
            "concurrency_levels": levels,
            "agent_id": AGENT_ID,
        },
        "thresholds": thresholds,
        "overall": overall,
        "by_probe": by_probe,
        "retrieval": retrieval_stats,
        "concurrency": {"levels": levels_stats, "degradation": degradation},
        "baseline": baseline_section,
        "ws_full_duplex": ws_section,
        "judgment": judgment,
    }

    detail: Dict[str, Any] = {
        "suite": SUITE_NAME,
        "run_id": run_id,
        "status": summary["status"],
        "judgment": judgment,
        "summary": summary,
        "probes": PROBES,
        "raw": {
            "e2e": {
                "rounds": rounds,
                "samples_by_probe": e2e["samples_by_probe"],
                "failures": e2e["failures"],
            },
            "retrieval": {
                "rounds": RETRIEVAL_ROUNDS,
                "queries": RETRIEVAL_QUERIES,
                "samples": retrieval_raw,
                "failures": retrieval_failures,
            },
            "concurrency": {str(level): concurrency_raw[level] for level in levels},
            "ws_full_duplex": ws_section,
        },
    }
    store.save_run_artifacts(run_id, detail)
    store.finish_run(run_id, summary["status"], metrics_summary=summary)
    return summary
