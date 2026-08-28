"""CX-O-Autonomy 持久化簇（第八轮 G1：R1/R2/R3/R4）单元测试。

覆盖：
① _atomic_io.atomic_write_json —— 写成功内容正确、写盘中断（os.replace 抛
   OSError）后原文件内容保持完整且无 .tmp 残留、覆盖已存在文件安全；
② load 坏档回退 —— autonomy_config.json / dream_config.json 损坏时返回默认
   配置并生成 .corrupt 留痕文件（原文件移除）；
③ KillSwitch 状态变更（emergency_stop/pause/resume/set_sleeping/
   update_from_user_online）后 store 文件内容同步，未变化不重复落盘；
④ TokenLedger save 后文件内容正确；引擎每轮末尾统一持久化台账（R4 接线）。

运行：python -m pytest tests/test_autonomy_persistence.py -q
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from server.autonomy._atomic_io import atomic_write_json
from server.autonomy.config import AutonomyConfig, load_config, save_config
from server.autonomy.core.loop.autonomy_engine import AutonomyEngine
from server.autonomy.core.motivation.state import MotivationState
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.config import load_config as load_dream_config
from server.autonomy.manager import AutonomyManager
from server.autonomy.safety.audit import AuditStore
from server.autonomy.safety.budget.token_ledger import TokenLedger
from server.autonomy.safety.killswitch import KillSwitch


# ================================================================ ① 原子写
class TestAtomicWriteJson:
    def test_write_success_content_and_no_tmp(self, tmp_path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"a": 1, "b": "中文"})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": "中文"}
        assert list(tmp_path.glob("*.tmp")) == []  # 无临时文件残留

    def test_overwrite_existing_file(self, tmp_path):
        target = tmp_path / "state.json"
        atomic_write_json(target, {"v": 1})
        atomic_write_json(target, {"v": 2})  # os.replace 覆盖已存在文件安全
        assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}

    def test_interrupted_write_keeps_original(self, tmp_path, monkeypatch):
        """写盘中断模拟：os.replace 抛 OSError 后原文件内容保持完整。"""
        target = tmp_path / "state.json"
        target.write_text('{"v": 1}', encoding="utf-8")

        def _boom(src, dst):
            raise OSError("simulated crash before replace")

        monkeypatch.setattr("os.replace", _boom)
        with pytest.raises(OSError):
            atomic_write_json(target, {"v": 2})
        # 原文件内容保持完整（未被截断/覆盖）
        assert target.read_text(encoding="utf-8") == '{"v": 1}'
        # 临时文件已在 finally 中清理
        assert list(tmp_path.glob("*.tmp")) == []


# ================================================================ ② load 坏档回退
class TestLoadCorruptFallback:
    def test_autonomy_config_corrupt_returns_defaults(self, tmp_path):
        cfg_path = tmp_path / "autonomy_config.json"
        cfg_path.write_text('{"enabled": tru', encoding="utf-8")  # 截断坏档
        cfg = load_config(str(tmp_path))
        assert isinstance(cfg, AutonomyConfig)
        assert cfg.enabled is False  # 默认值（非 500/异常）
        assert cfg.store_path == str(tmp_path)
        # 坏档改名 .corrupt 留痕，原路径移除
        assert (tmp_path / "autonomy_config.json.corrupt").exists()
        assert not cfg_path.exists()

    def test_dream_config_corrupt_returns_defaults(self, tmp_path):
        cfg_path = tmp_path / "dream_config.json"
        cfg_path.write_text('{"dream_tem', encoding="utf-8")
        cfg = load_dream_config(str(tmp_path))
        assert isinstance(cfg, DreamConfig)
        assert cfg.enabled is False
        assert (tmp_path / "dream_config.json.corrupt").exists()
        assert not cfg_path.exists()

    def test_valid_load_unaffected(self, tmp_path):
        cfg = AutonomyConfig(enabled=True, agent_id="测试", store_path=str(tmp_path))
        save_config(cfg)
        loaded = load_config(str(tmp_path))
        assert loaded.enabled is True
        assert loaded.agent_id == "测试"


# ================================================================ ③ KillSwitch 接线
class TestKillSwitchPersistenceWiring:
    def test_emergency_stop_persists(self, tmp_path):
        path = tmp_path / "killswitch.json"
        ks = KillSwitch(store_path=str(path))
        ks.emergency_stop()  # 状态变更即落盘（无需显式 save）
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"enabled": False, "paused": False, "sleeping": False}
        restored = KillSwitch(store_path=str(path)).load()
        assert restored.enabled is False
        assert restored.is_active() is False

    def test_pause_and_resume_persist(self, tmp_path):
        path = tmp_path / "killswitch.json"
        ks = KillSwitch(store_path=str(path))
        ks.pause()
        assert json.loads(path.read_text(encoding="utf-8"))["paused"] is True
        ks.resume()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"enabled": True, "paused": False, "sleeping": False}

    def test_set_sleeping_persists_and_skips_unchanged(self, tmp_path, monkeypatch):
        ks = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
        calls = []

        def _spy_save():
            calls.append(1)
            return str(ks.store_path)

        monkeypatch.setattr(ks, "save", _spy_save)
        ks.set_sleeping(True)
        assert len(calls) == 1  # 变化 → 落盘
        ks.set_sleeping(True)
        assert len(calls) == 1  # 未变化 → 不重复落盘（避免轮级高频写）
        ks.set_sleeping(False)
        assert len(calls) == 2

    def test_update_from_user_online_persists(self, tmp_path):
        path = tmp_path / "killswitch.json"
        ks = KillSwitch(store_path=str(path))
        ks.update_from_user_online(True, True)  # 用户在线 → sleeping
        assert json.loads(path.read_text(encoding="utf-8"))["sleeping"] is True


# ================================================================ ④ TokenLedger 接线
class TestTokenLedgerPersistenceWiring:
    def test_save_file_content(self, tmp_path):
        path = tmp_path / "token_ledger.json"
        ledger = TokenLedger(daily_token_limit=1000, store_path=str(path))
        ledger.add_tokens({"total_tokens": 300})
        ledger.add_llm_call()
        ledger.save()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["used_tokens"] == 300
        assert data["llm_calls"] == 1
        assert data["alerted"] is False
        assert data["date"]

    def test_save_overwrites_previous_content(self, tmp_path):
        path = tmp_path / "token_ledger.json"
        ledger = TokenLedger(daily_token_limit=1000, store_path=str(path))
        ledger.add_tokens(100)
        ledger.save()
        ledger.add_tokens(50)
        ledger.save()
        assert json.loads(path.read_text(encoding="utf-8"))["used_tokens"] == 150


# ================================================================ ⑤ 引擎轮末持久化
def _build_engine(tmp_path: Path) -> AutonomyEngine:
    """构造最小依赖引擎：manager 未启用 → 轮级跳过路径，聚焦轮末台账持久化。"""
    manager = AutonomyManager(AutonomyConfig(store_path=str(tmp_path)))
    return AutonomyEngine(
        manager=manager,
        motivation=MotivationState(),
        circadian=object(),  # _current_phase 异常兜底 active，不会被跳过路径触达
        sensor=object(),  # 非 ContextSensor → 用户在线策略跳过
        rss=None,
        hotspot=None,
        memory_actions=None,
        planner=None,
        diary=None,
        evaluator=None,
        token_ledger=TokenLedger(
            daily_token_limit=1000, store_path=str(tmp_path / "token_ledger.json")
        ),
        content_gate=None,
        rate_limiter=None,
        killswitch=KillSwitch(store_path=str(tmp_path / "killswitch.json")),
        audit=AuditStore(path=str(tmp_path / "audit.jsonl")),
        handlers={},
    )


@pytest.mark.asyncio
async def test_round_end_persists_token_ledger(tmp_path):
    """引擎每轮末尾统一持久化台账（R4 接线：无显式 save 调用即落盘）。"""
    engine = _build_engine(tmp_path)
    ledger_path = tmp_path / "token_ledger.json"
    assert not ledger_path.exists()
    engine.token_ledger.add_tokens(123)
    await engine._run_round()
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert data["used_tokens"] == 123


@pytest.mark.asyncio
async def test_round_end_ledger_save_failure_not_fatal(tmp_path, monkeypatch):
    """台账持久化失败仅告警，不影响本轮收尾（last_cycle_at 正常写入）。"""
    engine = _build_engine(tmp_path)

    def _boom():
        raise OSError("disk full")

    monkeypatch.setattr(engine.token_ledger, "save", _boom)
    await engine._run_round()  # 不应抛异常
    assert engine.manager.last_cycle_at is not None
    assert json.loads(
        (tmp_path / "manager_state.json").read_text(encoding="utf-8")
    )["last_cycle_at"] == engine.manager.last_cycle_at
