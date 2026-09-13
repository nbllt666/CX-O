"""config 单测：默认补全 / 部分覆盖 / to_safe_dict 剥离 key / 深合并。全 Mock，无网络。"""
import json

from evalkit.config import EvalConfig, load_config, merge_overrides


def test_empty_config_fills_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    cfg = load_config(str(path))
    assert cfg.target.base_url == "http://host.docker.internal:8000"
    assert cfg.target.admin_api_key == ""
    assert cfg.judge.api_base == ""
    assert cfg.judge.model == ""
    assert cfg.judge.api_key == ""
    assert cfg.judge.timeout_seconds == 60
    assert cfg.thresholds.memory.retention_1y_min == 0.6
    assert cfg.thresholds.memory.permanent_retention == 1.0
    assert cfg.thresholds.memory.reactivation_must_beat_control is True
    assert cfg.thresholds.latency.p95_ms == 2000
    assert cfg.thresholds.latency.regression_pct == 20
    assert cfg.thresholds.quality.avg_min == 3.5
    assert cfg.memory_decay.interval_days == [30, 180, 365, 1095]
    assert cfg.memory_decay.reactivation_visit_every_days == 30
    assert cfg.latency.rounds == 10
    assert cfg.latency.probe_timeout_seconds == 120
    assert cfg.latency.concurrency_levels == [1]
    assert cfg.data_dir == "data"


def test_partial_json_overrides(tmp_path):
    payload = {
        "target": {"base_url": "http://example:9000", "admin_api_key": "sk-admin"},
        "judge": {"model": "judge-x", "timeout_seconds": 5},
        "thresholds": {"quality": {"avg_min": 4.0}},
        "latency": {"rounds": 3},
        "data_dir": "/tmp/evalkit-data",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_config(str(path))
    assert cfg.target.base_url == "http://example:9000"
    assert cfg.target.admin_api_key == "sk-admin"
    assert cfg.judge.model == "judge-x"
    assert cfg.judge.timeout_seconds == 5
    assert cfg.judge.api_base == ""  # 未覆盖字段保持默认
    assert cfg.thresholds.quality.avg_min == 4.0
    assert cfg.thresholds.latency.p95_ms == 2000  # 兄弟字段默认补全
    assert cfg.latency.rounds == 3
    assert cfg.latency.concurrency_levels == [1]
    assert cfg.data_dir == "/tmp/evalkit-data"


def test_to_safe_dict_strips_api_keys():
    cfg = EvalConfig.model_validate(
        {"target": {"admin_api_key": "sk-admin"}, "judge": {"api_key": "sk-judge"}}
    )
    safe = cfg.to_safe_dict()
    assert safe["target"]["admin_api_key"] == ""
    assert safe["judge"]["api_key"] == ""
    # 原对象不受影响（key 仅存于 config 对象）
    assert cfg.target.admin_api_key == "sk-admin"
    assert cfg.judge.api_key == "sk-judge"


def test_merge_overrides_deep_and_no_pollution():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    merged = merge_overrides(base, {"a": {"b": 9}})
    assert merged == {"a": {"b": 9, "c": 2}, "d": 3}
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}  # base 不被污染


def test_load_config_missing_file_with_explicit_path_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "not_exist.json"))
