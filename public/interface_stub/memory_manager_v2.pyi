"""MemoryManager V2 接口契约存根。

定义 RADIX-Lite MemoryManager 扩展接口签名。
在原 MemoryManager 基础上新增 write_with_decision 方法，支持 DecisionCore 驱动的智能存储。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

@version 1.1.0  # G2 契约修订（MINOR）：write_with_decision 签名对齐实现（4 参：content/decision/metadata/source，decision: Any，返回 Dict 含 location/memory_id/rejected_id）；移除无引用的 WriteWithDecisionResult 模型
@see public/schema/storage_decision.schema.json
@see public/schema/agent_config_v2.schema.json
"""

from typing import Any, Dict, List, Optional


class MemoryManagerV2:
    """MemoryManager V2 接口契约。

    在原 MemoryManager 基础上扩展，新增 write_with_decision 方法。
    原 MemoryManager 方法（write_permanent_memory / search_memories / search_all_memories）
    保持向后兼容，此处仅声明新增方法。
    """

    def write_with_decision(
        self,
        content: str,
        decision: Any,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按 decision.location 决定写入主库或 rejected_content 表。

        - location=memories → write_memory（临时记忆）
        - location=permanent_memories → write_permanent_memory（永久记忆）
        - location=rejected → 写入 rejected_content 表（保留 retention_days 天）

        Args:
            content: 记忆/被拒绝内容
            decision: StorageDecision 对象或 dict（含 location/quality_score/reason/
                      metadata/decision_point/llm_confidence 等字段）
            metadata: 附加元数据（写入主库时合并到记忆 metadata；写入 rejected 时
                      合并到 rejected_content.metadata）
            source: 来源标记透传（'vision'/'user' 等）。memories 分支默认 'user'；
                    permanent_memories 分支缺省维持 'radix_decision'。

        Returns:
            Dict[str, Any]: 含以下键——
                location: str（memories / permanent_memories / rejected）
                memory_id: Optional[int]（主库分支的记忆 ID，rejected 分支为 None）
                rejected_id: Optional[str]（rejected 分支的记录 UUID，主库分支为 None）

        Raises:
            ValueError: decision.location 不在枚举中（422）
            RuntimeError: 数据库写入失败（500）
        """
        ...

    def get_rejected_content(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询指定会话的被拒绝内容。

        用于 GN-004 抽样审查和人类 override_decision。

        Args:
            session_id: 会话 ID（必填）
            limit: 返回条数上限（默认 50；<=0 时实现回退为 50）

        Returns:
            被拒绝内容记录列表（按 created_at 降序，不含已清理记录）

        Raises:
            KeyError: session_id 为空（404）
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
