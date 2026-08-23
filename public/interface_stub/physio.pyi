"""CX-O-Dream 生理信号接口契约存根（零实现，仅签名）。

源真理:
    - spec: .trae/specs/add-dream-physio-heartrate/spec.md
    - 实现: server/autonomy/dream/physio/{estimator,store,runtime}.py
    - 融合状态机: server/autonomy/dream/sleep_sensor.py
    - 配置: server/autonomy/dream/config.py（PhysioConfig / DreamConfig.physio）
    - 数据契约: public/schema/dream_physio_config.schema.json / sleep_sensor_state.schema.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。

异常契约（rules-3 §二，调用方必须处理）:
    - ValueError: PhysioSignalStore.update 收到原始 HR 键（raw_hr / samples /
      hr_sequence 等，隐私红线 R6）；PhysioConfig.store_raw_hr=True（原始心率禁落盘）
    - ValueError: HeartRateSleepEstimator.ingest 收到无法解析的时间戳（非 datetime /
      数值 epoch 秒 / ISO 字符串）
    - KeyError: SleepSensor._provider 收到 S1-S9 之外的未知信号编号

REST 端点语义（/api 前缀；server/api/routers/physio.py，Task 7 契约补全）:
    - POST  /physio/hr                前端上送 HR 样本 {bpm, ts, device_fingerprint}（仅内存）
                                       未启用返回 {"status":"disabled"}；启用返回 {hr_sleep_confidence}
    - POST  /physio/state             前端上送系统状态 {system_idle_sec, user_active}，更新 S1/S6 provider
                                       runtime 无 update_system_state 能力时仍返回 {"ok":true}
    - GET   /physio/status            采集/估计器/融合状态快照；未启用返回 {"status":"disabled"}（200 不抛错）
    - GET   /physio/sleep             当前 SleepSensor 融合状态（对齐 sleep_sensor_state.schema.json）：
                                       {state, confidence, signals:[{name,weight,value,available}], updated_at}
                                       未启用 {"status":"disabled"}；无 sleep_sensor 返回默认清醒态
    - GET   /physio/devices           已配对设备列表 {name, fingerprint(脱敏前 8+****), id(真实指纹仅供 forget)}；
                                       未启用 {"devices":[]}。脱敏 fingerprint 不可用于 forget（必 404）
    - POST  /physio/devices/{id}/forget  解除配对（须传真实指纹 id）；未配对 404
    - GET/PUT /physio/config          读 / 深度合并更新 physio 配置；非法字段或 store_raw_hr=true 返回 422
    - POST  /physio/clear             一键清除生理基线 {ok, cleared}（含 audit 记录）

隐私红线 R6：原始心率不落盘、不入记忆、不入 LLM；store_raw_hr 强制 false；
PhysioSignalStore 仅持久化衍生指标 {base_hr, hr_sleep_confidence,
device_fingerprint, updated_at}。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# DreamConfig 完整契约见 interface_stub/dream.pyi；此处仅引用类型
from server.autonomy.dream.config import DreamConfig

__all__ = [
    "DreamConfig",
    "PhysioConfig",
    "HeartRateSleepEstimator",
    "PhysioSignalStore",
    "SleepSignalProvider",
    "SleepSensor",
    "PhysioRuntime",
]


class PhysioConfig:
    """CX-O-Dream 生理信号接入配置（对齐 dream_physio_config.schema.json）。

    backend="noble" 为**信息性登记键**：标注采集路线由前端 Electron 主进程
    noble 承担，后端无对应实现、不参与任何逻辑。store_raw_hr 强制 False
    （隐私红线 R6）。extra="forbid"：非法字段校验失败（PUT /physio/config 422）。
    """

    enabled: bool  # 默认 False：生理信号总开关（用户显式开启）
    backend: str  # 默认 "noble"：采集路线登记键（前端 Electron noble，后端无实现）
    device_name_hint: str  # 默认 ""：设备名称提示（扫描过滤与展示）
    device_fingerprint: Optional[str]  # 默认 None：已配对设备真实指纹（仅存配置）
    scan_timeout_sec: int  # 默认 15：BLE 扫描超时（秒）
    reconnect_interval_sec: int  # 默认 30：断线重连间隔（秒）
    base_drop_ratio: float  # 默认 0.88：入睡判定心率下降比例
    base_drop_confirm_min: int  # 默认 5：心率下降持续确认时长（分钟）
    hr_stability_threshold: float  # 默认 6.0：窗口心率标准差上限（稳定判定）
    base_hr_learning: bool  # 默认 True：清醒基线自学习开关
    store_raw_hr: bool  # 默认 False（强制）：原始心率禁落盘，写 True 抛 ValueError（R6）


class HeartRateSleepEstimator:
    """后端心率睡眠估计器（内存滑动窗口 + 基线学习 + 入睡置信度）。

    HR 样本流仅在内存滑动窗口（默认 10 分钟）内存在，原始序列不落盘
    （隐私红线 R6）。无效样本（None / <=0 / >220 bpm）标记丢弃，不影响置信度。
    """

    def __init__(
        self,
        config: Optional[PhysioConfig] = None,
        store: Optional[PhysioSignalStore] = None,
        sample_window_min: int = 0,
    ) -> None: ...

    def ingest(self, bpm: Any, ts: Any) -> float:
        """接收一个 HR 样本（bpm + 时间戳），返回当前入睡置信度 [0,1]。

        ts 支持 datetime / ISO 字符串 / 数值时间戳（秒）。

        Returns:
            当前 hr_sleep_confidence [0,1]

        Raises:
            ValueError: ts 无法解析（非 datetime / 数值 / ISO 字符串）
        """
        ...

    def get_state(self) -> Dict[str, Any]:
        """返回当前状态。

        Returns:
            {"base_hr": float, "hr_sleep_confidence": float,
             "window_size": int, "updated_at": Optional[str]}
        """
        ...


class PhysioSignalStore:
    """生理信号衍生指标持久化存储。

    仅持久化 {base_hr, hr_sleep_confidence, device_fingerprint, updated_at}，
    原始 HR 不落盘（隐私红线 R6）。状态常驻内存，load/save 读写 JSON 文件。
    """

    def __init__(self, path: str = "") -> None:
        """path 为空时基于 __file__ 绝对路径解析到 server/autonomy/data/physio_state.json。"""
        ...

    def load(self) -> None:
        """从文件加载状态到内存（文件不存在/损坏时回空状态；按白名单过滤）。"""
        ...

    def save(self) -> None:
        """将内存状态写入文件。"""
        ...

    def clear(self) -> None:
        """一键清除所有生理基线数据（含 base_hr 与设备指纹），落盘空状态。"""
        ...

    def get(self, key: str, default: Any = None) -> Any:
        """读取状态键值；不存在返回 default。"""
        ...

    def update(self, data: Dict[str, Any]) -> None:
        """合并更新衍生指标并落盘（白名单过滤）。

        Raises:
            ValueError: data 含原始 HR 键（raw_hr / samples / hr_sequence 等，R6）
        """
        ...


class SleepSignalProvider:
    """单路睡眠信号 provider（S1-S9）。

    name: 信号编号；label: 中文描述；weight: 基础权重；
    value: 当前信号值 [0,1]；available: 是否有数据源接入。
    """

    name: str
    label: str
    weight: float
    value: float  # 默认 0.0
    available: bool  # 默认 False

    def set_source(self, fn: Callable[[], float]) -> None:
        """注入外部取值函数并标记可用（无源信号的接入点，源就绪后自动启用）。"""
        ...

    def update(self, value: float) -> None:
        """更新信号值（钳制到 [0,1]，非法值归 0）并标记可用。"""
        ...


class SleepSensor:
    """S1-S9 多路睡眠信号融合状态机（AWAKE/DROWSY/ASLEEP/AWAY）。

    动态归一：available 信号权重归一化计算 confidence；S4=1.0 短路信号命中时
    直接 ASLEEP、跳过归一化；S9 心率下降但 S1 行为活跃 → 强制 AWAKE；
    S9 缺席时 weight 0 自动归一（退化纯时间/行为判定）。
    """

    def __init__(
        self,
        now_fn: Optional[Callable[[], datetime]] = None,
        conf_asleep: float = 0.8,
        conf_drowsy: float = 0.5,
        s4_hold_min: float = 10.0,
        away_hr_stale_min: float = 30.0,
        time_prior_span_hours: float = 4.0,
    ) -> None: ...

    def snapshot(self) -> Dict[str, Any]:
        """返回当前状态快照。

        Returns:
            {"state": "AWAKE"|"DROWSY"|"ASLEEP"|"AWAY", "confidence": float,
             "signals": [{"name", "weight", "value", "available"}...], "updated_at": str}
        """
        ...

    def evaluate(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """计算当前融合状态。

        Returns:
            {"state": str, "confidence": float, "updated_at": str}
        """
        ...

    def normalized_weights(self) -> Dict[str, float]:
        """返回参与动态归一信号的归一化权重映射（总权重=1），供验证/调试。"""
        ...

    def set_hr_confidence(self, conf: float) -> None:
        """注入 S9 生理心率置信度 [0,1]（来自 HeartRateSleepEstimator）。"""
        ...

    def set_system_idle(
        self, idle_sec: float, thresholds: Optional[Dict[str, float]] = None
    ) -> None:
        """注入系统空闲时长（秒）驱动 S1 输入静默 / S6 系统锁屏。"""
        ...

    def set_voice_activity(self, recent_sec: Optional[float]) -> None:
        """注入最近语音活动秒数驱动 S2 语音静默；None 时 S2 置为不可用。"""
        ...

    def set_sleep_speech(self, hit: bool) -> None:
        """注入 S4 显式睡眠语命中信号（hit=True 置值 1.0 并记录命中时刻）。"""
        ...

    def set_time_prior(self, now: datetime, circadian: Any) -> None:
        """注入 S7 时间先验：circadian 睡眠窗口内 ≈1，窗口外按距边界小时数递减。"""
        ...

    def set_external_source(self, name: str, fn: Callable[[], float]) -> None:
        """为 S3/S5/S8 无源 provider 注入外部取值函数（接线后自动可用）。"""
        ...


class PhysioRuntime:
    """生理信号运行时容器：桥接 physio REST 路由与估计器/存储/融合状态机。

    由 setup_autonomy 在 dream.enabled 时装配并注入 services.physio_runtime；
    未装配时路由按 disabled 口径自动降级。任何方法异常由调用方（路由）捕获隔离。
    """

    def __init__(
        self,
        estimator: Any = None,
        store: Any = None,
        sleep_sensor: Any = None,
        dream_config: Optional[DreamConfig] = None,
    ) -> None: ...

    def is_enabled(self) -> bool:
        """physio.enabled（false 时路由按 disabled 口径响应）。"""
        ...

    def get_config(self) -> PhysioConfig:
        """返回运行期 PhysioConfig。"""
        ...

    def set_config(self, config: Any) -> None:
        """应用运行期配置（接受 DreamConfig 或 PhysioConfig），尽力同步估计器 config。"""
        ...

    def update_system_state(
        self, system_idle_sec: Any = None, user_active: Any = None
    ) -> None:
        """注入 S1/S6 系统静默 provider 输入（前端 POST /physio/state）。"""
        ...

    def get_devices(self) -> list:
        """已配对设备列表（读 dream_config.physio.device_fingerprint）。

        Returns:
            每项 {"fingerprint": str, "device_name": Optional[str]}；未配对返回 []
        """
        ...

    def forget_device(self, fp: str) -> bool:
        """解除配对：指纹不匹配返回 False；匹配则清空并持久化配置。"""
        ...
