"""CX-O-Autonomy 持久化簇（第八轮 G1：R1/R2/R3/R4）单元测试。

覆盖（2026-09-27 人类裁决：预算台账与急停档持久化已随「删除预算记账 / 急停」移除）：
① _atomic_io.atomic_write_json —— 写成功内容正确、写盘中断（os.replace 抛
   OSError）后原文件内容保持完整且无 .tmp 残留、覆盖已存在文件安全；
② load 坏档回退 —— autonomy_config.json / dream_config.json 损坏时返回默认
   配置并生成 .corrupt 留痕文件（原文件移除）；
③ 遗留 manager_state.json（status=budget_limited / error）经引擎载入归一化为 running。

运行：python -m pytest tests/test_autonomy_persistence.py -q
"""

import json
from pathlib import Path

import pytest

from server.autonomy._atomic_io import atomic_write_json
from server.autonomy.config import AutonomyConfig, load_config, save_config
from server.autonomy.core.loop.autonomy_engine import AutonomyEngine
from server.autonomy.core.motivation.state import MotivationState
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.config import load_config as load_dream_config
from server.autonomy.manager import AutonomyManager
from server.autonomy.safety.audit import AuditStore


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


# ================================================================ ③ 引擎载入遗留状态
def _build_engine(tmp_path: Path) -> AutonomyEngine:
    """构造最小依赖引擎：sensor 非 ContextSensor → 用户在线策略跳过，聚焦状态载入。"""
    manager = AutonomyManager(AutonomyConfig(store_path=str(tmp_path)))
    return AutonomyEngine(
        manager=manager,
        motivation=MotivationState(),
        circadian=object(),  # _current_phase 异常兜底 active
        sensor=object(),  # 非 ContextSensor → 用户在线策略跳过
        rss=None,
        hotspot=None,
        memory_actions=None,
        planner=None,
        diary=None,
        evaluator=None,
        content_gate=None,
        rate_limiter=None,
        audit=AuditStore(path=str(tmp_path / "audit.jsonl")),
        handlers={},
    )


class TestLegacyManagerStateNormalization:
    @pytest.mark.parametrize("legacy_status", ["budget_limited", "error"])
    def test_legacy_status_normalized_to_running(self, tmp_path, legacy_status):
        """不变量④：遗留 manager_state.json 非法 status 经引擎载入归一化为 running。"""
        (tmp_path / "manager_state.json").write_text(
            json.dumps({"status": legacy_status}), encoding="utf-8"
        )
        engine = _build_engine(tmp_path)
        assert engine.manager.status == "running"

    def test_valid_status_preserved(self, tmp_path):
        """对照组：合法 status（paused）不被归一化覆盖。"""
        (tmp_path / "manager_state.json").write_text(
            json.dumps({"status": "paused"}), encoding="utf-8"
        )
        engine = _build_engine(tmp_path)
        assert engine.manager.status == "paused"
