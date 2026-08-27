"""CX-O-Dream 主引擎（server/autonomy/dream/engine.py）。

DreamEngine 串联 采集 → 联想生成 → D7 确定性闸门过滤 → 缓冲隔离（红线 R5 前置），
并自持 CircadianScheduler 实例 + 独立 asyncio 后台循环（start / stop），
与自主主循环（AutonomyEngine._run_loop）完全解耦（spec "DreamEngine 主引擎与昼夜挂点"）。

相位挂点（_run_loop，独立后台任务，不并入自主主循环）：
- 睡眠窗口进入 → asyncio.create_task(run_session)（状态 dreaming，结束后回 idle）
- SleepSensor 生理/行为确认（注入 sleep_sensor 时）：睡眠窗口内状态 ASLEEP，
  或窗口外 S4 显式睡眠语短路 ASLEEP → 触发 run_session（冷却 30min 防高频）；
  Task 3：注入 auto_summarizer 时改走"入睡 LLM 确认闸门 → 首步自动摘要 →
  梦境会话"的入睡流程（确认拒绝回退 DROWSY 并跳过本轮）
- 唤醒窗口进入 → create_task(purge_job.run()) + 可选 consolidator.surface()（surface_on_wake）
- 每 6 小时兜底 purge
- 任何异常被捕获隔离并记日志，绝不影响主服务与语音链路

循环间隔可注入（interval_seconds，默认 60s）便于测试；config.enabled 关闭后循环退出。
sleep_sensor 未注入时入睡判定保持纯 circadian 时间窗口（零回归）；sleep_sensor
调用异常被捕获隔离，不影响主循环。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.autonomy.core.scheduler.circadian import CircadianScheduler
from server.autonomy.dream.config import DreamConfig
from server.protocol.actions import DreamActions

logger = logging.getLogger(__name__)

# 兜底清除周期：每 6 小时（秒）
_FALLBACK_PURGE_SECONDS = 6 * 3600

# SleepSensor 触发冷却：距上次触发不足该秒数不再触发（防高频）
_SLEEP_SENSOR_COOLDOWN_SECONDS = 30 * 60

# S4 显式睡眠语短路阈值（对齐 sleep_sensor._S4_FIRE_THRESHOLD=0.5）
_S4_SHORTCUT_THRESHOLD = 0.5


async def push_dream_event(ws_manager: Any, action: str, data: Dict[str, Any]) -> None:
    """经 ws_manager.broadcast 推送梦境 S→C 事件（type 即 action，直发）。

    对齐 spec "WebSocket 协议"：消息为 {"type": "dream.xxx", "data": {...}}，
    前端 useWebSocket 按 data.type 路由。ws_manager 为 None 或缺少 broadcast
    方法时静默跳过（不阻断梦境主链路）；推送异常仅记日志。
    """
    if ws_manager is None:
        return
    broadcast = getattr(ws_manager, "broadcast", None)
    if not callable(broadcast):
        return
    try:
        await broadcast({"type": action, "data": data})
    except Exception as e:
        logger.warning("梦境事件推送失败: action=%s, %s", action, e)

# 后台循环默认轮询间隔（秒）
_DEFAULT_INTERVAL_SECONDS = 60.0

# 后台循环最小轮询间隔（秒），避免过密空转
_MIN_INTERVAL_SECONDS = 0.05

# 后台循环默认 Agent
_DEFAULT_AGENT_ID = "default"

# 运行状态（对齐 dream_status 契约）
_STATUS_IDLE = "idle"
_STATUS_DREAMING = "dreaming"
_STATUS_PURGE_SCHEDULED = "purge_scheduled"
_STATUS_DISABLED = "disabled"


class DreamEngine:
    """梦境主引擎：采集→生成→过滤→缓冲，昼夜相位挂点 + 独立后台循环。

    Args:
        collector: 素材采集器（DreamMaterialCollector）
        generator: 联想生成器（DreamGenerator）
        dream_filter: 确定性内容闸门（DreamFilter，D7_DREAM_FILTER）
        buffer: 梦境候选缓冲（DreamBuffer，红线 R5 前置）
        consolidator: 固化/清除/提起（DreamConsolidator）
        purge_job: 自动清除任务（DreamPurgeJob）
        config: DreamConfig；None 时使用全默认
        ws_manager: 可选 WebSocket 管理器（预留，会话事件推送；None 可）
        interval_seconds: 后台循环轮询间隔（秒），注入便于测试，默认 60s
        sleep_sensor: 可选 SleepSensor 融合状态机（snapshot() -> {state, ...}）；
            None 时入睡判定保持纯 circadian 时间窗口（零回归）
        sleep_sensor_refresh: 可选每轮刷新回调（刷新 S9 心率置信度 / S7 时间先验），
            调用异常被捕获隔离，不影响主循环
        sleep_confirm_arbiter: 可选入睡 LLM 确认闸门（Task 3；暴露
            should_confirm/is_confirmed/confirm(snapshot) 之一的可调用对象，
            可为 sync/async）。None 时跳过确认直接进入（零回归）
        auto_summarizer: 可选入睡首步自动摘要组件（SleepAutoSummarizer，含
            async summarize(agent_id)）。None 时不自带摘要（零回归）

        注意：仅当 auto_summarizer 被注入时才走"确认闸门 + 首步自动摘要"入睡
        流程；二者任一为 None 时保持原有直接触发行为（`run_session`/`_status`
        语义不变）。
    """

    def __init__(
        self,
        collector,
        generator,
        dream_filter,
        buffer,
        consolidator,
        purge_job,
        config: Optional[DreamConfig] = None,
        ws_manager=None,
        interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
        sleep_sensor=None,
        sleep_sensor_refresh=None,
        sleep_confirm_arbiter=None,
        auto_summarizer=None,
    ):
        self._collector = collector
        self._generator = generator
        self._dream_filter = dream_filter
        self._buffer = buffer
        self._consolidator = consolidator
        self._purge_job = purge_job
        self.config = config or DreamConfig()
        self._ws_manager = ws_manager
        self._interval_seconds = max(float(interval_seconds), _MIN_INTERVAL_SECONDS)
        self._fallback_purge_seconds = float(_FALLBACK_PURGE_SECONDS)
        # SleepSensor 生理/行为确认（可选；None 时保持纯时间窗口，零回归）
        self._sleep_sensor = sleep_sensor
        self._sleep_sensor_refresh = sleep_sensor_refresh
        self._sleep_sensor_cooldown_seconds = float(_SLEEP_SENSOR_COOLDOWN_SECONDS)
        # 入睡 LLM 确认闸门 / 首步自动摘要（Task 3；None 时零回归）
        self._sleep_confirm_arbiter = sleep_confirm_arbiter
        self._auto_summarizer = auto_summarizer
        # 相位调度器：start() 时由 config.schedule.model_dump() 构造
        self._scheduler: Optional[CircadianScheduler] = None
        # 后台任务生命周期
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        # 后台任务引用集合：防止 _safe_run_session/_safe_wake_routines/_safe_purge/
        # _safe_sleep_session 等 fire-and-forget 任务在完成前被 GC 回收而静默中断
        # （asyncio 不持有裸 create_task 的引用，回收会静默丢弃任务）。
        self._bg_tasks: set[asyncio.Task] = set()
        self._status: str = _STATUS_IDLE
        self._last_session_at: Optional[str] = None
        # 最近一次会话触发时刻（窗口边沿 / SleepSensor 确认均记录，供冷却判定）
        self._last_trigger_at: Optional[datetime] = None
        self._stats: Dict[str, int] = {
            "sessions": 0,
            "generated": 0,
            "approved": 0,
            "rejected": 0,
            "purges": 0,
        }

    # ================================================================ 会话
    async def run_session(self, agent_id: str = _DEFAULT_AGENT_ID) -> Dict[str, int]:
        """执行一轮梦境会话：采集 → 生成 → D7 过滤 → 缓冲。

        整轮任何异常被捕获隔离并记日志，不向上抛出，绝不影响主服务。
        统计写入 self._stats（sessions/generated/approved/rejected）。

        Args:
            agent_id: Agent ID

        Returns:
            {"generated": n, "approved": n, "rejected": n}
        """
        try:
            snapshot = await self._collector.collect(agent_id)
        except Exception as e:
            logger.warning("梦境会话：素材采集失败，会话中止: %s", e)
            return self._record_session(0, 0, 0)

        try:
            candidates = await self._generator.generate(snapshot)
        except Exception as e:
            logger.warning("梦境会话：联想生成失败，会话中止: %s", e)
            return self._record_session(0, 0, 0)

        memories = getattr(snapshot, "memories", None) or []
        associated_meta = self._build_associated_meta(memories)

        generated = len(candidates)
        approved = 0
        rejected = 0
        for candidate in candidates:
            try:
                verdict = self._dream_filter.filter_candidate(
                    {
                        "content": candidate.content,
                        "lucidity_score": candidate.lucidity_score,
                    },
                    associated_meta,
                    self.config,
                )
                if not verdict.get("approved"):
                    rejected += 1
                    continue
                self._buffer.put(self._to_buffer_candidate(candidate, agent_id, associated_meta))
                approved += 1
            except Exception as e:
                logger.warning("梦境会话：单条候选处理异常，按拒绝计数: %s", e)
                rejected += 1

        logger.info(
            "梦境会话完成: agent=%s, generated=%s, approved=%s, rejected=%s",
            agent_id,
            generated,
            approved,
            rejected,
        )
        return self._record_session(generated, approved, rejected)

    def _record_session(self, generated: int, approved: int, rejected: int) -> Dict[str, int]:
        """累计会话统计并刷新 last_session_at，返回本轮计数。"""
        self._stats["sessions"] += 1
        self._stats["generated"] += generated
        self._stats["approved"] += approved
        self._stats["rejected"] += rejected
        self._last_session_at = datetime.now().isoformat()
        return {"generated": generated, "approved": approved, "rejected": rejected}

    @staticmethod
    def _build_associated_meta(memories: List[Dict]) -> List[Dict]:
        """从素材快照记忆组装关联记忆元数据（供 D7 闸门校验红线 R2）。

        每项含 id / importance_score / permanent / content，对齐
        DreamFilter.filter_candidate 的 associated_memories_meta 契约。
        """
        metas = []
        for mem in memories or []:
            if not isinstance(mem, dict):
                continue
            metas.append(
                {
                    "id": mem.get("id"),
                    "importance_score": mem.get("importance_score"),
                    "permanent": mem.get("permanent"),
                    "content": mem.get("content"),
                }
            )
        return metas

    @staticmethod
    def _to_buffer_candidate(candidate, agent_id: str, associated_meta: List[Dict]) -> Dict:
        """将 DreamCandidate 组装为 buffer.put 契约候选字典。

        - dream_session_id 复用 generator 的 session_id
        - associated_memories = 关联记忆 id 列表（[记忆 id]）
        """
        return {
            "dream_session_id": candidate.session_id,
            "agent_id": agent_id,
            "candidate_content": candidate.content,
            "associated_memories": [m.get("id") for m in associated_meta],
            "associated_entities": list(candidate.associated_entities or []),
            "lucidity_score": candidate.lucidity_score,
            "emotion_shift": dict(candidate.emotion_shift or {}),
        }

    # ================================================================ 生命周期
    def start(self) -> Optional[asyncio.Task]:
        """启动后台昼夜循环。

        用 config.schedule.model_dump() 构造 CircadianScheduler 实例；
        已在运行或未启用（config.enabled=False，由外部保证不启动）时返回 None。
        """
        if self._task is not None and not self._task.done():
            return None
        if not self.config.enabled:
            logger.info("梦境引擎未启用（config.enabled=False），不启动后台循环")
            return None
        self._stop_event.clear()
        self._scheduler = CircadianScheduler(self.config.schedule.model_dump())
        self._task = asyncio.create_task(self._run_loop())
        return self._task

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪后台任务，防止被 GC 提前回收；任务完成后自动从集合移除。"""
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def stop(self) -> None:
        """停止后台循环：置停止事件并取消后台任务与未完成的子任务。"""
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        # 取消仍在运行的后台子任务（run_session/wake/purge），防止循环退出后遗留
        for bg in list(self._bg_tasks):
            if not bg.done():
                bg.cancel()
        self._bg_tasks.clear()

    async def _run_loop(self) -> None:
        """后台昼夜循环：检测相位切换并触发对应动作（异常隔离）。

        - 睡眠窗口进入 → create_task(run_session)，状态 dreaming，结束后回 idle
        - SleepSensor 生理/行为确认（注入时）：窗口内 ASLEEP 或 S4 短路 → 触发
          run_session（冷却 30min 防高频）；无 sleep_sensor 时保持纯时间窗口
        - 唤醒窗口进入 → create_task(purge_job.run()) + 可选 consolidator.surface()
        - 每 6 小时兜底 purge
        - config.enabled 关闭后退出
        """
        logger.info("梦境引擎后台循环启动")
        prev_sleeping: Optional[bool] = None
        last_fallback = datetime.now()
        while not self._stop_event.is_set() and self.config.enabled:
            try:
                now = datetime.now()
                sleeping = self._scheduler.is_sleep_time(now)

                # 每轮刷新 SleepSensor（S9 心率置信度 / S7 时间先验），异常隔离
                if self._sleep_sensor_refresh is not None:
                    try:
                        self._sleep_sensor_refresh(now)
                    except Exception as e:
                        logger.warning("SleepSensor 刷新异常（已隔离，跳过本轮刷新）: %s", e)

                # 睡眠窗口进入 → 异步发起梦境会话（不阻塞循环）。
                # M-E 修复：仅空闲态且冷却已过才进入——状态非 idle（例如
                # SleepSensor 已开跑的会话/唤醒清扫未回位）时跳过，防止双开。
                if sleeping and prev_sleeping is not True:
                    if self._status != _STATUS_IDLE:
                        logger.info(
                            "睡眠窗口边沿触发跳过（当前状态=%s，防与进行中会话双开）",
                            self._status,
                        )
                    elif not self._cooldown_passed(now):
                        logger.info("睡眠窗口边沿触发冷却未到，跳过本轮梦境会话")
                    else:
                        self._status = _STATUS_DREAMING
                        self._last_trigger_at = now
                        self._track_background_task(
                            asyncio.create_task(self._safe_run_session())
                        )

                # SleepSensor 生理/行为确认（窗口内 ASLEEP / 窗口外 S4 短路，冷却防高频）
                if self._sleep_sensor is not None:
                    self._maybe_trigger_by_sensor(now, sleeping)

                # 唤醒窗口进入 → 清除 + 可选主动提起（surface_on_wake）
                if not sleeping and prev_sleeping is True:
                    self._status = _STATUS_PURGE_SCHEDULED
                    self._track_background_task(asyncio.create_task(self._safe_wake_routines()))

                # 每 6 小时兜底清除
                if (now - last_fallback).total_seconds() >= self._fallback_purge_seconds:
                    last_fallback = now
                    self._track_background_task(asyncio.create_task(self._safe_purge()))

                prev_sleeping = sleeping
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("梦境引擎相位检测异常，已隔离")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
        logger.info("梦境引擎后台循环退出")

    # ================================================================ SleepSensor 触发
    def _maybe_trigger_by_sensor(self, now: datetime, sleeping: bool) -> None:
        """SleepSensor 生理/行为确认触发梦境会话（异常隔离，冷却防高频）。

        - 状态非 ASLEEP / 正在 dreaming / 距上次触发不足冷却 → 不触发
        - 睡眠窗口内 ASLEEP，或窗口外 S4 显式睡眠语短路 ASLEEP → 触发
        - 未注入 auto_summarizer 时保持原有直接触发（零回归）
        - 注入 auto_summarizer 时走"入睡 LLM 确认闸门 + 首步自动摘要"入睡流程：
            确认拒绝 → sleep_sensor 回退非 ASLEEP（DROWSY）并跳过本轮；确认通过 →
            ENTERING_SLEEP，先同步等待自动摘要，完毕后再进入梦境会话（置 dreaming）
        - snapshot() 异常被捕获隔离，不影响主循环
        """
        if self._status == _STATUS_DREAMING:
            return
        if not self._cooldown_passed(now):
            return
        try:
            snapshot = self._sleep_sensor.snapshot()
        except Exception as e:
            logger.warning("SleepSensor 快照读取失败（已隔离，跳过本轮触发）: %s", e)
            return
        if not isinstance(snapshot, dict) or snapshot.get("state") != "ASLEEP":
            return
        s4_shortcut = self._is_s4_shortcut(snapshot)
        if not (sleeping or s4_shortcut):
            return

        # 未注入首步摘要 → 保持原有直接触发行为（零回归）
        if self._auto_summarizer is None:
            self._last_trigger_at = now
            self._status = _STATUS_DREAMING
            # M-E 修复：纳入 _track_background_task，防止 fire-and-forget 任务被 GC 提前回收
            self._track_background_task(asyncio.create_task(self._safe_run_session()))
            logger.info(
                "SleepSensor 确认入睡，触发梦境会话（sleeping=%s, s4_shortcut=%s）",
                sleeping,
                s4_shortcut,
            )
            return

        # 带冷却的入睡流程：确认闸门 + 首步自动摘要 + 梦境会话（异常隔离，不阻塞循环）
        self._last_trigger_at = now
        self._status = _STATUS_DREAMING
        self._track_background_task(asyncio.create_task(self._safe_sleep_session(snapshot)))
        logger.info(
            "SleepSensor 确认入睡候选，进入入睡流程（确认闸门+自动摘要+会话, sleeping=%s, s4_shortcut=%s）",
            sleeping,
            s4_shortcut,
        )

    async def _safe_sleep_session(self, snapshot: Dict[str, Any]) -> None:
        """入睡流程（任务内）：LLM 确认闸门 → ENTERING_SLEEP → 首步摘要 → 梦境会话。

        任一环节异常被捕获隔离并记日志，绝不阻断休眠主链路；确认拒绝时回退
        sleep_sensor 到非 ASLEEP（DROWSY）并跳过本会话，不进入 run_session。
        """
        try:
            # 闸门1：入睡 LLM 确认；拒绝则回退并跳过本轮
            confirmed = await self._sleep_confirmation_gate(snapshot)
            if not confirmed:
                logger.info("入睡 LLM 确认未通过，回退 DROWSY 并跳过本轮梦境会话")
                self._reject_sleep(snapshot)
                return
            # 闸门2：状态流转 ENTERING_SLEEP（传感器侧），随后首步自动摘要
            self._enter_sleep(snapshot)
            if self._auto_summarizer is not None:
                try:
                    await self._auto_summarizer.summarize(_DEFAULT_AGENT_ID)
                except Exception as e:
                    logger.warning("入睡首步自动摘要异常（已隔离，仍继续进入梦境会话）: %s", e)
            # 摘要完成后再调用 run_session（置 dreaming，由 _safe_run_session 管理）
            await self._safe_run_session()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("入睡流程异常，已隔离")
        finally:
            if self._status == _STATUS_DREAMING:
                self._status = _STATUS_IDLE

    async def _sleep_confirmation_gate(self, snapshot: Dict[str, Any]) -> bool:
        """入睡 LLM 确认闸门（可复用 sleep_confirm_arbiter，sync/async 均可）。

        - 未注入 arbiter → 默认通过（True，保持无确认直接进）
        - arbiter 暴露 should_confirm / is_confirmed / confirm 任一方法即调用
          （传入 snapshot）；调用异常被隔离，按"未确认"处理（跳过本轮，防误判入睡）
        - arbiter 无任何可用确认方法 → 记日志并按通过处理（不阻断）
        """
        arbiter = self._sleep_confirm_arbiter
        if arbiter is None:
            return True
        for name in ("should_confirm", "is_confirmed", "confirm"):
            method = getattr(arbiter, name, None)
            if not callable(method):
                continue
            try:
                result = method(snapshot)
                if asyncio.iscoroutine(result) or inspect.isawaitable(result):
                    result = await result
                return bool(result)
            except Exception as e:
                logger.warning("入睡确认闸门调用失败（按未确认处理）: name=%s, %s", name, e)
                return False
        logger.warning("入睡确认闸门：arbiter 无可用确认方法，按通过处理")
        return True

    def _reject_sleep(self, snapshot: Dict[str, Any]) -> None:
        """确认拒绝：将 sleep_sensor 回退到非 ASLEEP（DROWSY），跳过本轮会话。"""
        self._status = _STATUS_IDLE
        if self._sleep_sensor is None:
            return
        try:
            self._sleep_sensor.transition_state("DROWSY")
        except Exception as e:
            logger.warning("SleepSensor 回退 DROWSY 失败（已隔离）: %s", e)

    def _enter_sleep(self, snapshot: Dict[str, Any]) -> None:
        """状态流转 ENTERING_SLEEP：将 sleep_sensor 置入浅睡中间态（异常隔离）。"""
        if self._sleep_sensor is None:
            return
        try:
            self._sleep_sensor.transition_state("ENTERING_SLEEP")
        except Exception as e:
            logger.warning("SleepSensor 置入 ENTERING_SLEEP 失败（已隔离）: %s", e)

    async def trigger_auto_summary(self, agent_id: str = _DEFAULT_AGENT_ID) -> Optional[str]:
        """外部入口：触发一次入睡首步自动摘要（physio runtime / 引擎启动可调用）。

        未注入 auto_summarizer 或摘要异常时返回 None，绝不阻断调用方。

        Args:
            agent_id: Agent ID

        Returns:
            生成的摘要文本；无需执行/未注入/异常时返回 None
        """
        if self._auto_summarizer is None:
            logger.info("入睡首步自动摘要未装配（auto_summarizer=None），跳过")
            return None
        try:
            return await self._auto_summarizer.summarize(agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("触发入睡首步自动摘要异常（已隔离）: agent=%s, %s", agent_id, e)
            return None

    def _cooldown_passed(self, now: datetime) -> bool:
        """距上次会话触发（窗口边沿或 SleepSensor 确认）是否已超过冷却。"""
        last = self._last_trigger_at
        if last is None:
            return True
        return (now - last).total_seconds() >= self._sleep_sensor_cooldown_seconds

    @staticmethod
    def _is_s4_shortcut(snapshot: Dict[str, Any]) -> bool:
        """判定快照是否由 S4 显式睡眠语短路（窗口外也可触发的依据）。

        对齐 SleepSensor：S4 available 且 value >= 0.5（_S4_FIRE_THRESHOLD）为短路命中。
        """
        for sig in snapshot.get("signals", []) or []:
            if not isinstance(sig, dict) or sig.get("name") != "S4":
                continue
            try:
                value = float(sig.get("value", 0.0))
            except (TypeError, ValueError):
                value = 0.0
            return bool(sig.get("available")) and value >= _S4_SHORTCUT_THRESHOLD
        return False

    # ================================================================ 后台任务包装
    async def _safe_run_session(self) -> None:
        """包装 run_session：状态 dreaming → 结束后回 idle，异常隔离。

        会话前后经 WS 推送 dream.session_started / dream.session_completed
        （S→C，data 含 agent_id / 候选数 / 状态；ws_manager 为 None 时静默）。
        """
        try:
            await push_dream_event(
                self._ws_manager,
                DreamActions.SESSION_STARTED,
                {"agent_id": _DEFAULT_AGENT_ID, "status": _STATUS_DREAMING},
            )
            result = await self.run_session(_DEFAULT_AGENT_ID)
            await push_dream_event(
                self._ws_manager,
                DreamActions.SESSION_COMPLETED,
                {
                    "agent_id": _DEFAULT_AGENT_ID,
                    "status": _STATUS_IDLE,
                    "generated": result.get("generated", 0),
                    "approved": result.get("approved", 0),
                    "rejected": result.get("rejected", 0),
                },
            )
        except Exception:
            logger.exception("梦境会话任务异常，已隔离")
        finally:
            if self._status == _STATUS_DREAMING:
                self._status = _STATUS_IDLE

    async def _safe_wake_routines(self) -> None:
        """唤醒例行任务：清除 + 可选主动提起（异常隔离）。"""
        try:
            await self._purge_job.run(_DEFAULT_AGENT_ID)
            self._stats["purges"] += 1
            if self.config.surface_on_wake:
                await self._consolidator.surface(_DEFAULT_AGENT_ID)
        except Exception:
            logger.exception("梦境唤醒例行任务异常，已隔离")
        finally:
            if self._status == _STATUS_PURGE_SCHEDULED:
                self._status = _STATUS_IDLE

    async def _safe_purge(self) -> None:
        """兜底清除任务（异常隔离）。"""
        try:
            await self._purge_job.run(_DEFAULT_AGENT_ID)
            self._stats["purges"] += 1
        except Exception:
            logger.exception("梦境兜底清除异常，已隔离")

    # ================================================================ 状态查询
    def get_status(self) -> Dict[str, Any]:
        """返回引擎运行状态。

        - 后台任务未启动/已结束 → status=disabled
        - 运行中 → status ∈ idle / dreaming / purge_scheduled
        disabled 由外部在 enabled=false 时不启动引擎。
        """
        enabled = bool(self.config.enabled)
        running = self._task is not None and not self._task.done()
        return {
            "status": self._status if running else _STATUS_DISABLED,
            "enabled": enabled,
            "last_session_at": self._last_session_at,
            "stats": dict(self._stats),
        }
