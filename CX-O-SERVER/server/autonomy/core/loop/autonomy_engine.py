"""CX-O-Autonomy 自主主循环引擎（P1-T8）。

AutonomyEngine 串联 感知→动机→规划→行动→审计 五层流水线，以后台 asyncio 任务
周期运行：

- start() / stop()        启动/停止后台循环任务
- _run_loop()             后台主循环（while self.running：标志位守卫 + 任务取消双路径终止）
- _run_round()            单轮五层流水线（轮首含用户在线策略）
- _execute()              按 action 分发执行（sleep/wait 为内部原语不调 handler）
- _maybe_diary()          日记时刻触发日记生成（is_diary_time 且今日未写）

动机真实性（2026-09-30 修复）：
- _apply_motivation_feedback() 在行动成功后按 action 写回动机反馈（read_news/search →
  curiosity 回落（取回内容时创意欲上升）、write_post → social_need 回落、
  write_memory/write_diary → creative_drive 回落（创作消费，与素材获取配对）、
  start_live/stop_live → fatigue 上升）。只认 handler 的 result == "success"，
  不采信 LLM 自述；修复此前 4 个 record_* 入口在生产代码零调用、动机退化为
  纯时间函数并饱和（curiosity/social_need→1.0，creative_drive/fatigue→0）的缺陷。
- _apply_plan_focus() 回写 LLM 本轮自报的 focus（curiosity 的指向性维度），
  与动机状态一并落盘 motivation_state.json；_plan() 将当前焦点注入下一轮上下文。

安全/质量职责：
- 行动前对 write_post 过内容闸门（fail-closed），拒绝则 result=blocked 不执行；
- 每轮追加审计（对齐 public/schema/autonomy_audit.schema.json）并做效果评估；
- round 内任何异常被捕获（不冒泡），记录错误审计后继续下一轮；
- 主循环以 `while self.running` 守卫周期运行：不存在任何会终止循环的急停路径；
  唯一轮级跳过来源是"用户在线休眠"（见 _apply_user_online_policy），
  从而支持"用户在线→休眠、用户离开→离开模式自动恢复"的轮询语义；
  终止由 stop() 承担（置 running=False 的守卫自退 + task.cancel() 取消）。
- 轮内**不含**预算记账、manager 门控与 killswitch 三道路径（2026-09-27 人类裁决：
  纯本地项目不需要这些管控设施）。启停语义上移到任务层——由
  POST /api/autonomy/control 真正 start/stop 后台循环任务，而非轮级空转。

生命周期：构造时从持久化恢复 motivation 与 manager 状态（重启续接）；载入遗留
manager_state.json 时把 status 归一化为 running/paused/sleeping（历史预算受限态 /
错误态不回放，避免升级后契约越界），并忽略已删除的预算字段。
本模块无相对路径访问，禁止 "../../" / "..\\\\" 形式。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.autonomy._atomic_io import atomic_write_json
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
    "diary_last_at",
)

# manager.status 白名单（对齐 public/schema/autonomy_state.schema.json 精简枚举）；
# 载入遗留 manager_state.json 时，非白名单值（历史预算受限态 / 错误态）归一化为 running
_VALID_MANAGER_STATUSES: Tuple[str, ...] = ("running", "paused", "sleeping")


class AutonomyEngine:
    """CX-O-Autonomy 自主主循环引擎。

    构造入参按已实现模块真实 API 灵活适配（组件均以关键字注入，便于测试 mock）：
    manager / motivation / circadian / sensor / rss / hotspot / memory_actions /
    planner / diary / evaluator / content_gate / rate_limiter / audit / handlers /
    persona，另含 loop_interval_minutes 与 max_diary_per_day。

    2026-09-27 人类裁决后已移除 token_ledger / killswitch / ws_manager 三个入参
    （预算记账、killswitch 与成本告警已整体删除，ws_manager 仅曾服务于成本告警推送）。

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
        content_gate: Any,
        rate_limiter: Any,
        audit: Any,
        handlers: Dict[str, Callable],
        persona: Optional[Dict[str, Any]] = None,
        loop_interval_minutes: int = 15,
        max_diary_per_day: bool = True,
    ) -> None:
        """初始化引擎：保存全部组件引用，解析存储目录并执行重启续接。

        loop_interval_minutes 会经 max(..., 1.0) 归一化：配置 0 或负值会被提升为
        1 分钟（即 interval_seconds >= 60），避免主循环以近乎 0 的间隔空转形成
        高频忙循环副作用。
        """
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
        self.content_gate = content_gate
        self.rate_limiter = rate_limiter
        self.audit = audit
        self.handlers = handlers or {}
        self.persona = persona or {}
        # 用户在线休眠标志（原 killswitch.sleeping 的落点，2026-09-27 人类裁决：
        # 行为保留、改由引擎内标志承载）。该状态由传感器每轮实时判定，
        # 不参与持久化（跨重启保持无意义）。
        self._user_online_sleeping: bool = False
        self.loop_interval_minutes = max(float(loop_interval_minutes), 1.0)  # 0 被提升为 1 分钟，避免空转忙循环
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
        """后台主循环：未停止期间周期执行单轮，并在每次醒来后检查日记时刻。

        主循环无条件运行（while self.running）：不存在任何会终止循环的急停路径，
        终止有两条冗余路径——① stop() 先置 running=False，循环守卫在轮首自检后
        自行退出；② stop() 的 task.cancel() 经 await 点（asyncio.sleep）抛出
        CancelledError 直接解开循环。两条路径互为兜底（守卫不依赖任何外部开关，
        与"移除急停语义"一致），避免终止单点依赖取消。
        唯一的轮级跳过来源是"用户在线休眠"（见 _run_round），从而支持
        "用户在线→休眠、用户离开→离开模式自动恢复"的轮询语义。
        round 内任何异常被捕获（不冒泡），记录错误审计后 continue 下一轮；
        running=False 由 stop() 负责（守卫在下一轮首生效）。
        """
        interval_seconds: float = self.loop_interval_minutes * 60.0
        while self.running:
            await asyncio.sleep(interval_seconds)
            try:
                await self._run_round()
            except Exception as e:
                logger.error("自主主循环单轮异常（不冒泡）: %s", e)
                await self._record_error_audit(e)
            try:
                await self._maybe_diary()
            except Exception as e:
                logger.error("日记触发异常（不冒泡）: %s", e)

    # ================================================================ 单轮流水线
    async def _run_round(self) -> None:
        """执行单轮流水线：感知→动机→规划→行动→审计（轮首含用户在线策略）。

        轮首用户在线策略（P2-T4 离开模式/用户在线休眠）：
        若 sensor 为真实 ContextSensor 且 config.safety.user_online_sleep 开启，
        先调用 sensor.is_user_online() 并写入引擎内标志 self._user_online_sleeping：
        - 用户在线 → 休眠（避免"Agent 边聊边自发帖"的分裂感）；
        - 用户离开 → 离开模式，自主全授权，不拦截操作。
        用户在线触发休眠时，本轮跳过规划与行动，仅更新动机并记录 result=skipped
        （trigger_reason=user_online_sleep）的审计条目（保留审计可回溯，
        且维持轮询语义，用户离开后下一轮自动恢复）。

        本方法**不含**预算记账、manager 门控与 killswitch 三道路径
        （2026-09-27 人类裁决：纯本地项目不需要这些管控设施）。启停语义上移到
        任务层——POST /api/autonomy/control 真正 start/stop 后台循环任务，
        因此轮内不存在 paused/disabled 的轮级跳过分支。

        门控顺序：用户在线策略 → 动机 → 感知/规划/执行。

        round 内任何异常被捕获（不冒泡）：记录错误审计后本轮结束，由 _run_loop
        继续下一轮。最后更新 manager 的 last_action / last_cycle_at 并保存
        manager 状态与动机状态。
        """
        plan: Optional[Dict[str, Any]] = None
        action_result: Optional[Dict[str, Any]] = None
        try:
            online_sleep = await self._apply_user_online_policy()
            await self._motivate()
            if online_sleep:
                # 用户在线触发休眠：跳过规划与行动，仅审计 skipped（轮级跳过
                # 维持轮询语义，用户离开后下一轮自动恢复；不终止主循环）。
                action_result = {
                    "action": "wait",
                    "target": "",
                    "payload": {},
                    "reason": "user_online_sleep",
                    "expected_outcome": "",
                    "result": "skipped",
                }
            else:
                sense = await self._sense()
                plan = await self._plan(sense)
                action_result = await self._execute(plan)
                # 动机反馈 + 焦点回写：绑定真实行动结果（result == "success"），
                # 修复"4 个 record_* 入口生产零调用 → 动机只剩时间演化并饱和"的缺陷；
                # focus 来自 LLM 本轮自报，缺失则沿用上次焦点。
                await self._apply_motivation_feedback(action_result)
                self._apply_plan_focus(plan)
            await self._audit(plan, action_result)
        except Exception as e:
            logger.error("自主循环单轮异常（不冒泡）: %s", e)
            await self._record_error_audit(e, plan)
        finally:
            if action_result is not None:
                self.manager.last_action = str(action_result.get("action", "") or "")
            elif plan is not None:
                self.manager.last_action = str(plan.get("action", "") or "")
            # H12: last_cycle_at 统一用本地带偏移时间戳（日记过滤按本地日期前缀
            # 匹配；_elapsed_minutes 对 tz-aware 时间戳跨时区求差无混算）。
            self.manager.last_cycle_at = self._local_now_iso()
            self._sync_manager_motivations()
            self._sync_manager_focus()
            # G1/A4: manager 状态落盘为同步文件 IO，经 to_thread 卸载
            await asyncio.to_thread(self._save_manager_state)
            # 动机状态（tick + 行为反馈 + 焦点）在轮末统一落盘，保证重启续接
            # 不丢失本轮反馈（motivation_state.json 为动机层真源）。
            await asyncio.to_thread(self._save_motivation)

    async def _apply_user_online_policy(self) -> bool:
        """轮首用户在线策略：把传感器判定写入引擎内休眠标志。

        2026-09-27 人类裁决：行为保留、落点由 killswitch.sleeping 改为引擎内标志
        self._user_online_sleeping。该标志不持久化——它由传感器每轮实时判定，
        跨重启保持无意义；因此本方法不再有落盘 IO（保留 async 形态以对齐唯一调用点
        `_run_round` 的 await）。

        仅在 sensor 为真实 ContextSensor（含可调用 is_user_online）且
        config.safety.user_online_sleep 开启时生效；否则标志置 False 并返回 False
        （不触发休眠，测试 MagicMock 替身也不误触发）。

        Returns:
            bool: 是否因"用户在线"在本轮触发休眠（True=本轮处于用户在线休眠，
            用于审计 trigger_reason 与轮级跳过判定；False=未触发或策略未开启）。
        """
        self._user_online_sleeping = False
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
        self._user_online_sleeping = is_online
        return is_online

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
        """动机层：按流逝分钟 tick 四维动机（落盘由 _run_round 轮末统一承担）。

        落盘统一到轮末，是为了让本轮的行为反馈（_apply_motivation_feedback）
        与焦点回写（_apply_plan_focus）一并计入 motivation_state.json，
        避免"反馈只活在内存、重启即丢一轮"。
        """
        elapsed_minutes = self._elapsed_minutes()
        tick = getattr(self.motivation, "tick", None)
        if callable(tick):
            try:
                result = tick(elapsed_minutes)
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.warning("动机 tick 失败: %s", e)
        self._sync_manager_motivations()
        return self._motivation_dict()

    async def _apply_motivation_feedback(self, action_result: Dict[str, Any]) -> None:
        """按真实行动结果写回动机反馈（只认 handler 的 result == "success"）。

        修复"动机退化为纯时间函数"缺陷：MotivationState 的 4 个行为反馈入口此前在
        生产代码零调用，动机仅剩 tick 的时间演化并饱和。语义（对齐"动机值越高＝
        行动倾向越强"）：

        - read_news / search 成功 → record_info_ingestion（curiosity 回落）；
          且取回非空内容时 → record_material（creative_drive 上升，素材到手）；
        - write_post 成功 → record_interaction（social_need 回落）；
        - write_memory / write_diary 成功 → record_creation（creative_drive 回落，
          创作消费与素材获取配对，避免 creative_drive 只升不降被钉在 1.0）；
        - start_live / stop_live 成功 → record_activity（fatigue 上升）。

        触发点绑定 handler 结果而非 LLM 自述——模型会自称"学到了很多"但未必真实行动。
        异常隔离：任何失败仅告警，不阻断本轮（与各层容错口径一致）。

        注：每日日记的定时触发路径（_maybe_diary）不经此处，保持不变。
        """
        if not isinstance(action_result, dict):
            return
        if str(action_result.get("result", "") or "") != "success":
            return
        action = str(action_result.get("action", "") or "")
        calls: List[str] = []
        if action in ("read_news", "search"):
            calls.append("record_info_ingestion")
            if self._has_material(action_result.get("output")):
                calls.append("record_material")
        elif action == "write_post":
            calls.append("record_interaction")
        elif action in ("write_memory", "write_diary"):
            calls.append("record_creation")
        elif action in ("start_live", "stop_live"):
            calls.append("record_activity")
        for name in calls:
            fn = getattr(self.motivation, name, None)
            if not callable(fn):
                continue
            try:
                out = fn()
                if inspect.isawaitable(out):
                    await out
            except Exception as e:
                logger.warning("动机反馈 %s 失败: %s", name, e)

    @staticmethod
    def _has_material(output: Any) -> bool:
        """判定行动是否真实取回内容（可作创作素材）：非空 list/tuple/set/dict/str 视为有素材。"""
        if isinstance(output, (list, tuple, set)):
            return len(output) > 0
        if isinstance(output, dict):
            return bool(output)
        if isinstance(output, str):
            return bool(output.strip())
        return output is not None

    def _apply_plan_focus(self, plan: Optional[Dict[str, Any]]) -> None:
        """把 LLM 本轮自报的 focus 回写动机层（plan 缺 focus 时沿用上次焦点）。

        焦点不参与时间衰减，仅由自报更新（对齐"LLM 每轮自报"的裁决）。
        """
        if not isinstance(plan, dict):
            return
        focus = plan.get("focus")
        if not isinstance(focus, dict):
            return
        set_focus = getattr(self.motivation, "set_focus", None)
        if not callable(set_focus):
            return
        try:
            set_focus(focus.get("topic", ""), focus.get("level", 0.0))
        except Exception as e:
            logger.warning("焦点回写失败: %s", e)

    def _save_motivation(self) -> None:
        """把动机状态（含焦点）落盘为 motivation_state.json（尽力而为）。"""
        save = getattr(self.motivation, "save", None)
        if not callable(save):
            return
        try:
            save(self._store_dir)
        except Exception as e:
            logger.warning("动机保存失败: %s", e)

    # ------------------------------------------------------------ 3) 规划
    async def _plan(self, sense: Dict[str, Any]) -> Dict[str, Any]:
        """规划层：组装上下文调用 ActionPlanner 输出行动决策。

        上下文带当前焦点（curiosity 的指向性维度），使 LLM 可延续或更换关注对象。
        规划器异常不在此吞掉，交由 _run_round 捕获并记录错误审计。
        """
        context: Dict[str, Any] = {
            "motivations": self._motivation_dict(),
            "focus": self._focus_dict(),
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
        """审计层：追加审计条目（对齐 autonomy_audit.schema.json）并做效果评估。

        plan 可能为 None（用户在线休眠跳过路径等）：None 时按空字典处理，
        trigger_reason 回退到 action_result.reason，保证跳过原因可回溯。

        2026-09-27 人类裁决：Token 记账已随预算记账整体删除；审计条目的
        cost_tokens 字段保留（记录本轮实际消耗，仅不再累计计入任何台账）。
        """
        plan = plan if isinstance(plan, dict) else {}
        entry: Dict[str, Any] = {
            "timestamp": self._local_now_iso(),
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
            # G1/A4: 审计条目落盘为同步文件 IO，经 to_thread 卸载
            await asyncio.to_thread(self.audit.append, entry)
        except Exception as e:
            logger.error("审计写入失败: %s", e)
            return
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
            # G1/A4: 错误审计条目落盘为同步文件 IO，经 to_thread 卸载
            await asyncio.to_thread(
                self.audit.append,
                {
                    "timestamp": self._local_now_iso(),
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
        # L11/H12: 仅日记真正落库（memory_id 存在）才更新 diary_last_at——
        # 失败保留"今日未写"状态允许下一唤醒重试；审计仍记录 failed 条目。
        if (result or {}).get("memory_id"):
            self.manager.diary_last_at = now.isoformat()
            # G1/A4: 状态落盘为同步文件 IO，经 to_thread 卸载（与 :288 同型）
            await asyncio.to_thread(self._save_manager_state)
        try:
            # G1/A4: 审计条目落盘为同步文件 IO，经 to_thread 卸载（与 _audit 同型）
            await asyncio.to_thread(
                self.audit.append,
                {
                    "timestamp": self._local_now_iso(),
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
        """从审计存储取当日条目（供日记生成器使用），健壮处理各形态 list 结果。

        E8 修复：改为带日期下界查询（since=当日 ISO 日期前缀），由审计层直接
        过滤，不再 limit=None 全量加载后内存筛选；对不支持 since 的替身实现
        （TypeError）回退全量查询并保留原内存过滤，行为不变。
        """
        day = now.date().isoformat()
        try:
            try:
                page = self.audit.list(limit=None, since=day)
            except TypeError:
                page = self.audit.list(limit=None)
        except Exception:
            return []
        if isinstance(page, dict):
            items = page.get("items", [])
        else:
            items = getattr(page, "items", None) or []
        if not isinstance(items, list):
            return []
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
        """从 manager_state.json 恢复 manager 字段与 motivations（尽力而为）。

        遗留数据迁移：`status` 做白名单归一化——载入值不属于
        {"running", "paused", "sleeping"} 时（历史预算受限态 / 错误态）置为
        "running"，避免升级后回放已被契约精简的状态枚举；其余字段恢复行为
        不变（持久化字段集合不变，仍保存 status）。
        """
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
                    value = data[field]
                    if field == "status" and value not in _VALID_MANAGER_STATUSES:
                        logger.info(
                            "遗留 manager.status=%r 超出精简枚举，归一化为 running", value
                        )
                        value = "running"
                    setattr(self.manager, field, value)
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
                "diary_last_at": getattr(self.manager, "diary_last_at", None),
            }
            path = Path(self._store_dir) / "manager_state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, data)
        except Exception as e:
            logger.warning("保存 manager 状态失败: %s", e)

    # ================================================================ 工具方法
    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """若 value 是 awaitable 则等待后返回，否则原样返回（兼容 sync/async）。"""
        if inspect.isawaitable(value):
            return await value
        return value

    def _local_now_iso(self) -> str:
        """本地时区 ISO 时间戳（H12 审计条目/last_cycle_at 统一基准）。

        此前审计条目写 UTC 时间戳，而日记过滤器按本地日期前缀
        （startswith(now.date())）匹配，本地 00:00–07:59 生成的条目永远进不了
        当日日志。统一改为本地带偏移时间戳后两侧基准一致；tz-aware ISO 串可被
        _elapsed_minutes / _diary_written_today 直接解析，跨时区求差不引入混算。
        """
        return datetime.now().astimezone().isoformat()

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
                # G1/A1 规则（对齐 decay.py）：遗留 naive 数据按本地时区换算 UTC，
                # 禁止 replace(tzinfo=utc) 直接错标（当前写入端 _local_now_iso
                # 已返回 aware 时间戳，此分支仅为防御遗留数据）。
                if last.tzinfo is None:
                    last = last.astimezone(timezone.utc)
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

    def _focus_dict(self) -> Dict[str, Any]:
        """取焦点对象字典；兼容 motivation.to_focus_dict()，缺省回退空焦点。"""
        to_focus = getattr(self.motivation, "to_focus_dict", None)
        if callable(to_focus):
            try:
                raw = to_focus()
                if isinstance(raw, dict):
                    return {
                        "topic": str(raw.get("topic", "") or ""),
                        "level": float(raw.get("level", 0.0) or 0.0),
                    }
            except Exception:
                pass
        return {"topic": "", "level": 0.0}

    def _sync_manager_focus(self) -> None:
        """把焦点对象同步到 manager.focus（尽力而为，异常不影响落盘流程）。"""
        focus = self._focus_dict()
        try:
            from server.autonomy.models import AutonomyFocus

            self.manager.focus = AutonomyFocus(**focus)
        except Exception:
            pass

    def _sync_manager_motivations(self) -> None:
        """把动机状态同步到 manager.motivations（尽力而为，字段完整才写）。"""
        motivations = self._motivation_dict()
        if {"curiosity", "social_need", "creative_drive", "fatigue"}.issubset(motivations):
            try:
                from server.autonomy.models import Motivations

                self.manager.motivations = Motivations(**motivations)
            except Exception:
                pass
