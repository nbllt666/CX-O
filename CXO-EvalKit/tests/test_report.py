"""报告生成与阈值判定单测（fake run 经 store.create_run + finish_run 构造，无真实网络）。

覆盖：
- 三段式标题齐全（指标实测值 / 阈值逐项判定 / 异常项清单）
- memory_decay 保持率矩阵（含 "1年" 标注）+ 阈值边界（0.6 ✅ / 0.599 ❌）
- latency regressed 标记 + P95 边界（2000 ✅ / 2000.001 ❌）
- quality 低分案例清单含回复原文
- judge_unavailable 终态降级报告不抛异常
- write_report 落盘 + API run_report 端点（终态 200 / running 404）
- 清理残留（detail.json cleanup.remaining > 0）计异常
"""
import pytest
from fastapi.testclient import TestClient

from evalkit.api import create_app
from evalkit.config import EvalConfig
from evalkit.report import generate_report, write_report
from evalkit.store import EvalStore


# ---------------------------------------------------------------------------
# 样本构造（字段名与三 suite 的 metrics_summary 真实结构对齐；矩阵键经 JSON 存取为 str）
# ---------------------------------------------------------------------------
def _memory_summary(overall_1y: float = 0.65) -> dict:
    return {
        "retention_matrix": {
            "30": {"overall": 0.9, "permanent": 1.0},
            "180": {"overall": 0.8, "permanent": 1.0},
            "365": {"overall": overall_1y, "permanent": 1.0},
            "1095": {"overall": 0.5, "permanent": 1.0},
        },
        "retrieval_hit_rate": {
            "search": {"30": 1.0, "365": 0.7},
            "rag": {"30": 0.9, "365": 0.6},
        },
        "monotonic_violations": [],
        "reactivation_contrast": {
            "control": 0.3, "reactivated": 0.7, "passes": True, "computable": True,
        },
        "judge_failed_count": 0,
        "judge_unavailable": False,
        "failure_reasons": [],
    }


def _latency_summary(p95: float = 2500.0, baseline_missing: bool = False) -> dict:
    return {
        "suite": "latency",
        "status": "failed",
        "started_at": "2026-09-12T00:00:00+00:00",
        "finished_at": "2026-09-12T00:00:05+00:00",
        "config": {"rounds": 10, "concurrency_levels": [1]},
        "thresholds": {"p95_ms": 2000, "regression_pct": 20},
        "overall": {
            "count": 70, "mean": 100.0, "p50": 95.0, "p95": p95, "p99": 3000.0,
            "min": 50.0, "max": 3000.0, "failed_count": 3, "failure_rate": 0.043,
        },
        "by_probe": {
            "greet_short": {
                "count": 10, "mean": 90.0, "p50": 88.0, "p95": 100.0, "p99": 110.0,
                "min": 80.0, "max": 110.0, "failed_count": 1, "failure_rate": 0.1,
            },
        },
        "retrieval": {
            "rounds": 5, "limit": 5,
            "search_memories": {
                "q_self_preference": {
                    "count": 5, "mean": 10.0, "p50": 9.0, "p95": 12.0, "p99": 13.0,
                    "min": 8.0, "max": 13.0, "failed_count": 0,
                },
            },
            "rag_search": {},
        },
        "concurrency": {
            "levels": {
                "1": {
                    "count": 7, "mean": 90.0, "p50": 88.0, "p95": 100.0, "p99": 110.0,
                    "min": 80.0, "max": 110.0, "failed_count": 0, "failure_rate": 0.0,
                },
            },
            "degradation": {"1": {"p95_ratio": 1.0}},
        },
        "baseline": (
            {
                "baseline_run_id": "abc123", "baseline_missing": False,
                "baseline_status": "passed",
                "comparison": {
                    "regressed": True,
                    "metrics": {
                        "p50": {
                            "current_ms": 95.0, "baseline_ms": 80.0,
                            "delta_ms": 15.0, "delta_pct": 18.75, "regressed": False,
                        },
                        "p95": {
                            "current_ms": p95, "baseline_ms": 1800.0,
                            "delta_ms": 700.0, "delta_pct": 38.9, "regressed": True,
                        },
                    },
                },
            }
            if not baseline_missing
            else {"baseline_run_id": "gone", "baseline_missing": True, "reason": "基线 run 不存在: gone"}
        ),
        "judgment": {"overall_p95_ms": p95, "threshold_p95_ms": 2000, "passed": p95 <= 2000},
    }


def _quality_summary() -> dict:
    return {
        "suite": "quality",
        "status": "failed",
        "started_at": "2026-09-12T00:00:00+00:00",
        "finished_at": "2026-09-12T00:00:08+00:00",
        "config": {"agent_id": "eval-agent-x", "scripts": ["evening_debrief"], "turn_count": 4},
        "thresholds": {"avg_min": 3.5},
        "dimensions": {
            "memory_accuracy": {"count": 8, "mean": 4.0, "std": 0.5},
            "persona_consistency": {"count": 8, "mean": 3.8, "std": 0.4},
            "coherence": {"count": 8, "mean": 4.2, "std": 0.3},
        },
        "overall_avg": 2.9,
        "judgment": {"overall_avg": 2.9, "threshold_avg_min": 3.5, "passed": False},
        "judge_failed_count": 1,
        "failed_turns": [
            {"script_id": "evening_debrief", "turn_index": 3, "error": "TargetHttpError: 500"},
        ],
        "low_scores": [
            {
                "script_id": "evening_debrief",
                "turn_index": 2,
                "scores": {"memory_accuracy": 2.0, "persona_consistency": 4.0, "coherence": 4.0},
                "reason": "未接住用户的情绪，只给了泛泛回应",
                "reply": "别难过啦，吃点好的吧。\n早点休息。",
            },
        ],
        "scored_case_count": 8,
    }


def _quality_judge_unavailable_summary() -> dict:
    """quality judge_unavailable 终态（_failed_summary 结构，无判分统计字段）。"""
    return {
        "suite": "quality",
        "status": "judge_unavailable",
        "started_at": "2026-09-12T00:00:00+00:00",
        "finished_at": "2026-09-12T00:00:03+00:00",
        "config": {"agent_id": "eval-agent-x", "avg_min": 3.5},
        "judge_failed_count": 0,
        "failed_turns": [],
        "error": "judge 服务不可用（JudgeUnavailableError），整个 run 降级: connection refused",
    }


def _make_run(store: EvalStore, run_id: str, suite: str, status: str, summary) -> None:
    store.create_run(run_id, suite)
    store.finish_run(run_id, status, metrics_summary=summary)


def _threshold_line(report: str, item: str) -> str:
    """从阈值判定段提取含指定检查项的表格行（含 "—（本 suite 无此指标）" 行）。"""
    for line in report.splitlines():
        if line.startswith("|") and item in line:
            return line
    raise AssertionError(f"阈值行不存在: {item}\n{report}")


@pytest.fixture()
def env(tmp_path):
    cfg = EvalConfig.model_validate({"data_dir": str(tmp_path / "data")})
    store = EvalStore(cfg.data_dir)
    yield cfg, store
    store.close()


# ---------------------------------------------------------------------------
# 三段式齐全
# ---------------------------------------------------------------------------
def test_report_three_sections_for_all_suites(env):
    cfg, store = env
    cases = [
        ("md", "memory_decay", "passed", _memory_summary()),
        ("lat", "latency", "failed", _latency_summary()),
        ("q", "quality", "failed", _quality_summary()),
    ]
    for run_id, suite, status, summary in cases:
        _make_run(store, run_id, suite, status, summary)
        run = store.get_run(run_id)
        report = generate_report(cfg, run)
        assert "# CXO-EvalKit 评测报告" in report
        assert "## 一、指标实测值" in report
        assert "## 二、阈值逐项判定" in report
        assert "## 三、异常项清单" in report
        assert run_id in report and suite in report and status in report


# ---------------------------------------------------------------------------
# memory_decay
# ---------------------------------------------------------------------------
def test_memory_decay_report_matrix_and_labels(env):
    cfg, store = env
    _make_run(store, "md1", "memory_decay", "passed", _memory_summary())
    report = generate_report(cfg, store.get_run("md1"))
    # 横轴按年标注 + 矩阵数值 + 检索命中率 + 再激活对照 + 单调性
    for label in ("1月", "6月", "1年", "3年"):
        assert label in report
    assert "0.65" in report            # 1年 overall 保持率
    assert "0.9" in report             # 1月 overall
    assert "检索命中率" in report and "search" in report and "rag" in report
    assert "再激活对照" in report and "对照组保持率" in report
    assert "单调性" in report


def test_memory_decay_threshold_boundary_06_vs_0599(env):
    """阈值边界：1年 overall=0.6 → ✅（≥）；0.599 → ❌。"""
    cfg, store = env
    _make_run(store, "md_eq", "memory_decay", "passed", _memory_summary(overall_1y=0.6))
    _make_run(store, "md_lt", "memory_decay", "failed", _memory_summary(overall_1y=0.599))

    line_eq = _threshold_line(generate_report(cfg, store.get_run("md_eq")), "1年 overall 保持率")
    assert "✅" in line_eq and "0.6" in line_eq
    line_lt = _threshold_line(generate_report(cfg, store.get_run("md_lt")), "1年 overall 保持率")
    assert "❌" in line_lt and "0.599" in line_lt


def test_memory_decay_threshold_rows_for_latency_suite_absent(env):
    """suite 无对应指标 → "—（本 suite 无此指标）"。"""
    cfg, store = env
    _make_run(store, "lat2", "latency", "passed", _latency_summary(p95=800.0))
    report = generate_report(cfg, store.get_run("lat2"))
    assert report.count("—（本 suite 无此指标）") >= 3  # 记忆三维判定行


# ---------------------------------------------------------------------------
# latency
# ---------------------------------------------------------------------------
def test_latency_report_regressed_marked(env):
    cfg, store = env
    _make_run(store, "lat1", "latency", "failed", _latency_summary(p95=2500.0))
    report = generate_report(cfg, store.get_run("lat1"))
    assert "是（回归）" in report
    assert "按探针分组" in report and "greet_short" in report
    assert "检索延迟" in report and "并发档位" in report and "P95 退化倍率" in report
    line = _threshold_line(report, "总体 P95")
    assert "❌" in line and "2500" in line
    line_reg = _threshold_line(report, "基线 P95 回归幅度")
    assert "❌" in line_reg and "38.9" in line_reg


def test_latency_threshold_boundary_2000_vs_2001(env):
    """P95 边界：2000 → ✅（≤）；2000.001 → ❌。"""
    cfg, store = env
    _make_run(store, "lat_eq", "latency", "passed", _latency_summary(p95=2000.0, baseline_missing=True))
    _make_run(store, "lat_gt", "latency", "failed", _latency_summary(p95=2000.001, baseline_missing=True))

    line_eq = _threshold_line(generate_report(cfg, store.get_run("lat_eq")), "总体 P95")
    assert "✅" in line_eq
    line_gt = _threshold_line(generate_report(cfg, store.get_run("lat_gt")), "总体 P95")
    assert "❌" in line_gt


def test_latency_baseline_missing_hint(env):
    cfg, store = env
    _make_run(store, "lat3", "latency", "failed", _latency_summary(baseline_missing=True))
    report = generate_report(cfg, store.get_run("lat3"))
    assert "基线缺失" in report
    line_reg = _threshold_line(report, "基线 P95 回归幅度")
    assert "—（本 suite 无此指标）" in line_reg


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------
def test_quality_report_low_scores_with_reply(env):
    cfg, store = env
    _make_run(store, "q1", "quality", "failed", _quality_summary())
    report = generate_report(cfg, store.get_run("q1"))
    assert "三维评分" in report and "overall_avg" in report
    assert "低分案例清单" in report
    assert "别难过啦，吃点好的吧。" in report and "早点休息。" in report  # 回复原文
    assert "未接住用户的情绪" in report                                   # judge 理由
    assert "evening_debrief" in report
    line = _threshold_line(report, "三维综合均分")
    assert "❌" in line and "2.9" in line
    assert "失败轮次：evening_debrief 第 3 轮" in report
    assert "judge 判分失败案例数：1" in report


def test_quality_threshold_boundary_35_vs_349(env):
    """质量均分边界：3.5 → ✅（≥）；3.499 → ❌。"""
    cfg, store = env
    ok = _quality_summary()
    ok["overall_avg"] = 3.5
    _make_run(store, "q_eq", "quality", "passed", ok)
    bad = _quality_summary()
    bad["overall_avg"] = 3.499
    _make_run(store, "q_lt", "quality", "failed", bad)

    line_eq = _threshold_line(generate_report(cfg, store.get_run("q_eq")), "三维综合均分")
    assert "✅" in line_eq
    line_lt = _threshold_line(generate_report(cfg, store.get_run("q_lt")), "三维综合均分")
    assert "❌" in line_lt


# ---------------------------------------------------------------------------
# judge_unavailable 降级
# ---------------------------------------------------------------------------
def test_judge_unavailable_memory_decay_report_degraded(env):
    cfg, store = env
    summary = _memory_summary()
    summary["judge_unavailable"] = True
    summary["judge_unavailable_reason"] = "JudgeUnavailableError: boom"
    summary["retention_matrix"] = {}  # 降级后无保持率数据
    summary["retrieval_hit_rate"] = {}
    summary["reactivation_contrast"] = None
    _make_run(store, "md_ju", "memory_decay", "judge_unavailable", summary)
    report = generate_report(cfg, store.get_run("md_ju"))  # 不抛异常
    assert "降级报告" in report
    line = _threshold_line(report, "1年 overall 保持率")
    assert "—（本 suite 无此指标）" in line


def test_judge_unavailable_quality_report_degraded(env):
    cfg, store = env
    _make_run(store, "q_ju", "quality", "judge_unavailable", _quality_judge_unavailable_summary())
    report = generate_report(cfg, store.get_run("q_ju"))  # 不抛异常
    assert "降级报告" in report
    assert "judge 服务不可用" in report
    assert "（无数据）" in report  # 缺 dimensions/overall_avg/low_scores → 无数据渲染


def test_metrics_summary_none_renders_no_data(env):
    """metrics_summary=None（如 latency error 终态）→ 全 "（无数据）"，不抛异常。"""
    cfg, store = env
    store.create_run("err1", "latency")
    store.finish_run("err1", "error", metrics_summary=None, error="主服务不可达")
    report = generate_report(cfg, store.get_run("err1"))
    assert "（无数据）" in report
    assert "run error：主服务不可达" in report


# ---------------------------------------------------------------------------
# 清理残留（detail.json cleanup.remaining > 0 计异常）
# ---------------------------------------------------------------------------
def test_memory_decay_cleanup_residue_listed(env):
    cfg, store = env
    _make_run(store, "md_clean", "memory_decay", "passed", _memory_summary())
    store.save_run_artifacts("md_clean", {"cleanup": {"attempted": 5, "deleted": 3, "remaining": 2}})
    report = generate_report(cfg, store.get_run("md_clean"))
    assert "清理残留：仍有 2 条记忆未删除" in report

    _make_run(store, "md_clean2", "memory_decay", "passed", _memory_summary())
    report2 = generate_report(cfg, store.get_run("md_clean2"))  # 无 detail.json → 不抛异常不误报
    assert "清理残留" not in report2


# ---------------------------------------------------------------------------
# write_report 落盘
# ---------------------------------------------------------------------------
def test_write_report_writes_file_and_missing_raises(env):
    cfg, store = env
    _make_run(store, "w1", "memory_decay", "passed", _memory_summary())
    path = write_report(cfg, "w1")
    assert path.endswith("report.md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "# CXO-EvalKit 评测报告" in content
    assert content == generate_report(cfg, store.get_run("w1"))

    with pytest.raises(ValueError):
        write_report(cfg, "no_such_run")


# ---------------------------------------------------------------------------
# API run_report 端点
# ---------------------------------------------------------------------------
def test_api_report_endpoint(tmp_path):
    cfg = EvalConfig.model_validate({"data_dir": str(tmp_path / "data")})
    store = EvalStore(cfg.data_dir)
    _make_run(store, "run_ok", "memory_decay", "passed", _memory_summary())
    store.create_run("run_running", "quality")  # 未终态
    try:
        with TestClient(create_app(cfg)) as client:
            # 终态 run：报告现生成并返回 200 text/markdown
            resp = client.get("/api/v1/runs/run_ok/report")
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/markdown")
            assert "# CXO-EvalKit 评测报告" in resp.text
            assert "## 二、阈值逐项判定" in resp.text
            # report.md 已落盘
            assert (tmp_path / "data" / "runs" / "run_ok" / "report.md").exists()

            # running 状态 run：不得为其造报告 → 仍 404
            assert client.get("/api/v1/runs/run_running/report").status_code == 404
            # run 不存在 → 404
            assert client.get("/api/v1/runs/missing/report").status_code == 404
    finally:
        store.close()
