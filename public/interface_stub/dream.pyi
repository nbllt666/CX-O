"""CX-O-Dream 梦境引擎接口契约存根（零实现，仅签名）。

源真理:
    - spec: .trae/specs/add-dream-engine-embedded/spec.md
    - 实现: server/autonomy/dream/{config,engine,buffer,consolidator,purge}.py
    - _DreamMixin: server/core/memory/mixins/dream_mixin.py（第 10 个 Mixin）
    - 数据契约: public/schema/dream_config.schema.json / dream_status.schema.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。

异常契约（rules-3 §二，调用方必须处理）:
    - DreamIntegrityError: 梦境记忆完整性断言失败（红线 R1/R3 违反），不写入任何记录
    - ValueError: DreamBuffer.mark_decision 收到非法 decision（pending/approved/rejected 之外）
    - RuntimeError: 梦境记忆写入数据库失败（500）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

__all__ = [
    "DreamIntegrityError",
    "ScheduleConfig",
    "DreamConfig",
    "DreamEngine",
    "DreamBuffer",
    "DreamConsolidator",
    "DreamPurgeJob",
    "_DreamMixin",
]


class DreamIntegrityError(ValueError):
    """梦境记忆完整性断言失败（红线 R1/R3 违反时抛出，且不写入任何记录）。

    触发条件：metadata.dream_session_id 缺失或与参数不符、metadata.source != 'dream_engine'、
    或尝试 permanent=True。见 _DreamMixin.write_dream_memory。
    """


class ScheduleConfig:
    """日程配置（schedule 子对象，复用 server.autonomy.config.ScheduleConfig）。

    时间字段为 HH:MM 格式（pattern ^([01]?[0-9]|2[0-3]):[0-5][0-9]$），
    quiet_windows 为 "HH:MM-HH:MM" 静默档窗口列表。非法格式抛 ValueError。
    """

    wake_time: str  # 默认 "08:00"：起床时间 HH:MM
    sleep_time: str  # 默认 "02:00"：入睡时间 HH:MM（可跨午夜）
    golden_start: str  # 默认 "19:00"：黄金档开始 HH:MM
    golden_end: str  # 默认 "23:00"：黄金档结束 HH:MM
    diary_time: str  # 默认 "02:00"：每日日记时刻 HH:MM
    quiet_windows: List[str]  # 默认 []：静默档窗口列表 "HH:MM-HH:MM"


class DreamConfig:
    """CX-O-Dream 梦境引擎配置（对齐 dream_config.schema.json；契约无必填字段，缺失自动补齐默认值）。

    独立配置模块（人类裁决：不并入 UnifiedConfig / config_hot_reload），
    存储于 server/autonomy/data/dream_config.json，经 load_config/save_config 读写。
    extra="forbid"：非法字段校验失败（PUT /dream/config 返回 422）。
    """

    enabled: bool  # 默认 False：梦境引擎总开关
    model: str  # 默认 "summary"：联想生成所用模型（不用主模型，避免占用主链路槽位）
    dream_temperature: float  # 默认 0.9：联想生成温度
    candidates_per_session: int  # 默认 3：单次会话产出候选条数
    material_window_days: int  # 默认 7：素材采集时间窗（天）
    max_material_items: int  # 默认 20：边缘记忆采集上限
    min_lucidity: float  # 默认 0.3：清醒度下限（低于则 D7 闸门拦截）
    dream_ttl_hours: int  # 默认 72：未确认梦境保留时长（小时）
    purge_threshold: float  # 默认 0.1：重要性低于此值触发清除
    confirmed_importance: float  # 默认 0.4：固化确认后的重要性分数
    surface_on_wake: bool  # 默认 True：唤醒窗口是否主动提起梦境
    surface_probability: float  # 默认 0.5：主动提起概率门
    max_surface_per_day: int  # 默认 1：每日主动提起次数上限
    schedule: ScheduleConfig  # 睡眠/唤醒日程（默认睡眠 02:00-08:00）


class DreamEngine:
    """梦境主引擎：采集→生成→D7 过滤→缓冲，昼夜相位挂点 + 独立 asyncio 后台循环。

    相位挂点：睡眠窗口进入 → run_session（状态 dreaming → idle）；唤醒窗口进入 →
    DreamPurgeJob.run() + 可选 surface()；每 6 小时兜底清除。任何异常被捕获隔离，
    绝不影响主服务与语音链路（spec "DreamEngine 主引擎与昼夜挂点"）。
    """

    config: DreamConfig

    async def run_session(self, agent_id: str = "default") -> Dict[str, int]:
        """执行一轮梦境会话：采集 → 生成 → D7 过滤 → 缓冲（异常隔离，不向上抛出）。

        Returns:
            {"generated": int, "approved": int, "rejected": int} 本轮计数
        """
        ...

    def get_status(self) -> Dict[str, Any]:
        """返回引擎运行状态快照（对齐 dream_status.schema.json）。

        Returns:
            {"status": "idle"|"dreaming"|"purge_scheduled"|"disabled",
             "enabled": bool, "last_session_at": Optional[str], "stats": Dict[str, int]}
            后台任务未启动/已结束时 status="disabled"。
        """
        ...

    def start(self) -> Optional[asyncio.Task]:
        """启动后台昼夜循环；已在运行或 config.enabled=False 时返回 None。

        用 config.schedule.model_dump() 构造 CircadianScheduler 实例。

        Returns:
            后台 asyncio.Task；未启动时 None
        """
        ...

    def stop(self) -> None:
        """停止后台循环：置停止事件并取消后台任务。"""
        ...


class DreamBuffer:
    """梦境候选缓冲——固化前的梦境候选隔离存储（红线 R5 前置）。

    独立 SQLite 文件 data/dream_buffer.db，与主库（memories）完全隔离，
    绝不污染真实记忆。decision 取值 pending / approved / rejected。
    """

    def put(self, candidate: dict) -> int:
        """候选入缓冲：写入 decision='pending'，expires_at=created_at+dream_ttl_hours。

        candidate 字段：dream_session_id / agent_id / candidate_content /
        associated_memories / associated_entities / lucidity_score / emotion_shift。

        Returns:
            新记录 id
        """
        ...

    def list(
        self,
        agent_id: str = "default",
        decision: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """按 agent 列出缓冲候选（created_at DESC），可过滤 decision。"""
        ...

    def count(
        self,
        agent_id: str = "default",
        decision: Optional[str] = None,
    ) -> int:
        """按 agent 统计缓冲候选总匹配数，可过滤 decision（供分页 total 使用）。"""
        ...

    def get(self, buffer_id: int) -> Optional[Dict[str, Any]]:
        """按 id 查询缓冲候选；不存在返回 None。"""
        ...

    def get_by_session(self, dream_session_id: str) -> List[Dict[str, Any]]:
        """按梦境会话查询缓冲候选（全部 decision），created_at DESC。"""
        ...

    def mark_decision(
        self,
        buffer_id: int,
        decision: str,
        reason: str = "",
        retention_days: Optional[int] = None,
    ) -> bool:
        """标记决策：decision ∈ pending/approved/rejected。

        - rejected：expires_at = now + retention_days（默认 30 天，保留审计）
        - approved/pending：不改 expires_at

        Returns:
            是否命中记录

        Raises:
            ValueError: decision 非法值（不在 pending/approved/rejected 中）
        """
        ...

    def purge_expired(self, now: Optional[datetime] = None) -> int:
        """删除 expires_at 已过期的缓冲候选。

        Returns:
            删除的记录数
        """
        ...


class DreamConsolidator:
    """梦境候选固化 / 清除 / 主动提起（spec "DreamConsolidator 固化/清除"）。

    三态：consolidate → 写主库（type='dream'、consolidation_state='confirmed'、
    is_ground_truth 保持 false）；reject → 缓冲置 rejected（保留 30 天审计）不写主库；
    无响应 → 保持 pending 留待 purge。**固化 ≠ 变成事实**。
    """

    def consolidate(self, buffer_id: int, agent_id: str = "default") -> Optional[int]:
        """固化一条梦境候选：写主库 + 提级 + 缓冲置 approved。

        Returns:
            新写入的梦境记忆 id；候选不存在或已决策（rejected/approved）返回 None
        """
        ...

    def reject(self, buffer_id: int, agent_id: str = "default", reason: str = "") -> bool:
        """否定一条梦境候选：缓冲置 rejected（保留 30 天审计），不写主库。

        Returns:
            是否命中并标记成功；候选不存在或已 rejected 返回 False
        """
        ...

    async def surface(self, agent_id: str = "default") -> bool:
        """按概率与每日次数上限主动提起一条梦境候选（推送 {"type": "dream.surface"}）。

        条件（全部满足才推送）：surface_on_wake 为真、当日次数未达
        max_surface_per_day、random() < surface_probability、存在 pending 候选。

        Returns:
            是否成功提起并推送
        """
        ...


class DreamPurgeJob:
    """梦境自动清除任务（红线 R4，全部软删 + 审计，只动 type='dream'）。

    清除：①超 dream_ttl_hours 且未确认（pending/surfaced）②importance_score <
    purge_threshold ③dream_buffer 中过期候选。唤醒窗口 + 每 6 小时兜底触发。
    """

    async def run(self, agent_id: str = "default") -> Dict:
        """执行一轮自动清除。

        Returns:
            {"purged_memories": int, "purged_buffer": int} 被清除数量统计
        """
        ...


class _DreamMixin:
    """梦境记忆写入与生命周期 mixin（第 10 个 Mixin，MemoryManager 继承链追加）。

    以 type='dream' 软隔离写入 memories 表，绝不污染真实记忆（红线 R1/R3）。
    decay_type='dream'，decay_params 由本 Mixin 写入
    （pending {"alpha":1.0,"lambda1":0.8} / confirmed {"alpha":1.0,"lambda1":0.25}）。
    """

    def write_dream_memory(
        self,
        content: str,
        dream_session_id: str,
        metadata: Optional[Dict] = None,
        agent_id: str = "default",
    ) -> int:
        """写入一条梦境记忆（type='dream'）。

        强制落库字段：metadata.is_ground_truth=False、consolidation_state='pending'、
        surfaced_at=None、confirmed_at=None、decay_type='dream'、
        decay_params={"alpha":1.0,"lambda1":0.8}、importance=1、
        importance_score=0.15、permanent=FALSE。写 audit 'create_dream'。

        Returns:
            记忆ID

        Raises:
            DreamIntegrityError: 断言失败（metadata.dream_session_id 缺失/不符、
                source != 'dream_engine'、permanent=True），不写入
            RuntimeError: 数据库写入失败（500）
        """
        ...

    def consolidate_dream(
        self,
        memory_id: int,
        confirmed_importance: float = 0.4,
    ) -> bool:
        """固化梦境记忆（pending/surfaced → confirmed）。

        仅对 type='dream' 且 consolidation_state in (pending, surfaced) 生效；
        更新 importance_score=confirmed_importance、decay_params 放缓（λ=0.25）、
        metadata.consolidation_state='confirmed'、confirmed_at=now，写 audit
        'consolidate_dream'。

        Returns:
            是否固化成功（非梦境 / 状态不符 / 不存在时返回 False）
        """
        ...

    def reject_dream(self, memory_id: int, reason: str = "") -> bool:
        """否定并软删一条梦境记忆（仅 type='dream' 生效，is_deleted=TRUE）。

        写 audit 'reject_dream'（details 含 reason）；不写入共享 rejected_content 表。

        Returns:
            是否软删成功
        """
        ...

    def purge_dream_session(
        self,
        dream_session_id: str,
        agent_id: str = "default",
    ) -> int:
        """按会话批量软删全部 type='dream' 记忆（红线 R5 回滚）。

        按 metadata.dream_session_id 匹配，逐条写 audit 'rollback_dream_session'。

        Returns:
            软删的梦境记忆数量
        """
        ...

    def list_dreams(
        self,
        agent_id: str = "default",
        state: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """列出梦境记忆（type='dream'，不含软删）。

        Args:
            agent_id: Agent ID
            state: 按 consolidation_state 过滤（pending/surfaced/confirmed），None 不过滤
            limit: 返回条数上限（默认 50）

        Returns:
            梦境记忆列表（created_at DESC）
        """
        ...
