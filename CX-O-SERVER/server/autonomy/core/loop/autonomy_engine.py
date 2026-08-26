"""CX-O-Autonomy 自主主循环引擎（P1-T8）。

AutonomyEngine 串联 感知→动机→规划→行动→审计 五层流水线，以后台 asyncio 任务
周期运行：

- start() / stop()        启动/停止后台循环任务
- _run_loop()             后台主循环（while killswitch.enabled）
- _run_round()            单轮五层流水线（轮首含用户在线策略）
- _execute()              按 action 分发执行（sleep/wait 为内部原语不调 handler）
- _maybe_diary()          日记时刻触发日记生成（is_diary_time 且今日未写）

安全/质量职责：
- 行动前对 write_post 过内容闸门（fail-closed），拒绝则 result=blocked 不执行；
- 每轮追加审计（对齐 public/schema/autonomy_audit.schema.json），Token 记账，
  效果评估；
- 预算熔断闸门：每轮动机更新后、规划前检查 TokenLedger 超支（超支 → 置
  manager.status=budget_limited，跳过规划与行动，审计 result=skipped /
  trigger_reason=budget_exceeded）；未超支且此前 budget_limited（新的一天
  budget_reset_date 变化后）自动恢复 running；达到成本告警阈值时经
  ws_manager.broadcast 推送 autonomy_cost_alert（当日仅一次，缺失仅记日志）；
- round 内任何异常被捕获（不冒泡），记录错误审计后继续下一轮；
- 紧急停止（killswitch.emergency_stop）后循环立即退出，不执行新轮次；
- 用户在线休眠策略（P2-T4）：仅急停（enabled=False）终止循环；休眠/暂停降级
  为轮级跳过（见 _run_round），从而支持"用户在线→休眠、用户离开→离开模式
  自动恢复"的轮询语义。

生命周期：构造时从持久化恢复 motivation 与 manager 状态（重启续接）。
本模块无相对路径访问，禁止 "../../" / "..\\\\" 形式。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.autonomy.config import resolve_store_dir
from server.autonomy.perception.env.context_sensor import ContextSensor
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 默认热点主题（供感知层查询社交热点）
_DEFAULT_HOTSPOT_TOPICS: List[str] = ["AI", "科技", "游戏", "生活"]
# 默认热点条数上限
_DEFAULT_HOTSPOT_LIMIT: int = 5

# 动作枚举 → 工具名 映射（sleep/wait 为内部原语，不在此映射）
_ACTION_TO_TOOL: Dict[str, str] = {
    "read_news": "autonomy_read_news",
    "search": "autonomy_search",
    "write_memory": "autonomy_write_memory",
    "write_post": "autonomy_write_post",
    "start_live": "autonomy_start_live",
    "stop_live": "autonomy_stop_live",
    "write_diary": "autonomy_write_diary",
}

# manager 状态持久化字段（与 manager.py 属性一一对应）
_MANAGER_STATE_FIELDS: Tuple[str, ...] = (
    "enabled",
    "running",
    "status",
    "last_action",
    "last_cycle_at",
    "daily_budget_used_tokens",
    "budget_reset_date",
    "diary_last_at",
)


class AutonomyEngine:
    """CX-O-Autonomy 自主主循环引擎。

    构造入参按已实现模块真实 API 灵活适配（组件均以关键字注入，便于测试 mock）：
    manager / motivation / circadian / sensor / rss / hotspot / memory_actions /
    planner / diary / evaluator / token_ledger / content_gate / rate_limiter /
    killswitch / audit / handlers / persona，另含 loop_interval_minutes、
    max_diary_per_day 与可选 ws_manager（成本告警 WS 推送，缺失仅记日志）。

    构造时即执行持久化恢复（motivation 与 manager 状态），实现重启续接。
    """

    def __init__(
        self,
        *,
        manager: Any,
        motivation: Any,
        circadian: Any,
        sensor: Any,
        rss: Any,
        hotspot: Any,
        memory_actions: Any,
        planner: Any,
        diary: Any,
        evaluator: Any,
        token_ledger: Any,
        content_gate: Any,
        rate_limiter: Any,
        killswitch: Any,
        audit: Any,
        handlers: Dict[str, Callable],
        persona: Optional[Dict[str, Any]] = None,
        ws_manager: Optional[Any] = None,
        loop_interval_minutes: int = 15,
        max_diary_per_day: bool = True,
    ) -> None:
        """初始化引擎：保存全部组件引用，解析存储目录并执行重启续接。"""
        self.manager = manager
        self.motivation = motivation
        self.circadian = circadian
        self.sensor = sensor
        self.rss = rss
        self.hotspot = hotspot
        self.memory_actions = memory_actions
        self.planner = planner
        self.diary = diary
        self.evaluator = evaluator
        self.token_ledger = token_ledger
        self.content_gate = content_gate
        self.rate_limiter = rate_limiter
        self.killswitch = killswitch
        self.audit = audit
        self.handlers = handlers or {}
        self.persona = persona or {}
        self.ws_manager = ws_manager
        self.loop_interval_minutes = max(float(loop_interval_minutes), 0.0)
        self.max_diary_per_day = bool(max_diary_per_day)
        self.hotspot_topics: List[str] = list(_DEFAULT_HOTSPOT_TOPICS)
        self.hotspot_limit: int = _DEFAULT_HOTSPOT_LIMIT

        # 存储目录：优先 config.store_path，缺省基于 __file__ 绝对路径解析
        config = getattr(manager, "config", None)
        store = getattr(config, "store_path", "") or ""
        self._store_dir: str = str(store or resolve_store_dir())

        self.running: bool = False
        self._task: Optional[asyncio.Task] = None

        # 重启续接：构造时从持久化恢复 motivation 与 manager 状态
        self._load_persisted_state()

    # ================================================================ 生命周期
    async def start(self) -> asyncio.Task:
        """启动后台主循环任务；已启动则直接返回现有任务。

        仅创建 asyncio 后台任务，不阻塞等待；停止由 stop() 负责。
        """
        if self._task is not None and not self._task.done():
            return self._task
        self.running = True
        self._task = asyncio.create_task(
            self._run_loop(), name="cxo-autonomy-loop"
        )
        return self._task

    async def stop(self) -> None:
        """停止后台主循环任务并置 running=False。"""
        self.running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        """后台主循环：未急停期间周期执行单轮，并在每次醒来后检查日记时刻。

        P2-T4 起循环守卫由 killswitch.is_active() 放宽为 killswitch.enabled：
        - 仅紧急停止（enabled=False）才终止循环；
        - 暂停/休眠（paused/sleeping）不再终止循环，降级为轮级跳过（见
          _run_round），从而支持"用户在线→休眠、用户离开→离开模式自动恢复"
          的轮询语义。
        round 内任何异常被捕获（不冒泡），记录错误审计后 continue 下一轮；
        急停（killswitch.enabled 为 False）后循环立即退出，不执行新轮次。
        """
        interval_seconds: float = self.loop_interval_minutes * 60.0
        while self.killswitch.enabled:
            await asyncio.sleep(interval_seconds)
            # 醒来后再次确认未被急停，避免急停后执行多余轮次
            if not self.killswitch.enabled:
                break
            try:
                await self._run_round()
            except Exception as e:
                logger.error("自主主循环单轮异常（不冒泡）: %s", e)
                await self._record_error_audit(e)
            try:
                await self._maybe_diary()
            except Exception as e:
                logger.error("日记触发异常（不冒泡）: %s", e)
        self.running = False

    # ================================================================ 单轮流水线
    async def _run_round(self) -> None:
        """执行单轮流水线：感知→动机→规划→行动→审计（轮首含用户在线策略）。

        轮首用户在线策略（P2-T4 离开模式/用户在线休眠）：
        若 sensor 为真实 ContextSensor 且 config.safety.user_online_sleep 开启，
        先调用 sensor.is_user_online() 并写入 killswitch.update_from_user_online(...)：
        - 用户在线 → sleeping=True（休眠，避免"Agent 边聊边自发帖"的分裂感）；
        - 用户离开 → sleeping=False（离开模式，自主全授权，不拦截操作）。
        用户在线触发休眠时，本轮跳过规划与行动，仅更新动机并记录 result=skipped
        （trigger_reason=user_online_sleep）的审计条目（推荐方案：保留审计可回溯，
        且维持轮询语义，用户离开后下一轮自动恢复）。急停优先于一切：enabled=False
        时本轮同样跳过行动，且 leave_mode() 恒为 False。

        预算熔断闸门（P6）：动机更新后、规划前检查 TokenLedger——
        - 超支 → 置 manager.status=budget_limited，跳过规划与行动，审计
          result=skipped / trigger_reason=budget_exceeded（降级为记账不执行）；
        - 未超支 → 若此前 budget_limited（新的一天 budget_reset_date 变化后
          is_over_budget 自然 False）恢复 running；达到成本告警阈值经
          ws_manager.broadcast 推送 autonomy_cost_alert（当日仅一次）。

        round 内任何异常被捕获（不冒泡）：记录错误审计后本轮结束，由 _run_loop
        继续下一轮。最后更新 manager 的 last_action / last_cycle_at 并保存
        manager 状态与动机状态。
        """
        plan: Optional[Dict[str, Any]] = None
        action_result: Optional[Dict[str, Any]] = None
        try:
            online_sleep = self._apply_user_online_policy()
            await self._motivate()
            budget_blocked = await self._apply_budget_gate()
            if budget_blocked:
                # 预算超支：跳过规划与行动，仅审计 skipped（记账不执行）
                action_result = {
                    "action": "wait",
                    "target": "",
                    "payload": {},
                    "reason": "budget_exceeded",
                    "expected_outcome": "",
                    "result": "skipped",
                }
            elif self.killswitch.is_active():
                sense = await self._sense()
                plan = await self._plan(sense)
                action_result = await self._execute(plan)
            else:
                # 用户在线触发休眠 / 已暂停 / 已急停：跳过规划与行动，仅审计 skipped
                action_result = {
                    "action": "wait",
                    "target": "",
                    "payload": {},
                    "reason": "user_online_sleep" if online_sleep else "sleep_paused_or_stopped",
                    "expected_outcome": "",
                    "result": "skipped",
                }
            await self._audit(plan, action_result)
        except Exception as e:
            logger.error("自主循环单轮异常（不冒泡）: %s", e)
            await self._record_error_audit(e, plan)
        finally:
            if action_result is not None:
                self.manager.last_action = str(action_result.get("action", "") or "")
            elif plan is not None:
                self.manager.last_action = str(plan.get("action", "") or "")
            self.manager.last_cycle_at = self._now_iso()
            self._sync_manager_motivations()
            self._save_manager_state()

    def _apply_user_online_policy(self) -> bool:
        """轮首用户在线策略：将传感器判定同步到 killswitch 休眠档。

        仅在 sensor 为真实 ContextSensor（含可调用 is_user_online）且
        config.safety.user_online_sleep 开启时生效；否则不改动 killswitch
        （不干预手动 sleeping / 暂停 / 急停，测试 MagicMock 替身也不触发）。

        Returns:
            bool: 是否因"用户在线"在本轮触发休眠（True=本轮处于用户在线休眠，
            用于审计 trigger_reason 区分；False=未触发或策略未开启）。
        """
        if not isinstance(self.sensor, ContextSensor):
            return False
        try:
            safety = getattr(getattr(self.manager, "config", None), "safety", None)
            user_online_sleep = bool(getattr(safety, "user_online_sleep", False))
        except Exception:
            user_online_sleep = False
        if not user_online_sleep:
            return False
        try:
            is_online = bool(self.sensor.is_user_online())
        except Exception as e:
            logger.warning("用户在线判定失败: %s", e)
            is_online = False
        try:
            self.killswitch.update_from_user_online(is_online, user_online_sleep)
        except Exception as e:
            logger.warning("用户在线状态同步 killswitch 失败: %s", e)
        return bool(is_online)

    # ------------------------------------------------------------ 0) 预算熔断闸门
    async def _apply_budget_gate(self) -> bool:
        """轮首预算闸门：动机更新后、规划前执行预算熔断与成本告警。

        先按自然日同步预算日期（跨日自动重置 TokenLedger 当日计数），再判定：
        - 超支 → 置 manager.status="budget_limited" 并返回 True（本轮跳过规划
          与行动，降级为记账不执行，审计由 _run_round 记录 result=skipped /
          trigger_reason=budget_exceeded）；
        - 未超支 → 若此前处于 budget_limited（新的一天 budget_reset_date 变化后
          is_over_budget 自然为 False）恢复 running；达到成本告警阈值时经
          ws_manager.broadcast 推送 autonomy_cost_alert（当日仅一次，标记由
          TokenLedger 内部管理；ws_manager 缺失仅记日志）。

        Returns:
            bool: True=预算超支本轮跳过规划与行动；False=继续正常规划。
        """
        if self.token_ledger is None:
            return False
        try:
            self._sync_budget_date()
            if self.token_ledger.is_over_budget():
                self.manager.status = "budget_limited"
                logger.warning("自主系统当日预算超支，本轮降级为记账不执行")
                return True
        except Exception as e:
            logger.warning("预算超支判定失败: %s", e)
            return False
        # 未超支：此前因预算受限则恢复（新的一天重置后自然恢复）
        if getattr(self.manager, "status", "") == "budget_limited":
            self.manager.status = "running"
            logger.info("自主系统预算已恢复（新的一天），状态恢复 running")
        try:
            if self.token_ledger.is_alert_triggered():
                await self._push_cost_alert()
        except Exception as e:
            logger.warning("成本告警推送失败: %s", e)
        return False

    def _sync_budget_date(self) -> None:
        """按自然日同步预算日期：跨日时自动重置 TokenLedger 计数并更新 manager.budget_reset_date。

        新的一天（manager.budget_reset_date 与今日不一致）时调用
        token_ledger.reset_if_new_day() 清零当日计数，使 is_over_budget 自然
        恢复 False，并记录新的重置日期。
        """
        now = self._local_now()
        if not isinstance(now, datetime):
            now = datetime.now(timezone(timedelta(hours=8)))
        today = now.date().isoformat()
        if getattr(self.manager, "budget_reset_date", None) == today:
            return
        try:
            self.token_ledger.reset_if_new_day(today)
        except Exception as e:
            logger.warning("预算跨日重置失败: %s", e)
        self.manager.budget_reset_date = today

    async def _push_cost_alert(self) -> None:
        """经 ws_manager.broadcast 推送成本告警（type=autonomy_cost_alert）。

        data 含 usage_ratio / daily_used / limit / date；ws_manager 缺失或
        无 broadcast 方法时仅记日志，不阻断循环（ws_manager 缺失不抛错）。
        """
        now = self._local_now()
        if not isinstance(now, datetime):
            now = datetime.now(timezone(timedelta(hours=8)))
        data: Dict[str, Any] = {
            "usage_ratio": float(self.token_ledger.usage_ratio()),
            "daily_used": int(self.token_ledger.daily_used()),
            "limit": int(self.token_ledger.daily_token_limit),
            "date": now.date().isoformat(),
        }
        ws_manager = self.ws_manager
        if ws_manager is None:
            logger.warning(
                "自主系统成本告警触发但 ws_manager 缺失，仅记录日志（usage_ratio=%.2f）",
                data["usage_ratio"],
            )
            return
        broadcast = getattr(ws_manager, "broadcast", None)
        if not callable(broadcast):
            logger.warning("ws_manager 无 broadcast 方法，仅记录日志（usage_ratio=%.2f）", data["usage_ratio"])
            return
        await broadcast({"type": "autonomy_cost_alert", "data": data})

    # ------------------------------------------------------------ 1) 感知
    async def _sense(self) -> Dict[str, Any]:
        """感知层：环境快照 + RSS 新闻 + 社交热点 + 最近记忆。各子项独立容错。"""
        context_snapshot: Dict[str, Any] = {}
        if self.sensor is not None:
            try:
                raw = self.sensor.snapshot()
                snap = await self._maybe_await(raw)
                if isinstance(snap, dict):
                    context_snapshot = snap
            except Exception as e:
                logger.warning("环境感知失败: %s", e)

        news: List[Any] = []
        if self.rss is not None:
            try:
                raw = self.rss.fetch()
                items = await self._maybe_await(raw)
                if isinstance(items, list):
                    news = items
            except Exception as e:
                logger.warning("RSS 抓取失败: %s", e)

        hotspots: List[Any] = []
        if self.hotspot is not None:
            try:
                raw = self.hotspot.get_hotspots(
                    list(self.hotspot_topics), limit=self.hotspot_limit
                )
                items = await self._maybe_await(raw)
                if isinstance(items, list):
                    hotspots = items
            except Exception as e:
                logger.warning("热点感知失败: %s", e)

        recent_memories: List[Any] = []
        if self.memory_actions is not None:
            try:
                raw = self.memory_actions.retrieve_memory(query="", limit=5)
                items = await self._maybe_await(raw)
                if isinstance(items, list):
                    recent_memories = items
            except Exception as e:
                logger.warning("记忆检索失败: %s", e)

        return {
            "context_snapshot": context_snapshot,
            "news": news,
            "hotspots": hotspots,
            "recent_memories": recent_memories,
        }

    # ------------------------------------------------------------ 2) 动机
    async def _motivate(self) -> Dict[str, float]:
        """动机层：按流逝分钟 tick 四维动机并持久化。"""
        elapsed_minutes = self._elapsed_minutes()
        tick = getattr(self.motivation, "tick", None)
        if callable(tick):
            try:
                result = tick(elapsed_minutes)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.warning("动机 tick 失败: %s", e)
        save = getattr(self.motivation, "save", None)
        if callable(save):
            try:
                save(self._store_dir)
            except Exception as e:
                logger.warning("动机保存失败: %s", e)
        self._sync_manager_motivations()
        return self._motivation_dict()

    # ------------------------------------------------------------ 3) 规划
    async def _plan(self, sense: Dict[str, Any]) -> Dict[str, Any]:
        """规划层：组装上下文调用 ActionPlanner 输出行动决策。

        规划器异常不在此吞掉，交由 _run_round 捕获并记录错误审计。
        """
        context: Dict[str, Any] = {
            "motivations": self._motivation_dict(),
            "phase": self._current_phase(),
            "hotspots": sense.get("hotspots", []),
            "context_snapshot": sense.get("context_snapshot", {}),
            "recent_memories": sense.get("recent_memories", []),
        }
        result = self.planner.plan(context)
        plan = await self._maybe_await(result)
        return plan if isinstance(plan, dict) else {"action": "wait", "reason": "plan_invalid"}

    # ------------------------------------------------------------ 4) 行动
    async def _execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """行动层：按 action 分发执行。

        - sleep / wait 为内部原语：记录 result=skipped，不执行任何 handler；
        - write_post 执行前过内容闸门（fail-closed）：拒绝则 result=blocked 且
          不调用 handler（审计中止）；
        - handler 缺失/抛异常：result=failed + error 记录，不冒泡。
        """
        action_name = str(action.get("action", "wait") or "wait")
        base: Dict[str, Any] = {
            "action": action_name,
            "target": str(action.get("target", "") or ""),
            "payload": action.get("payload") if isinstance(action.get("payload"), dict) else {},
            "reason": str(action.get("reason", "") or ""),
            "expected_outcome": str(action.get("expected_outcome", "") or ""),
        }

        # 内部原语：sleep / wait 不执行 handler
        if action_name in ("sleep", "wait"):
            return {**base, "result": "skipped"}

        tool_name = _ACTION_TO_TOOL.get(action_name)
        if tool_name is None:
            return {**base, "result": "failed", "error": f"未映射动作 {action_name!r}"}

        handler = self.handlers.get(tool_name)
        if handler is None:
            return {**base, "result": "failed", "error": f"handler 缺失: {tool_name}"}

        # 内容闸门：仅对 write_post 的 draft 做检查
        if action_name == "write_post" and self.content_gate is not None:
            draft = str((action.get("payload") or {}).get("draft", "") or "")
            try:
                gate = await self.content_gate.check(draft)
            except Exception as e:
                gate = {"allowed": False, "reason": f"content_gate_error: {e}"}
            if not bool(gate.get("allowed", False)):
                reason = str(gate.get("reason", "content_rejected") or "content_rejected")
                return {**base, "result": "blocked", "error": reason}

        try:
            args, kwargs = self._build_handler_args(action, tool_name)
            out = handler(*args, **kwargs)
            out = await self._maybe_await(out)
        except Exception as e:
            logger.warning("工具 %s 执行失败: %s", tool_name, e)
            return {**base, "result": "failed", "error": str(e)}

        cost_tokens = 0
        if isinstance(out, dict):
            try:
                cost_tokens = int(out.get("cost_tokens", 0) or 0)
            except (TypeError, ValueError):
                cost_tokens = 0
        return {
            **base,
            "result": "success",
            "output": out,
            "cost_tokens": max(cost_tokens, 0),
        }

    def _build_handler_args(
        self, action: Dict[str, Any], tool_name: str
    ) -> Tuple[tuple, Dict[str, Any]]:
        """按工具名从 action payload 组装 handler 位置参数与关键字参数。"""
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        if tool_name == "autonomy_read_news":
            return (), {"limit": int(payload.get("limit", 5) or 5)}
        if tool_name == "autonomy_search":
            return (), {
                "query": str(payload.get("query", "") or ""),
                "limit": int(payload.get("limit", 5) or 5),
            }
        if tool_name == "autonomy_write_memory":
            kwargs: Dict[str, Any] = {
                "content": str(payload.get("content", "") or ""),
                "type": str(payload.get("type", "long_term") or "long_term"),
                "permanent": bool(payload.get("permanent", False)),
                "importance": int(payload.get("importance", 3) or 3),
            }
            if payload.get("tags") is not None:
                kwargs["tags"] = payload["tags"]
            if payload.get("metadata") is not None:
                kwargs["metadata"] = payload["metadata"]
            return (), kwargs
        if tool_name == "autonomy_write_post":
            return (), {
                "platform": str(payload.get("platform", "") or ""),
                "draft": str(payload.get("draft", "") or ""),
            }
        if tool_name == "autonomy_start_live":
            return (), {"script": str(payload.get("script", "") or "")}
        return (), {}

    # ------------------------------------------------------------ 5) 审计
    async def _audit(
        self, plan: Optional[Dict[str, Any]], action_result: Dict[str, Any]
    ) -> None:
        """审计层：追加审计条目（对齐 autonomy_audit.schema.json）、Token 记账并效果评估。

        plan 可能为 None（用户在线休眠跳过路径等）：None 时按空字典处理，
        trigger_reason 回退到 action_result.reason，保证跳过原因可回溯。
        """
        plan = plan if isinstance(plan, dict) else {}
        entry: Dict[str, Any] = {
            "timestamp": self._now_iso(),
            "motivations": self._motivation_dict(),
            "action": str(action_result.get("action", "") or plan.get("action", "") or "wait"),
            "target": str(action_result.get("target", "") or plan.get("target", "") or ""),
            "payload": action_result.get("payload")
            if isinstance(action_result.get("payload"), dict)
            else {},
            "result": str(action_result.get("result", "skipped") or "skipped"),
            "error": action_result.get("error"),
            "cost_tokens": int(action_result.get("cost_tokens", 0) or 0),
            "trigger_reason": str(plan.get("reason", "") or action_result.get("reason", "") or ""),
            "expected_outcome": str(plan.get("expected_outcome", "") or ""),
        }
        try:
            self.audit.append(entry)
        except Exception as e:
            logger.error("审计写入失败: %s", e)
            return
        cost_tokens = int(action_result.get("cost_tokens", 0) or 0)
        if cost_tokens > 0 and self.token_ledger is not None:
            try:
                self.token_ledger.add_tokens(cost_tokens)
            except Exception as e:
                logger.warning("Token 记账失败: %s", e)
        if self.evaluator is not None:
            try:
                await self._maybe_await(self.evaluator.evaluate(action_result))
            except Exception as e:
                logger.warning("效果评估失败: %s", e)

    async def _record_error_audit(
        self, error: Exception, plan: Optional[Dict[str, Any]] = None
    ) -> None:
        """记录一轮异常的错误审计条目（尽力而为，不冒泡）。"""
        try:
            self.audit.append(
                {
                    "timestamp": self._now_iso(),
                    "motivations": self._motivation_dict(),
                    "action": str((plan or {}).get("action", "") or "wait"),
                    "target": str((plan or {}).get("target", "") or ""),
                    "payload": (plan or {}).get("payload")
                    if isinstance((plan or {}).get("payload"), dict)
                    else {},
                    "result": "failed",
                    "error": str(error),
                    "cost_tokens": 0,
                    "trigger_reason": str((plan or {}).get("reason", "") or ""),
                    "expected_outcome": str((plan or {}).get("expected_outcome", "") or ""),
                }
            )
        except Exception as e:
            logger.error("错误审计写入失败: %s", e)

    # ================================================================ 日记触发
    async def _maybe_diary(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """日记时刻触发：当日到期且今日未写日记时生成日记并记录审计。

        日记生成失败不冒泡（返回错误结构并记录审计）。
        """
        if now is None:
            now = self._local_now()
        if not isinstance(now, datetime):
            return None
        try:
            # H6: 旧 is_diary_time 为分钟级等值判断，主循环粗轮询（默认 15 分钟
            # 唤醒一次）几乎必然错过目标分钟 → 默认配置下日记可能永远不触发。
            # 改为追赶式判定：某次唤醒只要已过今日 diary_time 且今日未写即到期。
            due = self._is_diary_due(now)
        except Exception as e:
            logger.warning("日记时刻判定失败: %s", e)
            return None
        if not due:
            return None
        # 已写日记则本轮不触发（追赶式判定下无条件拦截，保证每日至多一次）
        if self._diary_written_today(now):
            return None
        daily_log = self._daily_log(now)
        if self.diary is None:
            return None
        try:
            result = await self.diary.generate_diary(
                daily_log, date=now.date().isoformat()
            )
        except Exception as e:
            logger.warning("日记生成失败: %s", e)
            result = {"diary": "", "memory_id": None, "error": str(e)}
        self.manager.diary_last_at = now.isoformat()
        self._save_manager_state()
        try:
            self.audit.append(
                {
                    "timestamp": self._now_iso(),
                    "motivations": self._motivation_dict(),
                    "action": "write_diary",
                    "target": "",
                    "payload": {},
                    "result": "success" if (result or {}).get("memory_id") else "failed",
                    "error": (result or {}).get("error"),
                    "cost_tokens": 0,
                    "trigger_reason": "diary_time",
                    "expected_outcome": "每日日记沉淀",
                }
            )
        except Exception as e:
            logger.warning("日记审计写入失败: %s", e)
        return result

    def _is_diary_due(self, now: datetime) -> bool:
        """日记到期判定：now 落在今日 diary_time 起的容差窗口内。

        修复主循环粗轮询（默认 15 分钟唤醒一次）对分钟级等值匹配（旧
        is_diary_time：hour==H and minute==M）几乎必然错过、导致日记永远
        不触发的问题：容差窗口取 max(30, 2 × 轮询间隔) 分钟，保证至少一次
        唤醒落入窗口。窗口有界——超出窗口即视为错过当日时刻，不会无限顺延。
        """
        tolerance_min = max(30.0, 2.0 * self.loop_interval_minutes)
        today_diary = datetime.combine(now.date(), self.circadian.diary_time, tzinfo=now.tzinfo)
        return today_diary <= now < today_diary + timedelta(minutes=tolerance_min)

    def _diary_written_today(self, now: datetime) -> bool:
        """今日是否已写日记（依据 manager.diary_last_at 的日期判定）。"""
        if not self.manager.diary_last_at:
            return False
        try:
            last = datetime.fromisoformat(str(self.manager.diary_last_at))
            return last.date() == now.date()
        except (ValueError, TypeError):
            return False

    def _daily_log(self, now: datetime) -> List[Dict[str, Any]]:
        """从审计存储取当日条目（供日记生成器使用），健壮处理各形态 list 结果。"""
        try:
            page = self.audit.list(limit=None)
        except Exception:
            return []
        if isinstance(page, dict):
            items = page.get("items", [])
        else:
            items = getattr(page, "items", None) or []
        if not isinstance(items, list):
            return []
        day = now.date().isoformat()
        result: List[Dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            ts = str(entry.get("timestamp", "") or "")
            if ts.startswith(day):
                result.append(entry)
        return result

    # ================================================================ 持久化
    def _load_persisted_state(self) -> None:
        """构造时从持久化恢复 motivation 与 manager 状态（重启续接）。"""
        motivation_path = Path(self._store_dir) / "motivation_state.json"
        if motivation_path.exists():
            try:
                from server.autonomy.core.motivation.state import MotivationState

                self.motivation = MotivationState.load(self._store_dir)
            except Exception as e:
                logger.warning("恢复动机状态失败: %s", e)
        self._load_manager_state()

    def _load_manager_state(self) -> None:
        """从 manager_state.json 恢复 manager 字段与 motivations（尽力而为）。"""
        try:
            path = Path(self._store_dir) / "manager_state.json"
            if not path.exists():
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            for field in _MANAGER_STATE_FIELDS:
                if field in data:
                    setattr(self.manager, field, data[field])
            if isinstance(data.get("motivations"), dict):
                try:
                    from server.autonomy.models import Motivations

                    self.manager.motivations = Motivations(**data["motivations"])
                except Exception:
                    pass
        except Exception as e:
            logger.warning("恢复 manager 状态失败: %s", e)

    def _save_manager_state(self) -> None:
        """将 manager 状态持久化为 manager_state.json（尽力而为）。"""
        try:
            motivations = self.manager.motivations
            if hasattr(motivations, "model_dump"):
                motivations_dict = motivations.model_dump()
            elif isinstance(motivations, dict):
                motivations_dict = dict(motivations)
            else:
                motivations_dict = {}
            data: Dict[str, Any] = {
                "enabled": bool(getattr(self.manager, "enabled", False)),
                "running": bool(getattr(self.manager, "running", False)),
                "status": str(getattr(self.manager, "status", "paused")),
                "motivations": motivations_dict,
                "last_action": getattr(self.manager, "last_action", None),
                "last_cycle_at": getattr(self.manager, "last_cycle_at", None),
                "daily_budget_used_tokens": int(
                    getattr(self.manager, "daily_budget_used_tokens", 0) or 0
                ),
                "budget_reset_date": getattr(self.manager, "budget_reset_date", None),
                "diary_last_at": getattr(self.manager, "diary_last_at", None),
            }
            path = Path(self._store_dir) / "manager_state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存 manager 状态失败: %s", e)

    # ================================================================ 工具方法
    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """若 value 是 awaitable 则等待后返回，否则原样返回（兼容 sync/async）。"""
        if inspect.isawaitable(value):
            return await value
        return value

    def _now_iso(self) -> str:
        """当前 UTC ISO 时间戳（对齐 models._now_iso 格式）。"""
        return datetime.now(timezone.utc).isoformat()

    def _local_now(self) -> Any:
        """本地当前时间：优先感知器 now()，缺省 UTC+8。"""
        now_fn = getattr(self.sensor, "now", None)
        if callable(now_fn):
            try:
                return now_fn()
            except Exception:
                pass
        return datetime.now(timezone(timedelta(hours=8)))

    def _current_phase(self) -> str:
        """返回当前昼夜相位（sleep/golden/quiet/active），失败兜底 active。"""
        try:
            now = self._local_now()
            if isinstance(now, datetime):
                phase = self.circadian.current_phase(now)
                if isinstance(phase, str):
                    return phase
        except Exception as e:
            logger.warning("相位判定失败: %s", e)
        return "active"

    def _elapsed_minutes(self) -> float:
        """计算距上次循环的流逝分钟；无 last_cycle_at（首轮）用 loop_interval_minutes。"""
        if self.manager.last_cycle_at:
            try:
                last = datetime.fromisoformat(str(self.manager.last_cycle_at))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                delta = (now - last).total_seconds() / 60.0
                return max(delta, 0.0)
            except (ValueError, TypeError):
                pass
        return float(self.loop_interval_minutes)

    def _motivation_dict(self) -> Dict[str, float]:
        """取四维动机字典；兼容 motivation.to_dict() / dict / mock 缺省空字典。"""
        to_dict = getattr(self.motivation, "to_dict", None)
        if callable(to_dict):
            try:
                raw = to_dict()
                if isinstance(raw, dict):
                    return dict(raw)
            except Exception:
                pass
        if isinstance(self.motivation, dict):
            return dict(self.motivation)
        return {}

    def _sync_manager_motivations(self) -> None:
        """把动机状态同步到 manager.motivations（尽力而为，字段完整才写）。"""
        motivations = self._motivation_dict()
        if {"curiosity", "social_need", "creative_drive", "fatigue"}.issubset(motivations):
            try:
                from server.autonomy.models import Motivations

                self.manager.motivations = Motivations(**motivations)
            except Exception:
                pass
