"""CX-O-Autonomy 安全层——KillSwitch 暂停/睡眠状态开关。

状态语义（两态 + JSON 持久化）：
- paused    临时暂停自主行动（轮级跳过，可 resume 恢复）；
- sleeping  睡眠档标记（睡眠期间不行动，含用户在线休眠策略）；
- is_active() 为 True 表示当前可正常行动（非 paused 且非 sleeping）。

本开关不再提供任何急停语义（历史 enabled 字段已删除，不存在会终止主循环或使
Agent 永久不可行动的状态）。状态以 JSON 持久化到 server/autonomy/data/
killswitch.json（store_path 缺省基于 __file__ 绝对路径解析）；加载遗留档时忽略
历史 enabled 键（旧急停档 {"enabled": false} 不再导致停摆），下次落盘即移除该键。
相关策略：
- update_from_user_online() 按用户在线状态同步休眠档（用户在线→休眠，用户离开
  →离开模式）；
- leave_mode() 与 is_active() 同构（离开模式 = 非暂停且非休眠，不再有急停优先
  语义），其语义 = 直接授权、不拦截任何操作（由系统提示词 + 既有电脑控制授权
  承载，本层不新增操作级拦截层）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from server.autonomy._atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# 默认存储路径：本文件位于 server/autonomy/safety/，parent.parent = server/autonomy
DEFAULT_STORE_PATH = str(Path(__file__).resolve().parent.parent / "data" / "killswitch.json")


class KillSwitch:
    """暂停/睡眠状态开关，支持 JSON 持久化（无急停语义）。"""

    def __init__(self, store_path: Optional[str] = None) -> None:
        self.store_path = store_path or DEFAULT_STORE_PATH
        self.paused: bool = False
        self.sleeping: bool = False

    def resume(self) -> None:
        """恢复：解除暂停与睡眠，回到可行动状态（变更后尽力持久化）。"""
        self.paused = False
        self.sleeping = False
        self._persist()

    def pause(self) -> None:
        """临时暂停自主行动（变更后尽力持久化）。"""
        self.paused = True
        self._persist()

    def set_sleeping(self, sleeping: bool) -> None:
        """设置/解除睡眠档标记。

        状态实际变化时持久化（R4：sleeping 档跨重启保持）；未变化不重复
        落盘（update_from_user_online 每轮调用，避免轮级高频写）。
        """
        new_value = bool(sleeping)
        if new_value == self.sleeping:
            return
        self.sleeping = new_value
        self._persist()

    def _persist(self) -> None:
        """状态变更后尽力持久化到 killswitch.json；失败仅告警不影响内存状态。"""
        try:
            self.save()
        except Exception as e:
            logger.warning("KillSwitch 状态持久化失败: %s", e)

    def update_from_user_online(self, is_online: bool, user_online_sleep: bool) -> None:
        """按用户在线状态同步休眠档（P2-T4 用户在线休眠策略）。

        仅当 user_online_sleep 开启时生效：
        - is_online=True  → set_sleeping(True)：用户在线→休眠，避免"Agent 边聊边
          自发帖"的分裂感；
        - is_online=False → set_sleeping(False)：用户离开→离开模式，自主全授权。
        user_online_sleep=False 时不做任何改动（不干预手动设置的 sleeping 状态）。

        本方法不改动 paused：暂停优先级高于用户在线策略。
        """
        if not user_online_sleep:
            return
        self.set_sleeping(bool(is_online))

    def is_active(self) -> bool:
        """是否处于可行动状态：非 paused 且非 sleeping。"""
        return not self.paused and not self.sleeping

    def leave_mode(self) -> bool:
        """是否处于"离开模式"。

        离开模式 = 非暂停且非休眠（与 is_active() 同构，不再有急停优先语义）。
        其语义为"直接授权、不拦截任何操作"——授权由系统提示词 + 既有电脑控制
        授权承载，本层不新增操作级拦截层。
        """
        return self.is_active()

    def load(self) -> "KillSwitch":
        """从 store_path 读取持久化状态；文件缺失/损坏时保留默认值。

        只读 paused/sleeping；历史遗留的 enabled 键被忽略（旧急停档不得导致停摆）。
        """
        path = Path(self.store_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.paused = bool(data.get("paused", False))
                self.sleeping = bool(data.get("sleeping", False))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass  # 损坏文件不致命：保留默认值
        return self

    def save(self) -> str:
        """将当前状态原子持久化为 JSON，返回写入路径（只写 paused/sleeping）。"""
        path = Path(self.store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"paused": self.paused, "sleeping": self.sleeping}
        atomic_write_json(path, data)
        return str(path)
