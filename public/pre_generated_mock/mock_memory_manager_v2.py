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

@version 1.2.0  # G4-B 签名同步：get_rejected_content 对齐实现（session_id 必填、limit 默认 50、空 session_id 抛 KeyError）
@see public/interface_stub/memory_manager_v2.pyi
@see public/schema/storage_decision.schema.json
@see public/schema/agent_config_v2.schema.json

CX-O 迁移版，基于 CXHMS v1.2.0 Mock 适配。
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Pydantic 模型（与 .pyi 存根保持一致，Mock 自包含）
# --------------------------------------------------------------------------- #


class WriteWithDecisionResult(BaseModel):
    """write_with_decision 返回结果。"""
    stored: bool
    location: str  # enum: memories / permanent_memories / rejected
    memory_id: Optional[int]
    metadata: Dict[str, Any]
    reason: str


# --------------------------------------------------------------------------- #
# 枚举常量（与 storage_decision.schema.json 一致）
# --------------------------------------------------------------------------- #

_LOCATIONS = {"memories", "permanent_memories", "rejected"}

# 默认保留天数（与 agent_config_v2.schema.json decision_rubric.rejected_content_retention_days 一致）
_DEFAULT_RETENTION_DAYS = 30


class MockMemoryManagerV2:
    """MemoryManager V2 的 Mock 实现。

    在原 MemoryManager 基础上扩展，新增 write_with_decision 方法。
    返回值通过 storage_decision.schema.json 校验（location/memory_id 字段）。
    """

    def __init__(self) -> None:
        # 三张内存态表
        self._memories: Dict[int, Dict[str, Any]] = {}
        self._permanent_memories: Dict[int, Dict[str, Any]] = {}
        self._rejected_content: Dict[int, Dict[str, Any]] = {}
        # 自增 ID（三表共享序列，保证 memory_id 唯一）
        self._seq: int = 1

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    def write_with_decision(
        self,
        content: str,
        decision: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> WriteWithDecisionResult:
        """根据 DecisionCore 决策写入记忆。

        Mock behavior: 根据 decision['location'] 分发写入对应表。
        - memories → 写入 _memories
        - permanent_memories → 写入 _permanent_memories
        - rejected → 写入 _rejected_content（含 created_at 用于过期清理）
        """
        if not content:
            raise ValueError("content 不能为空（422）")
        location = decision.get("location")
        if location not in _LOCATIONS:
            raise ValueError(
                f"decision.location 不在枚举中（422）: {location}"
            )

        memory_id = self._alloc_id()
        now = _iso_now()
        record = {
            "memory_id": memory_id,
            "content": content,
            "decision": dict(decision),
            "metadata": dict(metadata),
            "created_at": now,
        }

        stored = True
        reason = decision.get("reason") or f"[Mock] 写入 {location}"

        if location == "memories":
            self._memories[memory_id] = record
        elif location == "permanent_memories":
            self._permanent_memories[memory_id] = record
        else:  # rejected
            # rejected 不分配 memory_id（与 schema 一致：location=rejected 时 memory_id=null）
            record["memory_id"] = None
            # 重新分配的 ID 放回序列池不回收，但 rejected 表用独立 key
            self._rejected_content[memory_id] = record
            stored = False  # rejected 视为未存储到 memories/permanent_memories
            memory_id = None

        return WriteWithDecisionResult(
            stored=stored,
            location=location,
            memory_id=memory_id,
            metadata=dict(metadata),
            reason=reason,
        )

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
        # 按 created_at 升序（rules-0 §三 sorting.order: ascending）
        results.sort(key=lambda r: r["created_at"])
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
        expired_ids: List[int] = []

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
        mid = self._alloc_id()
        expired_time = (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).isoformat()
        self._rejected_content[mid] = {
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
