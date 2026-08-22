"""CX-O-Autonomy 安全层——KillSwitch 急停开关。

状态语义（注意与 manager.enabled 的"启用"语义相反）：
- enabled   默认 True 表示"未急停"；emergency_stop() 置 False 后一切行动停止；
- paused    临时暂停自主行动（不解除急停）；
- sleeping  睡眠档标记（睡眠期间不行动）；
- is_active() 为 True 表示当前可正常行动（enabled 且非 paused 且非 sleeping）。

状态以 JSON 持久化到 server/autonomy/data/killswitch.json（store_path 缺省
基于 __file__ 绝对路径解析）。P2-T4 已扩展"离开模式/用户在线休眠策略"：
- update_from_user_online() 按用户在线状态同步休眠档（用户在线→休眠，用户离开
  →离开模式）；
- leave_mode() 判定"离开模式"（sleeping False 且 enabled 且非 paused），其语义
  = 直接授权、不拦截任何操作（由系统提示词 + 既有电脑控制授权承载，本层不新增
  操作级拦截层）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# 默认存储路径：本文件位于 server/autonomy/safety/，parent.parent = server/autonomy
DEFAULT_STORE_PATH = str(Path(__file__).resolve().parent.parent / "data" / "killswitch.json")


class KillSwitch:
    """急停/暂停/睡眠状态开关，支持 JSON 持久化。"""

    def __init__(self, store_path: Optional[str] = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH
        # enabled 默认 True 表示"未急停"
        self.enabled: bool = True
        self.paused: bool = False
        self.sleeping: bool = False

    def emergency_stop(self) -> None:
        """紧急停止：enabled 置 False，任何行动不得继续。"""
        self.enabled = False

    def resume(self) -> None:
        """恢复：解除急停/暂停/睡眠，全部回到可行动状态。"""
        self.enabled = True
        self.paused = False
        self.sleeping = False

    def pause(self) -> None:
        """临时暂停自主行动（不解除急停状态）。"""
        self.paused = True

    def set_sleeping(self, sleeping: bool) -> None:
        """设置/解除睡眠档标记。"""
        self.sleeping = bool(sleeping)

    def update_from_user_online(self, is_online: bool, user_online_sleep: bool) -> None:
        """按用户在线状态同步休眠档（P2-T4 用户在线休眠策略）。

        仅当 user_online_sleep 开启时生效：
        - is_online=True  → set_sleeping(True)：用户在线→休眠，避免"Agent 边聊边
          自发帖"的分裂感；
        - is_online=False → set_sleeping(False)：用户离开→离开模式，自主全授权。
        user_online_sleep=False 时不做任何改动（不干预手动设置的 sleeping 状态）。

        本方法不改动 enabled / paused：急停与暂停优先级高于用户在线策略。
        """
        if not user_online_sleep:
            return
        self.set_sleeping(bool(is_online))

    def is_active(self) -> bool:
        """是否处于可行动状态：enabled 且非 paused 且非 sleeping。"""
        return self.enabled and not self.paused and not self.sleeping

    def leave_mode(self) -> bool:
        """是否处于"离开模式"。

        离开模式 = sleeping 为 False 且 enabled 且非 paused（与 is_active() 同构）。
        其语义为"直接授权、不拦截任何操作"——授权由系统提示词 + 既有电脑控制
        授权承载，本层不新增操作级拦截层。急停优先于离开模式：enabled=False 时
        恒为 False。
        """
        return self.is_active()

    def load(self) -> "KillSwitch":
        """从 store_path 读取持久化状态；文件缺失/损坏时保留默认值。"""
        path = Path(self.store_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.enabled = bool(data.get("enabled", True))
                self.paused = bool(data.get("paused", False))
                self.sleeping = bool(data.get("sleeping", False))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass  # 损坏文件不致命：保留默认值
        return self

    def save(self) -> str:
        """将当前状态持久化为 JSON，返回写入路径。"""
        path = Path(self.store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"enabled": self.enabled, "paused": self.paused, "sleeping": self.sleeping}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(path)
