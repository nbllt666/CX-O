"""CX-O-Dream 生理信号运行时容器（server/autonomy/dream/physio/runtime.py）。

PhysioRuntime 是 physio REST 路由（server/api/routers/physio.py）的运行时依赖注入
容器：持有 estimator / store / sleep_sensor / dream_config，暴露路由契约方法
（is_enabled / get_config / set_config / update_system_state / get_devices /
forget_device）。由 setup_autonomy 在 dream.enabled 时装配并注入
services.physio_runtime；未装配时路由按 disabled 口径自动降级。

- is_enabled()：physio.enabled（false 时所有依赖引擎的端点返回 disabled）
- get_config()：返回 PhysioConfig（含 backend/device_fingerprint/device_name_hint，
  对齐路由 get_status 直接读 cfg.* 的口径）
- set_config()：接受 DreamConfig 或 PhysioConfig，更新运行期配置并尽力同步
  估计器 config（base_drop_ratio 等阈值变更即时生效）
- update_system_state()：S1/S6 系统静默 provider 输入（前端 POST /physio/state）
- get_devices() / forget_device()：设备配对管理（读/清 dream_config.physio.device_fingerprint）

任何方法异常由调用方（路由）捕获隔离，不影响主服务与梦境主流程（隐私红线 R6）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from server.autonomy.dream.config import DreamConfig, save_config

logger = logging.getLogger(__name__)

# user_active=False 且未上报 idle_sec 时视为长时间静默（S1 满静默 600s / S6 锁屏 900s）
_FULL_IDLE_SEC = 3600.0


class PhysioRuntime:
    """生理信号运行时容器：桥接 physio REST 路由与估计器/存储/融合状态机。"""

    def __init__(
        self,
        estimator: Any = None,
        store: Any = None,
        sleep_sensor: Any = None,
        dream_config: Optional[DreamConfig] = None,
    ):
        self.estimator = estimator
        self.store = store
        self.sleep_sensor = sleep_sensor
        self._config = dream_config or DreamConfig()

    # -------------------------------------------------------------- 状态/配置
    def is_enabled(self) -> bool:
        """physio.enabled（false 时路由按 disabled 口径响应）。"""
        return bool(self._config.physio.enabled)

    def get_config(self) -> Any:
        """返回运行期 PhysioConfig（对齐路由 get_status 直读 cfg.backend 等字段）。"""
        return self._config.physio

    def set_config(self, config: Any) -> None:
        """应用运行期配置（接受 DreamConfig 或 PhysioConfig），尽力同步估计器 config。"""
        if config is None:
            return
        physio = config.physio if hasattr(config, "physio") else config
        self._config = self._config.model_copy(update={"physio": physio})
        est = self.estimator
        if est is not None and hasattr(est, "config"):
            try:
                est.config = physio
            except Exception as e:
                logger.warning("估计器配置同步失败（尽力而为，不影响运行）: %s", e)

    # -------------------------------------------------------------- 系统状态
    def update_system_state(self, system_idle_sec: Any = None, user_active: Any = None) -> None:
        """注入 S1/S6 系统静默 provider 输入（前端 POST /physio/state）。

        system_idle_sec 优先；仅 user_active=False 且无 idle 上报时视为满静默。
        """
        sensor = self.sleep_sensor
        if sensor is None or not hasattr(sensor, "set_system_idle"):
            return
        if system_idle_sec is not None:
            idle_sec = float(system_idle_sec)
        elif user_active is False:
            idle_sec = _FULL_IDLE_SEC
        else:
            idle_sec = 0.0
        sensor.set_system_idle(idle_sec)

    # -------------------------------------------------------------- 设备配对
    def get_devices(self) -> list:
        """已配对设备列表（读 dream_config.physio.device_fingerprint）。"""
        physio = self._config.physio
        if not physio.device_fingerprint:
            return []
        return [
            {
                "fingerprint": str(physio.device_fingerprint),
                "device_name": physio.device_name_hint or None,
            }
        ]

    def forget_device(self, fp: str) -> bool:
        """解除配对：指纹不匹配返回 False；匹配则清空并持久化配置。"""
        physio = self._config.physio
        if physio.device_fingerprint != fp:
            return False
        new_physio = physio.model_copy(update={"device_fingerprint": None})
        updated = self._config.model_copy(update={"physio": new_physio})
        self._config = updated
        try:
            save_config(updated)
        except Exception as e:
            logger.warning("解除配对配置持久化失败（尽力而为）: %s", e)
        return True
