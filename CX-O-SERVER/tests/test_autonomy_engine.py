"""AutonomyEngine 循环间隔归一化测试（修复第六轮 B2：loop_interval_minutes 允许 0 空转）。"""
import asyncio
import json
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
        content_gate=None,
        rate_limiter=None,
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


# ===========================================================================
# 第四轮体检修复（20260827）H11/H12/L11 定向测试
# ===========================================================================
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from server.autonomy.config import AutonomyConfig  # noqa: E402
from server.autonomy.manager import AutonomyManager  # noqa: E402
from server.autonomy.safety.audit import AuditStore  # noqa: E402

_PLAN = {
    "action": "read_news",
    "target": "新闻",
    "payload": {},
    "reason": "好奇心较高",
    "expected_outcome": "获取素材",
}


def _build_full_engine(tmp_path):
    """构造外部依赖全 mock 的引擎（真实 AutonomyManager/AuditStore）。"""
    from unittest.mock import AsyncMock

    cfg = AutonomyConfig(store_path=str(tmp_path))
    manager = AutonomyManager(cfg)
    manager.enable()

    planner = AsyncMock()
    planner.plan.return_value = dict(_PLAN)

    diary = AsyncMock()
    diary.generate_diary.return_value = {"diary": "d", "memory_id": "mem-1"}

    handler = AsyncMock(return_value=[{"title": "n"}])
    audit = AuditStore(path=str(tmp_path / "audit.jsonl"))

    class _NoSensor:
        pass

    class _StubCircadian:
        diary_time = datetime.strptime("02:00", "%H:%M").time()

        def current_phase(self, now):
            return "active"

    from server.autonomy.core.motivation.state import MotivationState

    engine = AutonomyEngine(
        manager=manager,
        motivation=MotivationState(),
        circadian=_StubCircadian(),
        sensor=_NoSensor(),
        rss=None,
        hotspot=None,
        memory_actions=None,
        planner=planner,
        diary=diary,
        evaluator=None,
        content_gate=None,
        rate_limiter=None,
        audit=audit,
        handlers={"autonomy_read_news": handler},
        persona={},
        loop_interval_minutes=15,
    )
    return engine


@pytest.mark.asyncio
class TestLoopTermination:
    """[评审 Issue2] 主循环终止路径——标志位守卫 + 任务取消双路径均须生效。

    背景：主循环改为无条件循环后，终止一度单点依赖 `stop()` 的 task.cancel()
    （守卫被删）。本组用例锁定两条冗余终止路径，防止"stop() 后主循环不退出"回归。
    """

    async def test_stop_terminates_idle_loop(self, tmp_path):
        """空闲等待期（sleep 中）调用 stop()：主循环任务必须终止、running 置 False。"""
        engine = _build_full_engine(tmp_path)
        task = await engine.start()
        assert task.done() is False
        await asyncio.sleep(0.05)

        await asyncio.wait_for(engine.stop(), timeout=5.0)

        assert task.done() is True, "stop() 后主循环任务仍在运行（未终止）"
        assert engine.running is False

    async def test_stop_terminates_mid_round(self, tmp_path):
        """单轮执行中（轮内长 await）调用 stop()：任务同样必须终止。"""
        engine = _build_full_engine(tmp_path)
        engine.loop_interval_minutes = 0.01  # 0.6s 间隔，便于迅速进入轮内

        entered = asyncio.Event()

        async def _hanging_round():
            entered.set()
            await asyncio.sleep(300)  # 模拟轮内长时间 await

        engine._run_round = _hanging_round  # type: ignore[method-assign]

        task = await engine.start()
        await asyncio.wait_for(entered.wait(), timeout=5.0)

        await asyncio.wait_for(engine.stop(), timeout=5.0)

        assert task.done() is True, "轮内 stop() 后主循环任务仍在运行（未终止）"
        assert engine.running is False

    async def test_running_flag_guard_exits_loop_without_cancel(self, tmp_path):
        """守卫路径独立生效：仅置 running=False（不发取消）时，循环须在下一轮自行退出。

        该用例直接锁定"退出条件"本身——即便取消路径被未来改动削弱（如轮内新增
        吞 CancelledError 的写法），标志位守卫仍能终止主循环。
        """
        engine = _build_full_engine(tmp_path)
        engine.loop_interval_minutes = 0.01  # 0.6s 间隔

        task = await engine.start()
        await asyncio.sleep(0.1)

        engine.running = False  # 模拟 stop() 的置位，但不调用 task.cancel()
        await asyncio.wait_for(task, timeout=5.0)

        assert task.done() is True, "仅置 running=False 时主循环未自行退出（守卫失效）"
        assert task.cancelled() is False  # 走守卫正常返回，而非取消


@pytest.mark.asyncio
class TestLegacyManagerStateDoesNotHalt:
    """[T5.4] 遗留 manager_state.json（status=error）经载入归一化后不再导致停摆。

    2026-09-27 人类裁决删除急停档后就只剩 manager 遗留态这一条路径：
    载入时非法 status 归一化为 running，本轮照常进入规划与执行路径。
    """

    async def test_legacy_manager_state_still_enters_planning_path(self, tmp_path):
        """加载遗留 manager_state.json(status=error) 后运行一轮：
        遗留档被归一化、本轮仍进入规划与执行路径（非 skipped、不终止）。"""
        # 升级前遗留档
        (tmp_path / "manager_state.json").write_text(
            json.dumps({"status": "error"}), encoding="utf-8"
        )

        engine = _build_full_engine(tmp_path)

        # 遗留档不再把系统置于停摆态
        assert engine.manager.status == "running"

        await engine._run_round()

        # 进入规划/执行路径：planner 被调用，审计 result=success（非 skipped）
        engine.planner.plan.assert_awaited_once()
        items = engine.audit.list(limit=None).get("items", [])
        assert items[-1]["result"] == "success"


@pytest.mark.asyncio
class TestLocalAuditTimestamp:
    """[H12] 审计时间戳本地化——消除 UTC/本地日期前缀错配。"""

    async def test_audit_timestamp_is_local_aware(self, tmp_path):
        engine = _build_full_engine(tmp_path)
        await engine._run_round()

        entry = engine.audit.list(limit=None)["items"][0]
        ts = entry["timestamp"]
        parsed = datetime.fromisoformat(ts)
        # 与本机当前 utcoffset 一致（UTC 会差出整小时偏移）
        assert parsed.utcoffset() is not None
        expected_offset = datetime.now().astimezone().utcoffset()
        assert parsed.utcoffset() == expected_offset
        # 本地日期前缀可直接命中当日日记过滤
        local_day = datetime.now().astimezone().date().isoformat()
        assert ts.startswith(local_day)

    async def test_elapsed_minutes_handles_local_stamps(self, tmp_path):
        engine = _build_full_engine(tmp_path)
        await engine._run_round()
        minutes = engine._elapsed_minutes()
        # last_cycle_at 为刚写入的本地 aware 时间戳 → 差值近似 0 且不为负
        assert 0.0 <= minutes < 1.0


@pytest.mark.asyncio
class TestDiaryFailureKeepsPending:
    """[L11] 日记生成失败不更新 diary_last_at（保留可重试），审计记 failed。"""

    async def test_failure_does_not_touch_diary_last_at(self, tmp_path):
        engine = _build_full_engine(tmp_path)

        async def boom(daily_log, date=""):
            raise RuntimeError("diary backend down")

        engine.diary.generate_diary = boom
        now = datetime(2026, 8, 27, 2, 5)
        result = await engine._maybe_diary(now=now)

        assert result["memory_id"] is None
        assert engine.manager.diary_last_at is None  # 未谎报已写
        diary_items = [
            e for e in engine.audit.list(limit=None)["items"]
            if e.get("trigger_reason") == "diary_time"
        ]
        assert len(diary_items) == 1
        assert diary_items[0]["result"] == "failed"

    async def test_success_updates_diary_last_at(self, tmp_path):
        engine = _build_full_engine(tmp_path)  # generate_diary 返回 memory_id
        now = datetime(2026, 8, 27, 2, 5)
        result = await engine._maybe_diary(now=now)
        assert result["memory_id"] == "mem-1"
        assert engine.manager.diary_last_at is not None


class TestTodayDailyLogLocalDay:
    """[H12] autonomy/main._today_daily_log —— UTC 历史条目按本地日归档不再丢失。"""

    def test_entry_in_local_day_converts_utc_to_local(self):
        from server.autonomy import main as autonomy_main

        # UTC 2026-08-26T20:00:00+00:00 == 本地(+8) 2026-08-27 04:00 → 属本地 27 日
        entry = {"timestamp": "2026-08-26T20:00:00+00:00"}
        assert autonomy_main._entry_in_local_day(entry, "2026-08-27") is True
        assert autonomy_main._entry_in_local_day(entry, "2026-08-26") is False

    def test_entry_in_local_day_naive_falls_back_to_prefix(self):
        from server.autonomy import main as autonomy_main

        naive_same_day = {"timestamp": "2026-08-27T03:15:00"}
        assert autonomy_main._entry_in_local_day(naive_same_day, "2026-08-27") is True
        naive_other_day = {"timestamp": "2026-08-20T03:15:00"}
        assert autonomy_main._entry_in_local_day(naive_other_day, "2026-08-27") is False
        garbage = {"timestamp": "not-a-date"}
        assert autonomy_main._entry_in_local_day(garbage, "2026-08-27") is False

    def test_today_daily_log_includes_utc_entries_of_local_day(self, monkeypatch):
        """同一瞬间的 UTC 表示与本地前缀表示都被归入当日；陈旧条目被排除。"""
        from types import SimpleNamespace

        from server.autonomy import main as autonomy_main

        local_now = datetime.now().astimezone()
        day = local_now.date().isoformat()
        utc_same_moment = (local_now - timedelta(hours=6)).astimezone(timezone.utc).isoformat()

        items = [
            {"id": "utc", "timestamp": utc_same_moment},          # 同一瞬间 UTC 表示
            {"id": "prefix", "timestamp": f"{day}T12:00:00"},     # 本地日直接命中
            {"id": "old", "timestamp": "1999-01-01T00:00:00"},    # 陈旧排除
            {"no_ts": True},                                       # 无时间戳排除
        ]
        fake_store = SimpleNamespace(list=lambda limit=None: {"items": items})
        monkeypatch.setattr(autonomy_main, "_audit_store", fake_store)

        got = autonomy_main._today_daily_log()
        ids = {e["id"] for e in got}
        assert ids == {"utc", "prefix"}


# ===========================================================================
# 动机接线与焦点回写（20260930 修复"动机退化为纯时间函数"缺陷）
# ===========================================================================
from server.autonomy.core.motivation.state import MotivationState  # noqa: E402

# 一个 tick 周期（loop_interval_minutes=15）对应的分钟数与小时数
_TICK_MINUTES = 15.0
_TICK_HOURS = _TICK_MINUTES / 60.0


def _make_round_engine(tmp_path, plan, handlers, motivation=None):
    """构造可指定 plan/handlers 的引擎（真实 AutonomyManager/AuditStore/MotivationState）。"""
    from unittest.mock import AsyncMock

    cfg = AutonomyConfig(store_path=str(tmp_path))
    manager = AutonomyManager(cfg)
    manager.enable()

    planner = AsyncMock()
    planner.plan.return_value = dict(plan)

    class _NoSensor:
        pass

    class _StubCircadian:
        diary_time = datetime.strptime("02:00", "%H:%M").time()

        def current_phase(self, now):
            return "active"

    return AutonomyEngine(
        manager=manager,
        motivation=motivation if motivation is not None else MotivationState(),
        circadian=_StubCircadian(),
        sensor=_NoSensor(),
        rss=None,
        hotspot=None,
        memory_actions=None,
        planner=planner,
        diary=None,
        evaluator=None,
        content_gate=None,
        rate_limiter=None,
        audit=AuditStore(path=str(tmp_path / "audit.jsonl")),
        handlers=handlers,
        persona={},
        loop_interval_minutes=15,
    )


class TestMotivationFeedbackWiring:
    """4 个 record_* 入口此前在生产代码零调用 → 动机只剩 tick 并饱和。"""

    @pytest.mark.asyncio
    async def test_info_ingestion_drops_curiosity_and_raises_creative(self, tmp_path):
        from unittest.mock import AsyncMock

        st = MotivationState(curiosity=0.9, creative_drive=0.2)
        engine = _make_round_engine(
            tmp_path, _PLAN, {"autonomy_read_news": AsyncMock(return_value=[{"title": "n"}])}, st
        )
        await engine._run_round()
        assert st.curiosity == pytest.approx((0.9 + 0.05 * _TICK_HOURS) * 0.7)
        assert st.creative_drive == pytest.approx(0.2 - 0.02 * _TICK_HOURS + 0.10)

    @pytest.mark.asyncio
    async def test_info_ingestion_without_content_skips_material(self, tmp_path):
        """取回空列表（无素材）时只记信息摄入，不提升创意欲。"""
        from unittest.mock import AsyncMock

        st = MotivationState(curiosity=0.9, creative_drive=0.2)
        engine = _make_round_engine(
            tmp_path, _PLAN, {"autonomy_read_news": AsyncMock(return_value=[])}, st
        )
        await engine._run_round()
        assert st.creative_drive == pytest.approx(0.2 - 0.02 * _TICK_HOURS)

    @pytest.mark.asyncio
    async def test_interaction_drops_social_need(self, tmp_path):
        from unittest.mock import AsyncMock

        plan = {
            "action": "write_post",
            "target": "weibo",
            "payload": {"platform": "weibo", "draft": "hi"},
            "reason": "",
            "expected_outcome": "",
        }
        st = MotivationState(social_need=0.8)
        engine = _make_round_engine(
            tmp_path, plan, {"autonomy_write_post": AsyncMock(return_value={"status": "ok"})}, st
        )
        await engine._run_round()
        assert st.social_need == pytest.approx((0.8 + 0.04 * _TICK_HOURS) * 0.7)

    @pytest.mark.asyncio
    async def test_activity_raises_fatigue(self, tmp_path):
        from unittest.mock import AsyncMock

        plan = {
            "action": "start_live",
            "target": "",
            "payload": {"script": "s"},
            "reason": "",
            "expected_outcome": "",
        }
        st = MotivationState(fatigue=0.1)
        engine = _make_round_engine(
            tmp_path, plan, {"autonomy_start_live": AsyncMock(return_value={"status": "ok"})}, st
        )
        await engine._run_round()
        assert st.fatigue == pytest.approx(0.1 - 0.10 * _TICK_HOURS + 0.15)

    @pytest.mark.asyncio
    async def test_failed_action_produces_no_feedback(self, tmp_path):
        """只认 handler 的 result == "success"：失败/未执行不得改动机。"""
        from unittest.mock import AsyncMock

        st = MotivationState(curiosity=0.9)
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        engine = _make_round_engine(tmp_path, _PLAN, {"autonomy_read_news": handler}, st)
        await engine._run_round()
        assert st.curiosity == pytest.approx(0.9 + 0.05 * _TICK_HOURS)

    @pytest.mark.asyncio
    async def test_wait_action_produces_no_feedback(self, tmp_path):
        st = MotivationState(curiosity=0.9)
        plan = {"action": "wait", "target": "", "payload": {}, "reason": "", "expected_outcome": ""}
        engine = _make_round_engine(tmp_path, plan, {}, st)
        await engine._run_round()
        assert st.curiosity == pytest.approx(0.9 + 0.05 * _TICK_HOURS)

    @pytest.mark.asyncio
    async def test_creation_consumes_creative_drive(self, tmp_path):
        """write_memory / write_diary 成功 → record_creation（GN-004 Q5 泄压阀）。

        每轮用独立子目录：AutonomyEngine 构造时会按 store_dir 恢复
        motivation_state.json，复用同一目录会覆盖本用例注入的动机实例。
        """
        from unittest.mock import AsyncMock

        for idx, (action, tool) in enumerate(
            (("write_memory", "autonomy_write_memory"),
             ("write_diary", "autonomy_write_diary"))
        ):
            store = tmp_path / f"case{idx}"
            store.mkdir()
            plan = {
                "action": action,
                "target": "",
                "payload": {"content": "x"},
                "reason": "",
                "expected_outcome": "",
            }
            st = MotivationState(creative_drive=0.8)
            engine = _make_round_engine(
                store, plan, {tool: AsyncMock(return_value={"ok": True})}, st
            )
            await engine._run_round()
            assert st.creative_drive == pytest.approx(
                (0.8 - 0.02 * _TICK_HOURS) * 0.5
            ), f"{action} 成功后 creative_drive 应按比例消费回落"

    @pytest.mark.asyncio
    async def test_failed_creation_does_not_consume(self, tmp_path):
        from unittest.mock import AsyncMock

        plan = {
            "action": "write_memory",
            "target": "",
            "payload": {"content": "x"},
            "reason": "",
            "expected_outcome": "",
        }
        st = MotivationState(creative_drive=0.8)
        engine = _make_round_engine(
            tmp_path, plan, {"autonomy_write_memory": AsyncMock(side_effect=RuntimeError("boom"))}, st
        )
        await engine._run_round()
        assert st.creative_drive == pytest.approx(0.8 - 0.02 * _TICK_HOURS)


class TestFocusWriteBack:
    """LLM 自报 focus → 引擎回写动机层并随 motivation_state.json 持久化。"""

    @pytest.mark.asyncio
    async def test_plan_focus_written_persisted_and_exposed(self, tmp_path):
        from unittest.mock import AsyncMock

        plan = dict(_PLAN, focus={"topic": "AI 芯片出口管制", "level": 0.8})
        st = MotivationState(curiosity=0.9)
        engine = _make_round_engine(
            tmp_path, plan, {"autonomy_read_news": AsyncMock(return_value=[{"title": "n"}])}, st
        )
        await engine._run_round()

        assert st.to_focus_dict() == {"topic": "AI 芯片出口管制", "level": 0.8}
        saved = json.loads((tmp_path / "motivation_state.json").read_text(encoding="utf-8"))
        assert saved["focus"] == {"topic": "AI 芯片出口管制", "level": 0.8}
        # 动机层 → manager → GET /api/autonomy/status 快照
        assert engine.manager.get_status()["focus"] == {
            "topic": "AI 芯片出口管制",
            "level": 0.8,
        }

    @pytest.mark.asyncio
    async def test_absent_focus_keeps_previous(self, tmp_path):
        from unittest.mock import AsyncMock

        st = MotivationState(curiosity=0.9, focus_topic="旧焦点", focus_level=0.4)
        engine = _make_round_engine(
            tmp_path, _PLAN, {"autonomy_read_news": AsyncMock(return_value=[])}, st
        )
        await engine._run_round()
        assert st.to_focus_dict() == {"topic": "旧焦点", "level": 0.4}

    @pytest.mark.asyncio
    async def test_plan_context_carries_current_focus(self, tmp_path):
        """规划上下文必须带当前焦点，使 LLM 可延续或更换关注对象。"""
        from unittest.mock import AsyncMock

        st = MotivationState(focus_topic="量子计算", focus_level=0.7)
        engine = _make_round_engine(
            tmp_path, _PLAN, {"autonomy_read_news": AsyncMock(return_value=[])}, st
        )
        await engine._run_round()
        ctx = engine.planner.plan.call_args.args[0]
        assert ctx["focus"] == {"topic": "量子计算", "level": 0.7}

    @pytest.mark.asyncio
    async def test_focus_persisted_across_reload(self, tmp_path):
        """重启续接：MotivationState.load 恢复焦点（动机层持久化为真源）。"""
        from unittest.mock import AsyncMock

        st = MotivationState()
        engine = _make_round_engine(
            tmp_path,
            dict(_PLAN, focus={"topic": "量子计算", "level": 0.55}),
            {"autonomy_read_news": AsyncMock(return_value=[])},
            st,
        )
        await engine._run_round()
        reloaded = MotivationState.load(store_path=str(tmp_path))
        assert reloaded.to_focus_dict() == {"topic": "量子计算", "level": 0.55}