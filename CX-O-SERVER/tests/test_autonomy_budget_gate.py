"""CX-O-Autonomy P6 收尾：预算熔断闸门接线单元测试（全部 mock 外部组件）。

覆盖：
① 超支时 planner 不被调用、审计 result=skipped / trigger_reason=budget_exceeded /
   cost_tokens=0、manager.status=budget_limited；
② 未超支正常规划（planner 被调用、审计 success、status=running）；
③ 新日恢复（budget_reset_date 变更 / ledger 跨日重置后 status 回 running）；
④ is_alert_triggered 时 ws_manager.broadcast 被调且含 autonomy_cost_alert、
   同日内只告警一次；
⑤ ws_manager 缺失不抛错（告警路径仅记日志）。

运行：python -m pytest tests/test_autonomy_budget_gate.py -q
"""
import datetime
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
    token_ledger=None,
    ws_manager=None,
    plan=None,
):
    """构造外部组件全部 mock 的 AutonomyEngine（可注入自定义 TokenLedger / ws_manager）。"""
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

    if token_ledger is None:
        token_ledger = TokenLedger(store_path=str(tmp_path / "token_ledger.json"))

    content_gate = AsyncMock()
    content_gate.check.return_value = {"allowed": True, "reason": "ok"}
    rate_limiter = RateLimiter(limit_per_hour=5)
    killswitch = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
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
        token_ledger=token_ledger,
        content_gate=content_gate,
        rate_limiter=rate_limiter,
        killswitch=killswitch,
        audit=audit,
        handlers=handlers,
        persona={"system_prompt": "测试人设"},
        ws_manager=ws_manager,
        loop_interval_minutes=15,
    )
    return engine


def list_audit(engine):
    """读取引擎审计存储的全部条目。"""
    page = engine.audit.list(limit=None)
    return page.get("items", [])


# ================================================================ ① 超支熔断
@pytest.mark.asyncio
async def test_over_budget_blocks_planning(tmp_path):
    ledger = TokenLedger(daily_token_limit=100, store_path=str(tmp_path / "ledger.json"))
    ledger.add_tokens(150)  # 超支
    engine = build_engine(tmp_path, token_ledger=ledger)

    await engine._run_round()

    # 超支：跳过规划与行动（降级为记账不执行）
    engine.planner.plan.assert_not_called()
    assert engine.manager.status == "budget_limited"
    # 审计：result=skipped / trigger_reason=budget_exceeded / cost_tokens=0
    items = list_audit(engine)
    assert len(items) == 1
    assert items[0]["result"] == "skipped"
    assert items[0]["trigger_reason"] == "budget_exceeded"
    assert items[0]["cost_tokens"] == 0
    assert engine.manager.last_cycle_at is not None


# ================================================================ ② 未超支正常规划
@pytest.mark.asyncio
async def test_normal_planning_when_under_budget(tmp_path):
    engine = build_engine(tmp_path)  # 默认 ledger 2000000，未超支

    await engine._run_round()

    engine.planner.plan.assert_awaited_once()
    assert engine.manager.status == "running"
    items = list_audit(engine)
    assert items[0]["result"] == "success"
    assert engine.manager.last_action == "read_news"


# ================================================================ ③ 新日恢复
@pytest.mark.asyncio
async def test_new_day_recovers_status(tmp_path):
    ledger = TokenLedger(daily_token_limit=100, store_path=str(tmp_path / "ledger.json"))
    ledger.add_tokens(150)
    engine = build_engine(tmp_path, token_ledger=ledger)

    # 第一轮：超支 → budget_limited
    await engine._run_round()
    assert engine.manager.status == "budget_limited"
    assert engine.planner.plan.call_count == 0

    # 模拟新的一天：budget_reset_date 变化 + ledger 跨日重置
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    engine.manager.budget_reset_date = tomorrow
    ledger.reset_if_new_day(tomorrow)

    # 第二轮：is_over_budget 自然 False → status 恢复 running
    await engine._run_round()
    assert engine.manager.status == "running"
    engine.planner.plan.assert_awaited_once()
    items = list_audit(engine)
    assert items[1]["result"] == "success"


# ================================================================ ④ 成本告警当日一次
@pytest.mark.asyncio
async def test_cost_alert_pushed_once_per_day(tmp_path):
    ledger = TokenLedger(
        daily_token_limit=100,
        cost_alert_threshold=0.5,
        store_path=str(tmp_path / "ledger.json"),
    )
    ledger.add_tokens(60)  # ratio 0.6 >= 0.5，未超支
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    engine = build_engine(tmp_path, token_ledger=ledger, ws_manager=ws_manager)

    await engine._run_round()
    await engine._run_round()

    # 广播恰好一次（当日只告警一次，标记由 TokenLedger 内部管理）
    ws_manager.broadcast.assert_awaited_once()
    msg = ws_manager.broadcast.await_args.args[0]
    assert msg["type"] == "autonomy_cost_alert"
    data = msg["data"]
    assert data["usage_ratio"] == pytest.approx(0.6)
    assert data["daily_used"] == 60
    assert data["limit"] == 100
    assert data["date"]


# ================================================================ ⑤ ws_manager 缺失不抛错
@pytest.mark.asyncio
async def test_ws_manager_missing_does_not_raise(tmp_path):
    # 达到告警阈值但 ws_manager=None：告警路径仅记日志，不抛错
    ledger = TokenLedger(
        daily_token_limit=100,
        cost_alert_threshold=0.5,
        store_path=str(tmp_path / "ledger.json"),
    )
    ledger.add_tokens(60)
    engine = build_engine(tmp_path, token_ledger=ledger, ws_manager=None)

    await engine._run_round()  # 不应抛异常

    assert engine.manager.status == "running"
    engine.planner.plan.assert_awaited_once()
    items = list_audit(engine)
    assert items[0]["result"] == "success"
