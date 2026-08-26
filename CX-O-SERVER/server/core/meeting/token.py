"""模块二 · SpeakingToken —— 全局发言令牌（防菜市场的命根子）。

同一时刻只有持有令牌的 agent 能让 TTS 出声，从物理上杜绝多 agent 同时说话。

设计基准：《CX-O 多 Agent 语音会议协调器》§5。

核心规则：
- 唯一性：同一时刻只有一个 ``holder``。
- 用户优先：``revoke()`` 强制收回，所有 agent 静音（触发各 AgentMember 打断）。
- 申请失败：进入「举手队列」（``pending_queue``），令牌释放后自动排队。
- 持有超时：``token_hold_timeout_sec``（默认 30）超时自动释放，防某 agent 霸麦。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Deque, Optional

from collections import deque

from server.core.meeting.models import TokenState

logger = logging.getLogger(__name__)

# 打断回调类型：async (revoked_holder: Optional[str]) -> Awaitable[None]
InterruptCallback = Callable[..., Awaitable[None]]


class SpeakingToken:
    """发言令牌。

    用例（互斥 + 梯队）：

    >>> token = SpeakingToken(token_hold_timeout_sec=30)
    >>> await token.acquire("A")   # True
    >>> await token.acquire("B")   # False（B 进 pending_queue）
    >>> token.who_holds() == "A"   # True
    >>> await token.revoke()       # 用户开口/点名，强制收回 A
    >>> await token.release()      # 清空令牌并让给队列下一个
    """

    def __init__(
        self,
        token_hold_timeout_sec: float = 30.0,
        on_revoke: Optional[InterruptCallback] = None,
    ):
        self._state: TokenState = TokenState.IDLE
        self._holder: Optional[str] = None
        # 异步锁：防并发抢占（同事件循环内 protect acquire/release/revoke 互斥）
        self._lock = asyncio.Lock()
        # 举手队列：申请失败进入队尾，令牌释放后按队首优先授权
        self.pending_queue: Deque[str] = deque()
        self.token_hold_timeout_sec = float(token_hold_timeout_sec)
        # revoke 时回调（触发各 AgentMember 打断停 TTS）
        self._on_revoke: Optional[InterruptCallback] = on_revoke
        # 持有超时自动释放（取消防霸麦）
        self._release_task: Optional[asyncio.Task] = None

    # ---------------------------------------------------------------- 状态查询
    @property
    def state(self) -> TokenState:
        """当前令牌状态。"""
        return self._state

    @property
    def is_held(self) -> bool:
        """是否正被持有着。"""
        return self._state == TokenState.HELD and self._holder is not None

    def who_holds(self) -> Optional[str]:
        """返回当前持有者 agent_id；无则返回 None。"""
        return self._holder

    # ---------------------------------------------------------------- 申请 / 释放
    async def acquire(self, agent_id: str) -> bool:
        """申请令牌。

        绑定持有超时自动释放任务；申请失败则将其加入举手队列。
        """
        async with self._lock:
            if self._state == TokenState.REVOKED:
                # 已强制收回（用户开口），本回合内不再放行，仅记录排队
                if agent_id not in self.pending_queue:
                    self.pending_queue.append(agent_id)
                return False
            if self._holder is not None:
                if agent_id not in self.pending_queue:
                    self.pending_queue.append(agent_id)
                return False
            self._set_holder(agent_id)
            return True

    async def release(self, agent_id: Optional[str] = None) -> Optional[str]:
        """释放令牌（可选指定请求者，非持有者释放被忽略）。

        Returns:
            接下来被授权的中holder；无则 None。
        """
        next_holder: Optional[str] = None
        async with self._lock:
            if self._holder is not None and (
                agent_id is None or self._holder == agent_id
            ):
                self._clear_holder()
            # 从举手队列取队首授权（公平轮候）
            while self._holder is None and self.pending_queue:
                candidate = self.pending_queue.popleft()
                if self._state == TokenState.REVOKED:
                    # 已收回则不再放行，清空队列
                    self.pending_queue.clear()
                    break
                self._set_holder(candidate)
                next_holder = candidate
                break
        return next_holder

    async def revoke(self) -> Optional[str]:
        """强制收回令牌（用户说话 / 高优先级打断时调用）。

        状态置为 REVOKED、清空持有者与队列，并触发 ``_on_revoke`` 回调
        让各 AgentMember 打断（停 TTS）。
        """
        revoked: Optional[str] = None
        async with self._lock:
            revoked = self._holder
            self._cancel_timeout()
            self._holder = None
            self.pending_queue.clear()
            self._state = TokenState.REVOKED
        if revoked is not None and self._on_revoke is not None:
            try:
                await self._on_revoke(revoked)
            except Exception as e:  # 回调兜底，不阻塞收回
                logger.error("SpeakingToken revoke 回调执行错误: %s", e)
        return revoked

    async def reset(self) -> None:
        """将令牌从 REVOKED 复位到 IDLE（供新一轮用户话语后恢复调度）。"""
        async with self._lock:
            self._cancel_timeout()
            self._holder = None
            self.pending_queue.clear()
            self._state = TokenState.IDLE

    # ---------------------------------------------------------------- 内部工具
    def _set_holder(self, agent_id: str) -> None:
        """在锁内设置持有者并排定超时自动释放。"""
        self._holder = agent_id
        self._state = TokenState.HELD
        self._schedule_timeout(agent_id)

    def _clear_holder(self) -> None:
        """在锁内清空持有者并取消防霸麦定时器。"""
        self._cancel_timeout()
        self._holder = None
        if self._state == TokenState.HELD:
            self._state = TokenState.IDLE

    def _schedule_timeout(self, agent_id: str) -> None:
        """排定持有超时自动释放（<=0 表示不限时霸麦）。"""
        timeout = self.token_hold_timeout_sec
        if timeout is None or timeout <= 0:
            return

        async def _timeout_runner():
            try:
                await asyncio.sleep(timeout)
            except asyncio.CancelledError:
                return
            # 超时触发释放时，先解除对本任务的引用，避免释放过程内部 _set_holder 重新
            # 排定下一持有者定时器时 _cancel_timeout 取消到当前正在执行释放的自身，
            # 制造 "task exception was never retrieved"。
            if self._release_task is asyncio.current_task():
                self._release_task = None
            try:
                await self.release(agent_id=agent_id)
            except asyncio.CancelledError:
                # 释放过程被外部取消（如协程取消），安全终止，不向上抛
                return
            logger.info(
                "SpeakingToken 持有超时（%.1fs），自动释放 %s", timeout, agent_id
            )

        self._cancel_timeout()
        self._release_task = asyncio.create_task(_timeout_runner())

    def _cancel_timeout(self) -> None:
        """取消当前持有超时任务（若有）。"""
        task = self._release_task
        if task and not task.done():
            task.cancel()
        self._release_task = None