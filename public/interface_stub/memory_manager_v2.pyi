"""MemoryManager V2 接口契约存根。

定义 RADIX-Lite MemoryManager 扩展接口签名。
在原 MemoryManager 基础上新增 write_with_decision 方法，支持 DecisionCore 驱动的智能存储。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

@version 1.0.0
@see public/schema/storage_decision.schema.json
@see public/schema/agent_config_v2.schema.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class WriteWithDecisionResult(BaseModel):
    """write_with_decision 返回结果。"""
    stored: bool
    location: str  # enum: memories / permanent_memories / rejected
    memory_id: Optional[int]
    metadata: Dict[str, Any]
    reason: str


class MemoryManagerV2:
    """MemoryManager V2 接口契约。

    在原 MemoryManager 基础上扩展，新增 write_with_decision 方法。
    原 MemoryManager 方法（write_permanent_memory / search_memories / search_all_memories）
    保持向后兼容，此处仅声明新增方法。
    """

    def write_with_decision(
        self,
        content: str,
        decision: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> WriteWithDecisionResult:
        """根据 DecisionCore 决策写入记忆。

        根据 decision.location 决定写入位置：
        - memories → 写入 memories 表（临时记忆）
        - permanent_memories → 写入 permanent_memories 表（永久记忆）
        - rejected → 写入 rejected_content 表（保留 30 天）

        Args:
            content: 记忆内容
            decision: DecisionCore 决策结果（含 location / quality_score / reason）
            metadata: 记忆元数据（time / importance / source / tags）

        Returns:
            WriteWithDecisionResult: stored + location + memory_id + metadata + reason

        Raises:
            ValueError: decision.location 不在枚举中（422）
            RuntimeError: 数据库写入失败（500）
            IOError: 数据库文件不可访问（500）
        """
        ...

    def get_rejected_content(
        self,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取被拒绝的内容列表。

        用于 GN-004 抽样审查和人类 override_decision。

        Args:
            session_id: 会话 ID 过滤（None=全部）
            limit: 返回上限

        Returns:
            被拒绝内容列表（含 content / quality_score / reason / created_at）

        Raises:
            RuntimeError: 数据库查询失败（500）
        """
        ...

    def cleanup_expired_rejected_content(self, retention_days: int = 30) -> int:
        """清理过期的被拒绝内容。

        Args:
            retention_days: 保留天数（默认 30）

        Returns:
            清理的记录数

        Raises:
            RuntimeError: 数据库删除失败（500）
        """
        ...
