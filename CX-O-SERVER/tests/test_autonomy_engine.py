"""CX-O-Autonomy P1-T8 主循环引擎集成测试（全部 mock 外部组件）。

覆盖：
① 单轮循环 感知→动机→规划→行动→审计 走通（断言 audit 追加条目、manager.last_action
   更新、各层组件被调用）
② 异常隔离：planner 抛错时 round 不冒泡、下一轮继续
③ 紧急停止后 killswitch.is_active() False、引擎不执行新轮次
④ sleep/wait 内部原语不调用 handler
⑤ write_post 被内容闸门拒绝时 result=blocked 且 handler 不被调用
⑥ 日记时刻触发日记并写记忆
⑦ 重启续接：motivation / manager 状态从持久化恢复

运行：python -m pytest tests/test_autonomy_engine.py -q
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.autonomy.config import AutonomyConfig
from server.autonomy.core.loop.autonomy_engine import AutonomyEngine
from server.autonomy.core.motivation.state import MotivationState
from server.autonomy.core.scheduler.circadian import CircadianScheduler
from server.autonomy.manager import AutonomyManager
from server.autonomy.safety.audit import AuditStore
from server.autonomy.safety.budget.token_ledger import TokenLedger
from server.autonomy.safety.gate.content_gate import ContentGate
from server.autonomy.safety.killswitch import KillSwitch
from server.autonomy.safety.ratelimit.limiter import RateLimiter

# 默认作息（对齐 config.ScheduleConfig 默认值，diary_time=02:00）
DEFAULT_SCHEDULE = {
    "wake_time": "08:00",
    "sleep_time": "02:00",
    "golden_start": "19:00",
    "golden_end": "23:00",
    "diary_time": "02:00",
    "quiet_windows": [],
}

# 标准规划结果（read_news，供单轮流水线测试）
READ_NEWS_PLAN = {
    "action": "read_news",
    "target": "新闻",
    "payload": {},
    "reason": "好奇心较高，摄入信息",
    "expected_outcome": "获取新鲜素材",
}


def build_engine(
    tmp_path,
    *,
    plan=None,
    circadian=None,
    killswitch=None,
    content_gate=None,
    handlers=None,
    diary=None,
    loop_interval_minutes=15,
):
    """构造一个外部组件全部 mock 的 AutonomyEngine。

    感知/规划/行动/反思用 AsyncMock；轻量组件用真实实现（MotivationState /
    CircadianScheduler / AuditStore / KillSwitch / RateLimiter / TokenLedger），
    便于断言持久化与审计行为。
    """
    cfg = AutonomyConfig(store_path=str(tmp_path))
    manager = AutonomyManager(cfg)
    manager.enable()

    motivation = MotivationState(
        curiosity=0.5, social_need=0.4, creative_drive=0.3, fatigue=0.1
    )

    sensor = MagicMock()
    sensor.snapshot.return_value = {
        "now_iso": "2026-08-22T10:00:00+08:00",
        "weekday": 5,
        "hour": 10,
        "is_user_online": False,
        "weather": {"available": False},
    }

    rss = AsyncMock()
    rss.fetch.return_value = [{"title": "新闻A", "link": "http://x/1", "summary": "摘要A"}]

    hotspot = AsyncMock()
    hotspot.get_hotspots.return_value = [
        {"title": "热点A", "link": "http://y/1", "snippet": "热点摘要"}
    ]

    memory_actions = AsyncMock()
    memory_actions.retrieve_memory.return_value = []

    planner = AsyncMock()
    planner.plan.return_value = plan if plan is not None else dict(READ_NEWS_PLAN)

    if diary is None:
        diary = AsyncMock()
        diary.generate_diary.return_value = {"diary": "今日日记", "memory_id": "mem-1"}

    evaluator = AsyncMock()
    evaluator.evaluate.return_value = {
        "action": "read_news",
        "result": "success",
        "score": 1.0,
        "signal": "positive",
        "submitted": False,
    }

    token_ledger = TokenLedger(store_path=str(tmp_path / "token_ledger.json"))

    if content_gate is None:
        content_gate = AsyncMock()
        content_gate.check.return_value = {"allowed": True, "reason": "ok"}

    rate_limiter = RateLimiter(limit_per_hour=5)
    killswitch = killswitch if killswitch is not None else KillSwitch(
        store_path=str(tmp_path / "killswitch.json")
    )
    audit = AuditStore(path=str(tmp_path / "audit.jsonl"))

    handlers = handlers if handlers is not None else {
        "autonomy_read_news": AsyncMock(return_value=[{"title": "新闻A", "link": "", "summary": ""}]),
    }

    circadian = circadian if circadian is not None else CircadianScheduler(dict(DEFAULT_SCHEDULE))

    engine = AutonomyEngine(
        manager=manager,
        motivation=motivation,
        circadian=circadian,
        sensor=sensor,
        rss=rss,
        hotspot=hotspot,
        memory_actions=memory_actions,
        planner=planner,
        diary=diary,
        evaluator=evaluator,
        token_ledger=token_ledger,
        content_gate=content_gate,
        rate_limiter=rate_limiter,
        killswitch=killswitch,
        audit=audit,
        handlers=handlers,
        persona={"system_prompt": "测试人设"},
        loop_interval_minutes=loop_interval_minutes,
    )
    return engine


def list_audit(engine):
    """读取引擎审计存储的全部条目。"""
    page = engine.audit.list(limit=None)
    return page.get("items", [])


# ================================================================ ① 单轮流水线走通
@pytest.mark.asyncio
async def test_single_round_pipeline(tmp_path):
    engine = build_engine(tmp_path)

    await engine._run_round()

    # 审计追加了一条（read_news success）
    items = list_audit(engine)
    assert len(items) == 1
    entry = items[0]
    assert entry["action"] == "read_news"
    assert entry["result"] == "success"
    assert entry["trigger_reason"] == "好奇心较高，摄入信息"
    assert entry["expected_outcome"] == "获取新鲜素材"
    assert isinstance(entry["motivations"], dict)
    assert set(entry["motivations"].keys()) == {
        "curiosity", "social_need", "creative_drive", "fatigue",
    }

    # manager 状态更新
    assert engine.manager.last_action == "read_news"
    assert engine.manager.last_cycle_at is not None

    # 五层各组件被调用
    assert engine.sensor.snapshot.called
    assert engine.rss.fetch.called
    assert engine.hotspot.get_hotspots.called
    assert engine.planner.plan.called
    assert engine.evaluator.evaluate.called

    # 规划器收到五键上下文
    context = engine.planner.plan.await_args.args[0]
    assert set(context.keys()) == {
        "motivations", "phase", "hotspots", "context_snapshot", "recent_memories",
    }


# ================================================================ ② 异常隔离
@pytest.mark.asyncio
async def test_planner_exception_isolated(tmp_path):
    engine = build_engine(tmp_path)

    # 第一次规划抛错：round 不冒泡，记录错误审计
    engine.planner.plan.side_effect = RuntimeError("planner boom")
    await engine._run_round()  # 不应抛异常

    items = list_audit(engine)
    assert len(items) == 1
    assert items[0]["result"] == "failed"
    assert "planner boom" in (items[0]["error"] or "")

    # 修复 planner 后下一轮继续
    engine.planner.plan.side_effect = None
    engine.planner.plan.return_value = {
        "action": "wait", "target": "", "payload": {},
        "reason": "恢复", "expected_outcome": "",
    }
    await engine._run_round()

    items = list_audit(engine)
    assert len(items) == 2
    assert items[1]["result"] == "skipped"
    assert engine.manager.last_cycle_at is not None


# ================================================================ ③ 紧急停止
@pytest.mark.asyncio
async def test_emergency_stop_halts_loop(tmp_path):
    killswitch = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
    engine = build_engine(tmp_path, killswitch=killswitch, loop_interval_minutes=0.001)

    await engine.start()
    killswitch.emergency_stop()
    await asyncio.sleep(0.05)
    await engine.stop()

    assert killswitch.is_active() is False
    # 未执行任何轮次
    assert list_audit(engine) == []


# ================================================================ ④ sleep/wait 内部原语
@pytest.mark.asyncio
async def test_sleep_wait_are_internal_primitives(tmp_path):
    read_news_handler = AsyncMock(return_value=[{"title": "x"}])
    engine = build_engine(tmp_path, handlers={"autonomy_read_news": read_news_handler})

    for action in ("sleep", "wait"):
        result = await engine._execute(
            {"action": action, "target": "", "payload": {}, "reason": "", "expected_outcome": ""}
        )
        assert result["result"] == "skipped"
        assert "error" not in result

    # 内部原语不调用任何 handler
    assert read_news_handler.called is False


# ================================================================ ⑤ 内容闸门拒绝 write_post
@pytest.mark.asyncio
async def test_write_post_blocked_by_content_gate(tmp_path):
    gate = AsyncMock()
    gate.check.return_value = {"allowed": False, "reason": "persona_mismatch"}
    write_post_handler = AsyncMock(return_value={"platform": "weibo", "status": "published"})
    engine = build_engine(tmp_path, content_gate=gate, handlers={"autonomy_write_post": write_post_handler})

    plan = {
        "action": "write_post",
        "target": "动态",
        "payload": {"draft": "草稿文本", "platform": "weibo"},
        "reason": "分享见闻",
        "expected_outcome": "引发互动",
    }
    result = await engine._execute(plan)

    assert result["result"] == "blocked"
    assert write_post_handler.called is False
    gate.check.assert_awaited_once_with("草稿文本")


# ================================================================ ⑥ 日记时刻触发
@pytest.mark.asyncio
async def test_diary_time_triggers_diary(tmp_path):
    circadian = CircadianScheduler(dict(DEFAULT_SCHEDULE))  # diary_time=02:00
    diary = AsyncMock()
    diary.generate_diary.return_value = {"diary": "今日日记", "memory_id": "mem-9"}
    engine = build_engine(tmp_path, circadian=circadian, diary=diary)

    now = datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc)  # 02:00 → is_diary_time True
    result = await engine._maybe_diary(now)

    assert result == {"diary": "今日日记", "memory_id": "mem-9"}
    diary.generate_diary.assert_awaited_once()

    # 审计记录 write_diary，diary_last_at 更新
    items = list_audit(engine)
    assert any(e["action"] == "write_diary" for e in items)
    assert engine.manager.diary_last_at is not None


@pytest.mark.asyncio
async def test_diary_not_triggered_outside_diary_time(tmp_path):
    circadian = CircadianScheduler(dict(DEFAULT_SCHEDULE))
    diary = AsyncMock()
    engine = build_engine(tmp_path, circadian=circadian, diary=diary)

    now = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)  # 10:00 → 非日记时刻
    result = await engine._maybe_diary(now)

    assert result is None
    diary.generate_diary.assert_not_called()
    assert list_audit(engine) == []


# ================================================================ ⑦ 重启续接
@pytest.mark.asyncio
async def test_restart_resume_restores_state(tmp_path):
    # 第一个引擎：跑一轮，动机 tick 并持久化、manager 状态持久化
    engine1 = build_engine(tmp_path)
    await engine1._run_round()

    saved_motivations = engine1._motivation_dict()
    saved_last_action = engine1.manager.last_action
    saved_last_cycle_at = engine1.manager.last_cycle_at
    assert saved_last_action == "read_news"

    # 第二个引擎：从同一 store_dir 构造，应恢复 motivation 与 manager 状态
    engine2 = build_engine(tmp_path)

    assert engine2._motivation_dict() == saved_motivations
    assert engine2.manager.last_action == saved_last_action
    assert engine2.manager.last_cycle_at == saved_last_cycle_at


# ================================================================ 附加：循环实际执行轮次
@pytest.mark.asyncio
async def test_loop_runs_rounds_when_active(tmp_path):
    killswitch = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
    engine = build_engine(tmp_path, killswitch=killswitch, loop_interval_minutes=0.001)

    await engine.start()
    await asyncio.sleep(0.15)  # interval 0.06s，等待至少一轮
    await engine.stop()

    assert engine.running is False
    assert len(list_audit(engine)) >= 1
    assert engine.manager.last_cycle_at is not None
