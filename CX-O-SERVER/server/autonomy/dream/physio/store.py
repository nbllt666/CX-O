"""CX-O-Dream 生理信号衍生指标持久化（server/autonomy/dream/physio/store.py）。

- 持久化**仅衍生指标** {base_hr, hr_sleep_confidence, device_fingerprint, updated_at}，
  原始 HR 序列只存在于估计器内存滑动窗口，绝不落盘（隐私红线 R6）
- 存储路径基于 __file__ 绝对路径解析到 server/autonomy/data/physio_state.json
  （对齐 config.py resolve_store_dir 模式，禁止相对路径），可注入 path 便于测试
- 写路径白名单：update() 传入原始 HR 键（raw_hr / samples 等）时抛 ValueError
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 数据目录：本文件位于 server/autonomy/dream/physio/ 下，向上三级即 server/autonomy/，
# 数据文件为 server/autonomy/data/physio_state.json（对齐 config.resolve_store_dir）。
_DEFAULT_STATE_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "data" / "physio_state.json"
)

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
        """将内存状态写入文件。"""
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------- 操作
    def clear(self) -> None:
        """一键清除所有生理基线数据（含 base_hr 与设备指纹），落盘空状态。"""
        self._state = {}
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        """读取状态键值；不存在返回 default。"""
        return self._state.get(key, default)

    def update(self, data: Dict[str, Any]) -> None:
        """合并更新衍生指标并落盘（白名单过滤）。

        仅接受 _ALLOWED_KEYS 内的键；传入原始 HR 键（raw_hr / samples /
        hr_sequence 等）时抛 ValueError（隐私红线 R6）。值为 None 的键跳过
        （不清除既有值，清除请用 clear()）。
        """
        for key in data:
            if key in _RAW_HR_KEYS or "raw" in str(key).lower() or "sample" in str(key).lower():
                raise ValueError(f"禁止持久化原始心率字段 {key!r}（隐私红线 R6）")
        for key in _ALLOWED_KEYS:
            if key in data and data[key] is not None:
                self._state[key] = data[key]
        self.save()
