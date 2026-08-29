"""CX-O-Dream 生理信号衍生指标持久化（server/autonomy/dream/physio/store.py）。

- 持久化**仅衍生指标** {base_hr, hr_sleep_confidence, device_fingerprint, updated_at}，
  原始 HR 序列只存在于估计器内存滑动窗口，绝不落盘（隐私红线 R6）
- 存储路径基于 __file__ 绝对路径解析到 server/autonomy/data/physio_state.json
  （对齐 config.py resolve_store_dir 模式，禁止相对路径），可注入 path 便于测试
- 写路径白名单：update() 传入原始 HR 键（raw_hr / samples 等）时抛 ValueError
- 落盘节流：update() 按 _MIN_FLUSH_INTERVAL_SEC 最小间隔节流（interval 内仅置脏
  不写盘，写放大修复），get() 始终直读内存最新状态；flush() 强制落盘兜底脏数据
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict

from server.autonomy._atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# 数据目录：本文件位于 server/autonomy/dream/physio/ 下，向上三级即 server/autonomy/，
# 数据文件为 server/autonomy/data/physio_state.json（对齐 config.resolve_store_dir）。
_DEFAULT_STATE_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "data" / "physio_state.json"
)

# 落盘节流最小间隔（秒）：update() 高频调用时 interval 内仅置脏不落盘，
# 由下一次超过间隔的 update() 或 flush() 补写（单调时钟，不受系统时间回拨影响）
_MIN_FLUSH_INTERVAL_SEC = 30.0

# 允许持久化的键（白名单：只存衍生指标，禁止原始 HR）
_ALLOWED_KEYS = (
    "base_hr",
    "hr_sleep_confidence",
    "device_fingerprint",
    "updated_at",
)

# 原始 HR 相关键（禁止入白名单，update 命中即抛 ValueError）
_RAW_HR_KEYS = frozenset(
    {
        "raw_hr",
        "hr_samples",
        "hr_sequence",
        "samples",
        "raw_samples",
        "hr_values",
    }
)


class PhysioSignalStore:
    """生理信号衍生指标持久化存储。

    仅持久化 {base_hr, hr_sleep_confidence, device_fingerprint, updated_at}，
    原始 HR 不落盘。state 常驻内存，load/save 读写 JSON 文件；update 白名单
    过滤并落盘，clear 一键清空全部生理基线数据。
    """

    def __init__(self, path: str = ""):
        self.path = path or _DEFAULT_STATE_PATH
        self._state: Dict[str, Any] = {}
        # 落盘节流状态：脏标记 + 上次落盘的单调时钟时间戳
        self._dirty = False
        self._last_save_monotonic = 0.0
        self.load()

    # -------------------------------------------------------------- 读写
    def load(self) -> None:
        """从文件加载状态到内存（文件不存在/损坏时回空状态）。

        加载时按白名单过滤，拒绝文件中可能存在的原始 HR 等未授权键。
        """
        p = Path(self.path)
        if not p.exists():
            self._state = {}
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("读取生理状态失败 %s: %s", self.path, e)
            self._state = {}
            return
        if isinstance(raw, dict):
            self._state = {k: raw[k] for k in _ALLOWED_KEYS if k in raw}
        else:
            self._state = {}

    def save(self) -> None:
        """将内存状态原子写入文件（保持 atomic_write_json 原子写不变）。"""
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(p, self._state)
        # 落盘成功后清脏并记录节流基准时间戳
        self._dirty = False
        self._last_save_monotonic = time.monotonic()

    def flush(self) -> None:
        """强制落盘：忽略节流间隔，立即把当前内存状态写入文件。

        供关闭/退出路径显式调用，确保节流窗口内的脏数据不丢失。
        """
        self.save()

    # -------------------------------------------------------------- 操作
    def clear(self) -> None:
        """一键清除所有生理基线数据（含 base_hr 与设备指纹），立即落盘空状态。"""
        self._state = {}
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        """读取状态键值；不存在返回 default。"""
        return self._state.get(key, default)

    def update(self, data: Dict[str, Any]) -> None:
        """合并更新衍生指标（白名单过滤），落盘按最小间隔节流。

        仅接受 _ALLOWED_KEYS 内的键；传入原始 HR 键（raw_hr / samples /
        hr_sequence 等）时抛 ValueError（隐私红线 R6）。值为 None 的键跳过
        （不清除既有值，清除请用 clear()）。

        节流策略：距上次落盘不足 _MIN_FLUSH_INTERVAL_SEC 秒时仅置脏标记不写盘；
        内存状态始终最新，get() 直读内存不受影响，脏数据由下一次超过间隔的
        update() 或 flush() 补写。
        """
        for key in data:
            if key in _RAW_HR_KEYS or "raw" in str(key).lower() or "sample" in str(key).lower():
                raise ValueError(f"禁止持久化原始心率字段 {key!r}（隐私红线 R6）")
        changed = False
        for key in _ALLOWED_KEYS:
            if key in data and data[key] is not None:
                self._state[key] = data[key]
                changed = True
        if not changed:
            return
        # 节流落盘：interval 内仅置脏，超间隔才写盘
        self._dirty = True
        if time.monotonic() - self._last_save_monotonic >= _MIN_FLUSH_INTERVAL_SEC:
            self.save()
