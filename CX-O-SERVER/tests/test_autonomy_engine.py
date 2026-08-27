"""AutonomyEngine 循环间隔归一化测试（修复第六轮 B2：loop_interval_minutes 允许 0 空转）。"""
import types

from server.autonomy.core.loop.autonomy_engine import AutonomyEngine


def _make_engine(loop_interval_minutes, monkeypatch, tmp_path) -> AutonomyEngine:
    """构造最小 AutonomyEngine，隔离持久化副作用（走临时目录并跳过状态恢复）。"""
    monkeypatch.setattr(
        "server.autonomy.core.loop.autonomy_engine.resolve_store_dir",
        lambda: str(tmp_path),
    )
    monkeypatch.setattr(
        "server.autonomy.core.loop.autonomy_engine.AutonomyEngine._load_persisted_state",
        lambda self: None,
    )
    manager = types.SimpleNamespace()
    return AutonomyEngine(
        manager=manager,
        motivation=None,
        circadian=None,
        sensor=None,
        rss=None,
        hotspot=None,
        memory_actions=None,
        planner=None,
        diary=None,
        evaluator=None,
        token_ledger=None,
        content_gate=None,
        rate_limiter=None,
        killswitch=None,
        audit=None,
        handlers={},
        persona={},
        loop_interval_minutes=loop_interval_minutes,
    )


def test_zero_interval_raised_to_one_minute(monkeypatch, tmp_path) -> None:
    """配置 0 时被提升为 1 分钟，interval_seconds >= 60，避免空转忙循环。"""
    engine = _make_engine(loop_interval_minutes=0, monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert engine.loop_interval_minutes == 1.0
    assert engine.loop_interval_minutes * 60 >= 60


def test_negative_interval_raised_to_one_minute(monkeypatch, tmp_path) -> None:
    engine = _make_engine(loop_interval_minutes=-3, monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert engine.loop_interval_minutes == 1.0
    assert engine.loop_interval_minutes * 60 >= 60


def test_positive_interval_preserved(monkeypatch, tmp_path) -> None:
    """正常取值不被破坏。"""
    engine = _make_engine(loop_interval_minutes=5, monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert engine.loop_interval_minutes == 5.0
    assert engine.loop_interval_minutes * 60 == 300