"""CX-O-Autonomy P2-T4 离开模式/用户在线休眠策略单元测试。

覆盖（2026-09-27 人类裁决：用户在线休眠落点由急停档改为引擎内标志
`engine._user_online_sleeping`，行为保留）：
① 引擎在用户在线时跳过规划与行动（mock planner 不被调用）、离线时正常规划，且
   在线/离线切换后下一轮自动恢复；
② user_online_sleep=False 时即使在线也不休眠、正常规划。

运行：python -m pytest tests/test_autonomy_leave_mode.py -q
"""
from unittest.mock import AsyncMock

import pytest

from server.autonomy.config import AutonomyConfig
from server.autonomy.core.loop.autonomy_engine import AutonomyEngine
from server.autonomy.core.motivation.state import MotivationState
from server.autonomy.core.scheduler.circadian import CircadianScheduler
from server.autonomy.manager import AutonomyManager
from server.autonomy.perception.env.context_sensor import ContextSensor
from server.autonomy.safety.audit import AuditStore
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
    online=False,
    user_online_sleep=True,
):
    """构造外部组件全部 mock 的 AutonomyEngine，sensor 为真实 ContextSensor。

    online 经可变 dict 引用注入（state["online"]），便于轮次间切换用户在线状态；
    user_online_sleep 控制 config.safety.user_online_sleep（默认 True）。
    返回 (engine, state)。
    """
    state = {"online": bool(online)}
    cfg = AutonomyConfig(store_path=str(tmp_path))
    cfg.safety.user_online_sleep = bool(user_online_sleep)
    manager = AutonomyManager(cfg)
    manager.enable()

    motivation = MotivationState(
        curiosity=0.5, social_need=0.4, creative_drive=0.3, fatigue=0.1
    )
    sensor = ContextSensor(user_online_provider=lambda: state["online"])

    rss = AsyncMock()
    rss.fetch.return_value = [{"title": "新闻A", "link": "http://x/1", "summary": "摘要A"}]
    hotspot = AsyncMock()
    hotspot.get_hotspots.return_value = [
        {"title": "热点A", "link": "http://y/1", "snippet": "热点摘要"}
    ]
    memory_actions = AsyncMock()
    memory_actions.retrieve_memory.return_value = []

    planner = AsyncMock()
    planner.plan.return_value = dict(READ_NEWS_PLAN)

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

    content_gate = AsyncMock()
    content_gate.check.return_value = {"allowed": True, "reason": "ok"}
    rate_limiter = RateLimiter(limit_per_hour=5)

    audit = AuditStore(path=str(tmp_path / "audit.jsonl"))

    handlers = {
        "autonomy_read_news": AsyncMock(
            return_value=[{"title": "新闻A", "link": "", "summary": ""}]
        ),
    }
    circadian = CircadianScheduler(dict(DEFAULT_SCHEDULE))

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
        content_gate=content_gate,
        rate_limiter=rate_limiter,
        audit=audit,
        handlers=handlers,
        persona={"system_prompt": "测试人设"},
        loop_interval_minutes=15,
    )
    return engine, state


def list_audit(engine):
    """读取引擎审计存储的全部条目。"""
    page = engine.audit.list(limit=None)
    return page.get("items", [])


# ================================================================ ① 引擎用户在线跳过规划 / 离线正常规划
@pytest.mark.asyncio
async def test_engine_skips_planning_when_user_online(tmp_path):
    engine, state = build_engine(tmp_path, online=True)

    await engine._run_round()

    # 用户在线 → 引擎内休眠标志置位 → 跳过规划与行动
    assert engine._user_online_sleeping is True
    engine.planner.plan.assert_not_called()

    # 审计记录一条 skipped（trigger_reason=user_online_sleep）
    items = list_audit(engine)
    assert len(items) == 1
    assert items[0]["result"] == "skipped"
    assert items[0]["trigger_reason"] == "user_online_sleep"
    assert engine.manager.last_cycle_at is not None


@pytest.mark.asyncio
async def test_engine_plans_normally_when_user_offline(tmp_path):
    engine, state = build_engine(tmp_path, online=False)

    await engine._run_round()

    # 用户离开 → 离开模式 → 正常规划与行动
    assert engine._user_online_sleeping is False
    engine.planner.plan.assert_awaited_once()

    items = list_audit(engine)
    assert items[0]["result"] == "success"
    assert engine.manager.last_action == "read_news"


@pytest.mark.asyncio
async def test_engine_transition_online_to_offline_resumes(tmp_path):
    engine, state = build_engine(tmp_path, online=True)

    # 在线轮：跳过规划
    await engine._run_round()
    assert engine.planner.plan.call_count == 0
    assert engine._user_online_sleeping is True

    # 用户离开后下一轮自动恢复自主
    state["online"] = False
    await engine._run_round()
    engine.planner.plan.assert_awaited_once()
    assert engine._user_online_sleeping is False

    items = list_audit(engine)
    assert len(items) == 2
    assert items[0]["result"] == "skipped"
    assert items[1]["result"] == "success"


@pytest.mark.asyncio
async def test_engine_policy_disabled_plans_regardless(tmp_path):
    # user_online_sleep=False：即使在线也不休眠、正常规划
    engine, state = build_engine(tmp_path, online=True, user_online_sleep=False)

    await engine._run_round()

    assert engine._user_online_sleeping is False
    engine.planner.plan.assert_awaited_once()
    items = list_audit(engine)
    assert items[0]["result"] == "success"
