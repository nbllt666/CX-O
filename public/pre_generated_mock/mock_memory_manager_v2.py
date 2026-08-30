"""MemoryManager V2 预生成 Mock 实现。

对应接口契约: public/interface_stub/memory_manager_v2.pyi
对应数据契约: public/schema/storage_decision.schema.json
对应配置契约: public/config_template/radix_config.json
对应 Agent 契约: public/schema/agent_config_v2.schema.json

Mock 策略:
- 返回符合 schema 的固定样例数据
- 内存态维护 memories / permanent_memories / rejected_content 三张表
- write_with_decision 根据 decision.location 分发写入
- 异常路径通过 raise 模拟（ValueError=422 / RuntimeError=500）
- 真实实现就位后，切换导入路径即可替换

@version 1.3.0  # 第十三轮 G2 契约对齐：write_with_decision 改 4 参签名（+source），返回 Dict{location, memory_id, rejected_id}（对齐 pyi @1.1.0 与 decision_mixin.py 三分支）；移除无引用的 WriteWithDecisionResult 模型；get_rejected_content 改 created_at 降序（对齐实现 ORDER BY created_at DESC）；rejected 分支改以 rejected_id UUID 为键，不再空耗主库序号
@see public/interface_stub/memory_manager_v2.pyi
@see public/schema/storage_decision.schema.json
@see public/schema/agent_config_v2.schema.json

CX-O 迁移版，基于 CXHMS v1.2.0 Mock 适配。
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    """生成 UUID v4 字符串（rejected 分支的 rejected_id）。"""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# 枚举常量（与 storage_decision.schema.json 一致）
# --------------------------------------------------------------------------- #

_LOCATIONS = {"memories", "permanent_memories", "rejected"}

# 默认保留天数（与 agent_config_v2.schema.json decision_rubric.rejected_content_retention_days 一致）
_DEFAULT_RETENTION_DAYS = 30


class MockMemoryManagerV2:
    """MemoryManager V2 的 Mock 实现。

    在原 MemoryManager 基础上扩展，新增 write_with_decision 方法。
    返回值通过 storage_decision.schema.json 校验（location/memory_id/rejected_id 键）。
    """

    def __init__(self) -> None:
        # 三张内存态表
        self._memories: Dict[int, Dict[str, Any]] = {}
        self._permanent_memories: Dict[int, Dict[str, Any]] = {}
        self._rejected_content: Dict[str, Dict[str, Any]] = {}
        # 自增 ID（memories / permanent_memories 共用序列；rejected 以 UUID 为键，不消耗序号）
        self._seq: int = 1

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    def write_with_decision(
        self,
        content: str,
        decision: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据 DecisionCore 决策写入记忆。

        Mock behavior: 根据 decision['location'] 分发写入对应表
        （对齐 decision_mixin.py L102-176 的三个返回分支）。
        - memories → 写入 _memories（source 缺省 'user'）
        - permanent_memories → 写入 _permanent_memories（source 缺省 'radix_decision'）
        - rejected → 写入 _rejected_content（含 created_at 用于过期清理）

        Returns:
            Dict[str, Any]（对齐 pyi @1.1.0）：
            - memories/permanent_memories 分支：memory_id 为分配 ID，rejected_id=None
            - rejected 分支：memory_id=None，rejected_id 为 UUID 字符串
        """
        if not content:
            raise ValueError("content 不能为空（422）")
        location = decision.get("location")
        if location not in _LOCATIONS:
            raise ValueError(
                f"decision.location 不在枚举中（422）: {location}"
            )

        now = _iso_now()

        if location == "memories":
            memory_id = self._alloc_id()
            self._memories[memory_id] = {
                "memory_id": memory_id,
                "content": content,
                "decision": dict(decision),
                "metadata": dict(metadata or {}),
                "source": source or "user",
                "created_at": now,
            }
            return {
                "location": "memories",
                "memory_id": memory_id,
                "rejected_id": None,
            }

        if location == "permanent_memories":
            memory_id = self._alloc_id()
            self._permanent_memories[memory_id] = {
                "memory_id": memory_id,
                "content": content,
                "decision": dict(decision),
                "metadata": dict(metadata or {}),
                "source": source or "radix_decision",
                "created_at": now,
            }
            return {
                "location": "permanent_memories",
                "memory_id": memory_id,
                "rejected_id": None,
            }

        # location == "rejected" → 以 rejected_id UUID 为表键
        # （不消耗主库序号；与 schema 一致：location=rejected 时 memory_id=null）
        rejected_id = _new_uuid()
        self._rejected_content[rejected_id] = {
            "memory_id": None,
            "content": content,
            "decision": dict(decision),
            "metadata": dict(metadata or {}),
            "created_at": now,
        }
        return {
            "location": "rejected",
            "memory_id": None,
            "rejected_id": rejected_id,
        }

    def get_rejected_content(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询指定会话的被拒绝内容（签名对齐实现：session_id 必填、limit 默认 50）。

        Mock behavior: 返回 rejected_content 表记录，按 session_id 过滤；
        空 session_id 抛 KeyError（对齐实现 404）；limit<=0 回退为 50（对齐实现）。
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")
        if limit <= 0:
            limit = 50

        results: List[Dict[str, Any]] = []
        for record in self._rejected_content.values():
            rec_session = record.get("decision", {}).get("session_id")
            if rec_session != session_id:
                continue
            results.append({
                "content": record["content"],
                "quality_score": record.get("decision", {}).get("quality_score"),
                "reason": record.get("decision", {}).get("reason"),
                "created_at": record["created_at"],
            })
        # 按 created_at 降序（对齐 pyi @1.1.0 与实现 decision_mixin.py ORDER BY created_at DESC）
        results.sort(key=lambda r: r["created_at"], reverse=True)
        return results[:limit]

    def cleanup_expired_rejected_content(self, retention_days: int = 30) -> int:
        """清理过期的被拒绝内容。

        Mock behavior: 删除 created_at 超过 retention_days 天的记录，返回清理数量。
        """
        if retention_days < 1:
            raise ValueError(
                f"retention_days 必须 >= 1（422）: {retention_days}"
            )

        now = datetime.now(timezone.utc)
        threshold = now - timedelta(days=retention_days)
        expired_ids: List[str] = []

        for mid, record in self._rejected_content.items():
            created_str = record.get("created_at")
            if not created_str:
                continue
            try:
                created = datetime.fromisoformat(created_str)
            except ValueError:
                continue
            if created < threshold:
                expired_ids.append(mid)

        for mid in expired_ids:
            del self._rejected_content[mid]

        return len(expired_ids)

    # ------------------------------------------------------------------ #
    # 私有辅助
    # ------------------------------------------------------------------ #

    def _alloc_id(self) -> int:
        """分配自增 memory_id。"""
        mid = self._seq
        self._seq += 1
        return mid

    # ------------------------------------------------------------------ #
    # 测试辅助（非契约方法，仅供 Mock 验证使用）
    # ------------------------------------------------------------------ #

    def _seed_rejected_for_demo(self, session_id: str, days_ago: int = 45) -> None:
        """预置一条过期的 rejected 记录，用于演示 cleanup。

        非契约方法，仅供 Mock 自检/测试使用。
        """
        rid = _new_uuid()
        expired_time = (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).isoformat()
        self._rejected_content[rid] = {
            "memory_id": None,
            "content": f"[Mock] 过期 rejected 记录（{days_ago} 天前）",
            "decision": {
                "location": "rejected",
                "quality_score": 0.2,
                "reason": "[Mock] 低质量，已过期",
                "session_id": session_id,
            },
            "metadata": {},
            "created_at": expired_time,
        }
