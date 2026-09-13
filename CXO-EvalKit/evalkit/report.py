"""报告落盘与 Markdown 报告生成。

目录结构: {data_dir}/runs/{run_id}/
  detail.json  — run 明细（JSON）
  report.md    — Markdown 报告（三段式：指标实测值 / 阈值逐项判定 / 异常项清单）

generate_report(config, run) 由 store.get_run 的返回值渲染报告文本；
write_report(config, run_id) 负责 get_run → 渲染 → 落盘 report.md。
summary 缺字段一律渲染 "（无数据）"，不抛异常。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from evalkit.config import EVALKIT_ROOT, EvalConfig


def resolve_data_dir(data_dir: str) -> str:
    """相对 data_dir 以 CXO-EvalKit 项目根为基准解析为绝对路径。"""
    if os.path.isabs(data_dir):
        return data_dir
    return os.path.join(EVALKIT_ROOT, data_dir)


def runs_root(data_dir: str) -> str:
    """run 产物根目录: {data_dir}/runs/"""
    return os.path.join(resolve_data_dir(data_dir), "runs")


def ensure_run_dir(data_dir: str, run_id: str) -> str:
    """创建并返回 run 目录: {data_dir}/runs/{run_id}/"""
    path = os.path.join(runs_root(data_dir), run_id)
    os.makedirs(path, exist_ok=True)
    return path


def detail_path(data_dir: str, run_id: str) -> str:
    return os.path.join(runs_root(data_dir), run_id, "detail.json")


def write_detail_json(data_dir: str, run_id: str, detail: Dict[str, Any]) -> str:
    """将 run 明细落盘为 detail.json，返回文件路径。"""
    ensure_run_dir(data_dir, run_id)
    path = detail_path(data_dir, run_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False, indent=2)
    return path


def report_path(data_dir: str, run_id: str) -> str:
    """返回 report.md 约定路径（不必存在）。"""
    return os.path.join(runs_root(data_dir), run_id, "report.md")


def read_report(data_dir: str, run_id: str) -> Optional[str]:
    """读取 report.md 内容；不存在返回 None。"""
    path = report_path(data_dir, run_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# Markdown 报告生成（三段式：一、指标实测值 / 二、阈值逐项判定 / 三、异常项清单）
# ===========================================================================
# 时间间隔 → 横轴标注（按年标注长期年轴；未知天数按 "{d}天" 呈现）
_INTERVAL_LABELS: Dict[int, str] = {30: "1月", 180: "6月", 365: "1年", 1095: "3年"}
_EPS = 1e-9                      # 浮点比较容差（与 memory_decay suite 口径一致）
_NO_DATA = "（无数据）"

_MEMORY_GROUP_ORDER: List[str] = [
    "overall", "permanent",
    "importance_low(1-2)", "importance_mid(3)", "importance_high(4-5)",
]
_GROUP_LABELS: Dict[str, str] = {
    "overall": "总体 overall",
    "permanent": "永久 permanent",
    "importance_low(1-2)": "重要性低(1-2)",
    "importance_mid(3)": "重要性中(3)",
    "importance_high(4-5)": "重要性高(4-5)",
}
_DIMENSION_LABELS: Dict[str, str] = {
    "memory_accuracy": "记忆准确 memory_accuracy",
    "persona_consistency": "人设一致 persona_consistency",
    "coherence": "连贯性 coherence",
}


# ---------------------------------------------------------------------------
# 渲染工具
# ---------------------------------------------------------------------------
def _fmt_value(value: Any, suffix: str = "") -> str:
    """值格式化；None → （无数据）。浮点统一保留 3 位小数。"""
    if value is None:
        return _NO_DATA
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{round(value, 3)}{suffix}"
    return f"{value}{suffix}"


def _fmt_pct(value: Any) -> str:
    """百分比字符串（value 已是百分数值，如 failure_rate=0.043 → 0.043%）。"""
    if value is None:
        return _NO_DATA
    return f"{round(float(value), 3)}%"


def _interval_label(days: Any) -> str:
    """间隔天数 → 横轴标注：30→1月 / 180→6月 / 365→1年 / 1095→3年，未知→"{d}天"。"""
    try:
        key = int(days)
    except (TypeError, ValueError):
        return str(days)
    return _INTERVAL_LABELS.get(key, f"{key}天")


def _sort_intervals(keys: Any) -> List[Any]:
    """间隔键升序（数字键按数值在前，非数字键按字符串排后）。"""

    def _key(k: Any) -> Tuple[int, int, str]:
        try:
            return (0, int(k), "")
        except (TypeError, ValueError):
            return (1, 0, str(k))

    return sorted(keys, key=_key)


def _parse_iso(text: Any) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


def _fmt_dt(text: Any) -> str:
    dt = _parse_iso(text)
    if dt is None:
        return str(text) if text else "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def _fmt_duration(created_at: Any, finished_at: Any) -> str:
    start = _parse_iso(created_at)
    end = _parse_iso(finished_at)
    if start is None or end is None:
        return "—"
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}m{sec:02d}s"


def _read_detail(config: EvalConfig, run_id: str) -> Optional[Dict[str, Any]]:
    """尝试读取同目录 detail.json（清理残留等仅存在于明细的字段）；缺失/损坏返回 None。"""
    try:
        with open(detail_path(config.data_dir, run_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _table_header(cells: List[str]) -> List[str]:
    """Markdown 表头 + 分隔行。"""
    return ["| " + " | ".join(cells) + " |", "|" + "------|" * len(cells)]


# ---------------------------------------------------------------------------
# 头部
# ---------------------------------------------------------------------------
def _render_header(run: Dict[str, Any]) -> List[str]:
    summary = run.get("metrics_summary") or {}
    degraded = bool(run.get("status") == "judge_unavailable" or summary.get("judge_unavailable"))
    lines = [
        "# CXO-EvalKit 评测报告",
        "",
        "| 字段 | 值 |",
        "|------|-----|",
        f"| run_id | {run.get('run_id') or '—'} |",
        f"| suite | {run.get('suite') or '—'} |",
        f"| status | {run.get('status') or '—'} |",
        f"| 开始时间 | {_fmt_dt(run.get('created_at'))} |",
        f"| 结束时间 | {_fmt_dt(run.get('finished_at'))} |",
        f"| 时长 | {_fmt_duration(run.get('created_at'), run.get('finished_at'))} |",
        "",
    ]
    if degraded:
        lines += [
            "> ⚠ **judge 服务不可用，本报告为降级报告**：判分类指标（保持率/评分）缺失或仅含已完成部分。",
            "",
        ]
    return lines


# ---------------------------------------------------------------------------
# 第一段：memory_decay 指标
# ---------------------------------------------------------------------------
def _render_memory_metrics(run: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> List[str]:
    summary = run.get("metrics_summary") or {}
    lines: List[str] = []

    matrix = summary.get("retention_matrix") or {}
    intervals = _sort_intervals(matrix.keys()) if matrix else []
    lines += ["### 保持率矩阵（分层 × 时间间隔）", ""]
    if matrix and intervals:
        groups = [g for g in _MEMORY_GROUP_ORDER if any(g in matrix[i] for i in intervals)]
        groups += sorted({g for i in intervals for g in matrix[i] if g not in _MEMORY_GROUP_ORDER})
        lines += _table_header(["分层"] + [_interval_label(i) for i in intervals])
        for group in groups:
            label = _GROUP_LABELS.get(group, group)
            cells = " | ".join(_fmt_value(matrix[i].get(group)) for i in intervals)
            lines.append(f"| {label} | {cells} |")
    else:
        lines.append(_NO_DATA)
    lines.append("")

    hit_rate = summary.get("retrieval_hit_rate") or {}
    if hit_rate:
        hit_intervals = _sort_intervals({k for m in hit_rate.values() for k in (m or {})})
        lines += ["### 检索命中率", ""]
        lines += _table_header(["检索方式"] + [_interval_label(i) for i in hit_intervals])
        for method in ("search", "rag"):
            per = hit_rate.get(method) or {}
            cells = " | ".join(_fmt_value(per.get(i)) for i in hit_intervals)
            lines.append(f"| {method} | {cells} |")
        lines.append("")

    contrast = summary.get("reactivation_contrast")
    if contrast is not None:
        lines += ["### 再激活对照（终点保持率：再激活组 vs 对照组）", ""]
        lines.append(f"- 对照组保持率：{_fmt_value(contrast.get('control'))}")
        lines.append(f"- 再激活组保持率：{_fmt_value(contrast.get('reactivated'))}")
        if contrast.get("computable") is False:
            lines.append("- 可比性：（无数据，两组无有效判分样本）")
        else:
            lines.append(f"- 再激活组优于对照组：{'是' if contrast.get('passes') else '否'}")
        lines.append("")

    lines += ["### 劣化曲线单调性", ""]
    violations = summary.get("monotonic_violations") or []
    if violations:
        for v in violations:
            lines.append(
                f"- {_GROUP_LABELS.get(v.get('group'), v.get('group'))}："
                f"{_interval_label(v.get('prev_interval'))} {_fmt_value(v.get('prev_rate'))} → "
                f"{_interval_label(v.get('curr_interval'))} {_fmt_value(v.get('curr_rate'))}（回升超容差）"
            )
    else:
        lines.append("无单调性违反")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 第一段：latency 指标
# ---------------------------------------------------------------------------
def _render_latency_metrics(run: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> List[str]:
    summary = run.get("metrics_summary") or {}
    lines: List[str] = []

    overall = summary.get("overall") or {}
    lines += ["### 总体延迟（E2E chat）", ""]
    lines += _table_header(["指标", "值"])
    overall_labels = [
        ("count", "样本数", False), ("mean", "均值 ms", False), ("p50", "P50 ms", False),
        ("p95", "P95 ms", False), ("p99", "P99 ms", False), ("min", "最小 ms", False),
        ("max", "最大 ms", False), ("failed_count", "失败次数", False),
        ("failure_rate", "失败率", True),
    ]
    for key, label, as_pct in overall_labels:
        shown = _fmt_pct(overall.get(key)) if as_pct else _fmt_value(overall.get(key))
        lines.append(f"| {label} | {shown} |")
    lines.append("")

    by_probe = summary.get("by_probe") or {}
    if by_probe:
        lines += ["### 按探针分组", ""]
        lines += _table_header(["探针", "count", "mean", "P50", "P95", "failed"])
        for probe_id in sorted(by_probe):
            s = by_probe[probe_id] or {}
            cells = " | ".join([
                _fmt_value(s.get("count")), _fmt_value(s.get("mean")),
                _fmt_value(s.get("p50")), _fmt_value(s.get("p95")),
                _fmt_value(s.get("failed_count")),
            ])
            lines.append(f"| {probe_id} | {cells} |")
        lines.append("")

    retrieval = summary.get("retrieval") or {}
    retrieval_rows = [
        (method, query_id, stats or {})
        for method in ("search_memories", "rag_search")
        for query_id, stats in sorted((retrieval.get(method) or {}).items())
    ]
    if retrieval_rows:
        lines += ["### 检索延迟", ""]
        lines += _table_header(["方法", "查询", "count", "P50", "P95", "failed"])
        for method, query_id, s in retrieval_rows:
            cells = " | ".join([
                _fmt_value(s.get("count")), _fmt_value(s.get("p50")),
                _fmt_value(s.get("p95")), _fmt_value(s.get("failed_count")),
            ])
            lines.append(f"| {method} | {query_id} | {cells} |")
        lines.append("")

    concurrency = summary.get("concurrency") or {}
    levels = concurrency.get("levels") or {}
    if levels:
        degradation = concurrency.get("degradation") or {}
        lines += ["### 并发档位", ""]
        lines += _table_header(["并发", "count", "P50", "P95", "失败率", "P95 退化倍率"])

        def _level_key(k: Any) -> Tuple[int, int]:
            try:
                return (0, int(k))
            except (TypeError, ValueError):
                return (1, 0)

        for level in sorted(levels, key=_level_key):
            s = levels[level] or {}
            deg = degradation.get(level) or {}
            cells = " | ".join([
                _fmt_value(s.get("count")), _fmt_value(s.get("p50")), _fmt_value(s.get("p95")),
                _fmt_pct(s.get("failure_rate")), _fmt_value(deg.get("p95_ratio")),
            ])
            lines.append(f"| {level} | {cells} |")
        lines.append("")

    ws_section = summary.get("ws_full_duplex") or {}
    if ws_section.get("skipped"):
        lines += [f"### 全双工语音链路（WS voice.dual_stream）", "", f"跳过：{ws_section.get('reason') or '未知原因'}", ""]
    elif ws_section.get("error"):
        lines += ["### 全双工语音链路（WS voice.dual_stream）", "", f"探测异常：{ws_section.get('error')}", ""]
    elif ws_section.get("stats") is not None:
        stats = ws_section["stats"]
        lines += ["### 全双工语音链路（WS voice.dual_stream）", ""]
        turns = ws_section.get("turns") or []
        if turns:
            lines += _table_header(["轮次", "说完(能量) ms", "首个partial ms", "首包 ms", "partial→首包 ms", "timeout", "error"])
            for t in turns:
                tm = t.get("timings") or {}
                speech_end = t.get("speech_end_offset_ms")
                pfirst, first = tm.get("asr_first_partial"), tm.get("tts_first_audio")
                gap = (
                    round(max(0.0, float(first) - float(pfirst)), 1)
                    if isinstance(first, (int, float)) and isinstance(pfirst, (int, float)) else None
                )
                cells = " | ".join([
                    _fmt_value(t.get("turn_index")), _fmt_value(speech_end), _fmt_value(pfirst),
                    _fmt_value(first), _fmt_value(gap), "是" if t.get("timeout") else "否",
                    (str(t.get("error"))[:40] if t.get("error") else "—"),
                ])
                lines.append(f"| {cells} |")
            lines.append("")
        main = stats.get("first_partial_to_first_audio") or {}
        lines += ["**主指标：首个 ASR 中间结果 → 首包 TTS 音频**——投机响应模式真实体感；服务端 VAD 不参与判定", ""]
        lines += _table_header(["count", "mean ms", "P50 ms", "P95 ms", "min ms", "max ms"])
        lines.append("| " + " | ".join([
            _fmt_value(main.get("count")), _fmt_value(main.get("mean")), _fmt_value(main.get("p50")),
            _fmt_value(main.get("p95")), _fmt_value(main.get("min")), _fmt_value(main.get("max")),
        ]) + " |")
        lines.append("")
        aux_rows = [
            ("说完→首包（能量法，辅助）", stats.get("speech_end_to_first_audio") or {}),
            ("定稿→首包（asr_final→首包，纯管线段）", stats.get("asr_final_to_first_audio") or {}),
            ("流开始→首包（完整轮次）", stats.get("stream_to_first_audio") or {}),
        ]
        lines += _table_header(["辅助指标", "count", "mean ms", "P50 ms", "P95 ms"])
        for label, s in aux_rows:
            lines.append(f"| {label} | " + " | ".join([
                _fmt_value(s.get("count")), _fmt_value(s.get("mean")),
                _fmt_value(s.get("p50")), _fmt_value(s.get("p95")),
            ]) + " |")
        lines.append("")
        stage_rows = []
        for stage in ("asr_first_partial", "asr_final", "prefill_started", "tts_first_audio", "tts_done", "vad_speech_end"):
            s = (stats.get("stages") or {}).get(stage) or {}
            stage_rows.append((stage, s))
        lines += ["各阶段首包时刻（相对本轮音频流开始）", ""]
        lines += _table_header(["阶段", "count", "mean ms", "P50 ms", "P95 ms"])
        for stage, s in stage_rows:
            lines.append(f"| {stage} | " + " | ".join([
                _fmt_value(s.get("count")), _fmt_value(s.get("mean")),
                _fmt_value(s.get("p50")), _fmt_value(s.get("p95")),
            ]) + " |")
        lines.append("")

    lines += ["### 基线对比", ""]
    baseline = summary.get("baseline") or {}
    if not baseline:
        lines.append(_NO_DATA)
    elif baseline.get("baseline_missing"):
        lines.append(f"基线缺失：{baseline.get('reason') or '未配置 baseline_run_id'}")
    else:
        lines.append(
            f"- 基线 run：{baseline.get('baseline_run_id') or '—'}"
            f"（status={baseline.get('baseline_status') or '—'}）"
        )
        lines.append("")
        lines += _table_header(["指标", "当前 ms", "基线 ms", "变化 ms", "变化 %", "回归"])
        metrics = (baseline.get("comparison") or {}).get("metrics") or {}
        for name, label in (("p50", "P50"), ("p95", "P95")):
            m = metrics.get(name) or {}
            if m.get("missing") or not m:
                lines.append(f"| {label} | {_NO_DATA} | {_NO_DATA} | {_NO_DATA} | {_NO_DATA} | {_NO_DATA} |")
            else:
                regressed = "是（回归）" if m.get("regressed") else "否"
                cells = " | ".join([
                    _fmt_value(m.get("current_ms")), _fmt_value(m.get("baseline_ms")),
                    _fmt_value(m.get("delta_ms")), _fmt_value(m.get("delta_pct")),
                ])
                lines.append(f"| {label} | {cells} | {regressed} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 第一段：quality 指标
# ---------------------------------------------------------------------------
def _render_quality_metrics(run: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> List[str]:
    summary = run.get("metrics_summary") or {}
    lines: List[str] = []

    dimensions = summary.get("dimensions") or {}
    lines += ["### 三维评分（1-5 分）", ""]
    if dimensions:
        lines += _table_header(["维度", "count", "mean", "std"])
        for dim in ("memory_accuracy", "persona_consistency", "coherence"):
            s = dimensions.get(dim) or {}
            cells = " | ".join([
                _fmt_value(s.get("count")), _fmt_value(s.get("mean")), _fmt_value(s.get("std")),
            ])
            lines.append(f"| {_DIMENSION_LABELS[dim]} | {cells} |")
        lines.append("")
    else:
        lines += [_NO_DATA, ""]

    lines.append(f"- 综合均分 overall_avg：{_fmt_value(summary.get('overall_avg'))}")
    lines.append("")

    lines += ["### 低分案例清单（任一维 < 3 分）", ""]
    if "low_scores" not in summary:
        lines += [_NO_DATA, ""]
        return lines
    low_scores = summary.get("low_scores") or []
    if not low_scores:
        lines += ["（无低分案例）", ""]
        return lines
    for index, case in enumerate(low_scores, 1):
        scores = case.get("scores") or {}
        score_text = "、".join(
            f"{_DIMENSION_LABELS.get(k, k)}={v}" for k, v in scores.items()
        ) or _NO_DATA
        lines += [
            f"**{index}. {case.get('script_id') or '—'} 第 {case.get('turn_index')} 轮**",
            "",
            f"- 得分：{score_text}",
            f"- judge 理由：{case.get('reason') or _NO_DATA}",
            "",
            "> 回复原文：",
            ">",
        ]
        reply = str(case.get("reply") or "")
        for reply_line in (reply.splitlines() or [""]):
            lines.append(f"> {reply_line}")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 第二段：阈值逐项判定
# ---------------------------------------------------------------------------
def _judge_cell(value: Any, threshold: Any, op: str) -> str:
    """阈值判定单元格。op="ge"：value+ε ≥ threshold ✅；op="le"：value ≤ threshold ✅。

    边界口径与 suite 终态判定一致：恰好达标（=）判 ✅，恰好超标判 ❌。
    """
    if value is None:
        return "—（无数据）"
    v = float(value)
    ok = (v + _EPS >= float(threshold)) if op == "ge" else (v <= float(threshold))
    return "✅ 通过" if ok else "❌ 未达标"


def _threshold_row(item: str, measured: str, threshold: str, verdict: str) -> str:
    return f"| {item} | {measured} | {threshold} | {verdict} |"


def _render_thresholds_section(config: EvalConfig, run: Dict[str, Any]) -> List[str]:
    suite = run.get("suite")
    summary = run.get("metrics_summary") or {}
    t = config.thresholds
    lines = [
        "## 二、阈值逐项判定",
        "",
        "| 检查项 | 实测值 | 阈值 | 判定 |",
        "|------|--------|------|------|",
    ]

    # ---- 记忆维度 ----
    matrix = (summary.get("retention_matrix") or {}) if suite == "memory_decay" else {}
    permanent_values = [
        float(m.get("permanent")) for m in matrix.values()
        if isinstance(m, dict) and m.get("permanent") is not None
    ]
    if permanent_values:
        worst = min(permanent_values)
        lines.append(_threshold_row(
            "永久记忆保持率", round(worst, 3), f"≥ {t.memory.permanent_retention}",
            _judge_cell(worst, t.memory.permanent_retention, "ge"),
        ))
    else:
        lines.append(_threshold_row(
            "永久记忆保持率", "—", f"≥ {t.memory.permanent_retention}", "—（本 suite 无此指标）",
        ))

    if matrix and "365" in matrix:
        one_year = matrix.get("365", {}).get("overall")
        lines.append(_threshold_row(
            "1年 overall 保持率", _fmt_value(one_year), f"≥ {t.memory.retention_1y_min}",
            _judge_cell(one_year, t.memory.retention_1y_min, "ge"),
        ))
    else:
        lines.append(_threshold_row(
            "1年 overall 保持率", "—", f"≥ {t.memory.retention_1y_min}", "—（本 suite 无此指标）",
        ))

    contrast = summary.get("reactivation_contrast")
    if suite == "memory_decay" and contrast is not None and contrast.get("computable") is not False:
        verdict = "✅ 通过" if contrast.get("passes") else "❌ 未达标"
        measured = (
            f"再激活 {_fmt_value(contrast.get('reactivated'))} vs 对照 {_fmt_value(contrast.get('control'))}"
        )
        lines.append(_threshold_row(
            "再激活组保持率 > 对照组", measured,
            str(t.memory.reactivation_must_beat_control), verdict,
        ))
    else:
        lines.append(_threshold_row(
            "再激活组保持率 > 对照组", "—", str(t.memory.reactivation_must_beat_control),
            "—（本 suite 无此指标）",
        ))

    # ---- 延迟维度 ----
    overall = (summary.get("overall") or {}) if suite == "latency" else {}
    if overall:
        p95 = overall.get("p95")
        lines.append(_threshold_row(
            "总体 P95", _fmt_value(p95, " ms"), f"≤ {t.latency.p95_ms} ms",
            _judge_cell(p95, t.latency.p95_ms, "le"),
        ))
    else:
        lines.append(_threshold_row(
            "总体 P95", "—", f"≤ {t.latency.p95_ms} ms", "—（本 suite 无此指标）",
        ))

    baseline = (summary.get("baseline") or {}) if suite == "latency" else {}
    p95_entry = ((baseline.get("comparison") or {}).get("metrics") or {}).get("p95") or {}
    if baseline and not baseline.get("baseline_missing") and p95_entry and not p95_entry.get("missing") \
            and p95_entry.get("delta_pct") is not None:
        verdict = "❌ 未达标" if p95_entry.get("regressed") else "✅ 通过"
        lines.append(_threshold_row(
            "基线 P95 回归幅度", _fmt_pct(p95_entry.get("delta_pct")),
            f"≤ +{t.latency.regression_pct}%", verdict,
        ))
    else:
        lines.append(_threshold_row(
            "基线 P95 回归幅度", "—", f"≤ +{t.latency.regression_pct}%", "—（本 suite 无此指标）",
        ))

    # ---- 全双工语音链路（latency）----
    ws = (summary.get("ws_full_duplex") or {}) if suite == "latency" else {}
    if ws:
        if ws.get("skipped"):
            lines.append(_threshold_row(
                "首结果→首包 P95（全双工）", "—", f"≤ {t.latency.ws_p95_ms} ms",
                f"—（跳过：{ws.get('reason') or '未知原因'}）",
            ))
        elif ws.get("error"):
            lines.append(_threshold_row(
                "首结果→首包 P95（全双工）", "—", f"≤ {t.latency.ws_p95_ms} ms", "❌ 未达标（探测异常）",
            ))
        else:
            main = (ws.get("stats") or {}).get("first_partial_to_first_audio") or {}
            ws_p95 = main.get("p95") if main.get("count", 0) > 0 else None
            if ws_p95 is None:
                lines.append(_threshold_row(
                    "首结果→首包 P95（全双工）", "—", f"≤ {t.latency.ws_p95_ms} ms",
                    "❌ 未达标（无有效轮次）",
                ))
            else:
                passed = float(ws_p95) <= t.latency.ws_p95_ms
                lines.append(_threshold_row(
                    "首结果→首包 P95（全双工）", _fmt_value(ws_p95, " ms"),
                    f"≤ {t.latency.ws_p95_ms} ms",
                    "✅ 通过" if passed else "❌ 未达标",
                ))
    else:
        lines.append(_threshold_row(
            "首结果→首包 P95（全双工）", "—", f"≤ {t.latency.ws_p95_ms} ms", "—（本 suite 无此指标）",
        ))

    # ---- 质量维度 ----
    if suite == "quality" and "overall_avg" in summary:
        avg = summary.get("overall_avg")
        lines.append(_threshold_row(
            "三维综合均分", _fmt_value(avg), f"≥ {t.quality.avg_min}",
            _judge_cell(avg, t.quality.avg_min, "ge"),
        ))
    else:
        lines.append(_threshold_row(
            "三维综合均分", "—", f"≥ {t.quality.avg_min}", "—（本 suite 无此指标）",
        ))

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 第三段：异常项清单
# ---------------------------------------------------------------------------
def _render_anomalies_section(
    config: EvalConfig, run: Dict[str, Any], detail: Optional[Dict[str, Any]]
) -> List[str]:
    suite = run.get("suite")
    summary = run.get("metrics_summary") or {}
    lines = ["## 三、异常项清单", ""]
    items: List[str] = []

    judge_failed = summary.get("judge_failed_count")
    if isinstance(judge_failed, int) and judge_failed > 0:
        items.append(f"judge 判分失败案例数：{judge_failed}")

    if run.get("status") == "judge_unavailable" or summary.get("judge_unavailable"):
        reason = summary.get("error") or summary.get("judge_unavailable_reason")
        text = "judge 服务不可用，run 已降级（报告为降级报告）"
        if reason:
            text += f"：{reason}"
        items.append(text)

    if suite == "latency":
        overall = summary.get("overall") or {}
        failed = overall.get("failed_count")
        if isinstance(failed, int) and failed > 0:
            items.append(f"失败探针请求：{failed} 次（失败率 {_fmt_pct(overall.get('failure_rate'))}）")
        ws = summary.get("ws_full_duplex") or {}
        if ws.get("error"):
            items.append(f"全双工探测异常：{ws.get('error')}")
        elif not ws.get("skipped"):
            reason = ws.get("failure_reason")
            if reason:
                items.append(f"全双工失败原因：{reason}")
            elif not ((ws.get("judgment") or {}).get("passed")):
                items.append("全双工判定未通过（详见阈值判定表）")
            cleanup = ws.get("cleanup") or {}
            if cleanup.get("agent_deleted") is False:
                items.append(f"全双工 eval agent 删除失败：{cleanup.get('note') or '未知异常'}")
        baseline = summary.get("baseline") or {}
        if baseline.get("baseline_missing"):
            items.append(f"基线缺失：{baseline.get('reason') or '未配置 baseline_run_id'}")

    if suite == "quality":
        for turn in summary.get("failed_turns") or []:
            items.append(
                f"失败轮次：{turn.get('script_id') or '—'} 第 {turn.get('turn_index')} 轮 — {turn.get('error')}"
            )

    if suite == "memory_decay":
        cleanup = (detail or {}).get("cleanup") or {}
        remaining = cleanup.get("remaining")
        if isinstance(remaining, int) and remaining > 0:
            items.append(f"清理残留：仍有 {remaining} 条记忆未删除")
        if cleanup.get("note"):
            items.append(f"清理异常：{cleanup['note']}")
        for v in summary.get("monotonic_violations") or []:
            items.append(
                f"单调性违反：{_GROUP_LABELS.get(v.get('group'), v.get('group'))} "
                f"{_interval_label(v.get('prev_interval'))}（{_fmt_value(v.get('prev_rate'))}）→ "
                f"{_interval_label(v.get('curr_interval'))}（{_fmt_value(v.get('curr_rate'))}）"
            )
        contrast = summary.get("reactivation_contrast") or {}
        if contrast and contrast.get("computable") is not False and contrast.get("passes") is False:
            items.append(
                f"再激活对照失败：再激活 {_fmt_value(contrast.get('reactivated'))} "
                f"未胜过对照 {_fmt_value(contrast.get('control'))}"
            )
        for reason in summary.get("failure_reasons") or []:
            items.append(f"终态失败原因：{reason}")

    if run.get("error"):
        items.append(f"run error：{run['error']}")

    if items:
        lines += [f"- {item}" for item in items]
    else:
        lines.append("（无异常项）")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def generate_report(config: EvalConfig, run: Dict[str, Any]) -> str:
    """由 run 详情（store.get_run 返回值）生成三段式 Markdown 报告。

    summary 缺字段渲染 "（无数据）"，不抛异常；suite 未知时按通用空报告渲染。
    """
    run_id = str(run.get("run_id") or "")
    detail = _read_detail(config, run_id)
    suite = run.get("suite")

    lines: List[str] = _render_header(run)
    lines += ["## 一、指标实测值", ""]
    if suite == "memory_decay":
        lines += _render_memory_metrics(run, detail)
    elif suite == "latency":
        lines += _render_latency_metrics(run, detail)
    elif suite == "quality":
        lines += _render_quality_metrics(run, detail)
    else:
        lines += [_NO_DATA, ""]
    lines += _render_thresholds_section(config, run)
    lines += _render_anomalies_section(config, run, detail)
    return "\n".join(lines).rstrip() + "\n"


def write_report(config: EvalConfig, run_id: str) -> str:
    """get_run → generate_report → 落盘 report.md，返回文件路径；run 不存在抛 ValueError。"""
    from evalkit.store import EvalStore  # 局部导入避免循环依赖（store 依赖本模块）

    store = EvalStore(config.data_dir)
    try:
        run = store.get_run(run_id)
    finally:
        store.close()
    if run is None:
        raise ValueError(f"run 不存在: {run_id}")
    content = generate_report(config, run)
    ensure_run_dir(config.data_dir, run_id)
    path = report_path(config.data_dir, run_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
