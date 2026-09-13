"""头像可用动作清单注册表（spec enhance-emotion-tts-and-action-presets Task 5.1）。

前端头像 manifest 加载完成后，将可用动作名（motions keys）与表情 id 清单
经 ``POST /api/avatar-manifest`` 上报至本注册表缓存；后续提示词装配
（Task 4 范围）按 agent_id 查询注入真实动作名——消除「LLM 猜动作名」。

缓存策略（spec 冻结决策）：
- 进程级内存缓存（dict + threading.Lock），不持久化到 data/；
  服务重启后前端会重新上报，无需落盘恢复。
- 按 agent_id 维度缓存（与 chat.py 的 agent_id 惯例、data/agents.json
  的 agent 概念一致），覆盖式更新（同一 agent 重复上报以最新为准）。
- 未上报查询返回空清单（不报错），提示词侧据此回退为不注入动作清单段落。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 单 agent 动作/表情清单条目上限（防异常超大 payload 撑爆内存；超出截断并告警）
_MAX_ENTRIES = 512


class AvatarManifestRegistry:
    """会话级头像动作清单缓存：按 agent_id 覆盖式 upsert，线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # agent_id -> {"actions": [...], "expressions": [...], "updated_at": iso}
        self._store: Dict[str, Dict[str, object]] = {}

    def upsert(self, agent_id: str, actions: List[str], expressions: Optional[List[str]] = None) -> Dict[str, object]:
        """覆盖式更新该 agent 的动作/表情清单，返回写入后的缓存快照。"""
        acts = [str(a) for a in (actions or [])][:_MAX_ENTRIES]
        exprs = [str(e) for e in (expressions or [])][:_MAX_ENTRIES]
        if len(actions or []) > _MAX_ENTRIES or len(expressions or []) > _MAX_ENTRIES:
            logger.warning(f"agent '{agent_id}' 动作清单超出 {_MAX_ENTRIES} 条上限，已截断")
        snapshot = {
            "actions": acts,
            "expressions": exprs,
            "updated_at": datetime.now().isoformat(),
        }
        with self._lock:
            self._store[agent_id] = snapshot
        logger.info(
            f"头像清单已上报: agent='{agent_id}' actions={len(acts)} expressions={len(exprs)}"
        )
        return dict(snapshot)

    def get(self, agent_id: str) -> Dict[str, object]:
        """查询该 agent 的清单缓存；未上报时返回空清单（安全回退，不抛错）。"""
        with self._lock:
            entry = self._store.get(agent_id)
            if entry is None:
                return {"actions": [], "expressions": [], "updated_at": None}
            return dict(entry)


# 进程级单例（与 face_tool/frame_cache 等内存缓存同口径）
_registry: Optional[AvatarManifestRegistry] = None
_registry_lock = threading.Lock()


def get_avatar_manifest_registry() -> AvatarManifestRegistry:
    """获取进程级注册表单例（懒初始化）。"""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = AvatarManifestRegistry()
    return _registry
