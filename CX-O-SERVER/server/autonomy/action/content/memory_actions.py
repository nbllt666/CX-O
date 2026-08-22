"""CX-O-Autonomy 记忆读写行动（P1-T4）。

MemoryActions 封装自主系统主循环对记忆库的读写，直调主服务 memory manager 实例
（即 server.dependencies.get_memory_manager() 返回的 MemoryManager）：

- write_memory    写入一条自主经历，对齐 /api/memories POST 语义（write_memory_async）
- retrieve_memory 检索记忆，对齐 /api/memories/search 语义（search_memories_async）

错误策略（本模块 docstring 中显式声明）：
- 写入失败（memory_manager 未注入或底层抛异常）：不向上冒泡，返回
  {'error': <原因>, 'memory_id': None} 错误结构并记录日志，由调用方记录审计。
- 检索失败：优雅降级返回 [] 并记录日志，不向上冒泡。
- content 为空属参数错误，直接抛 ValueError（对齐 /memories 语义）。
"""

from typing import Any, Dict, List, Optional, Union

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 成功返回 memory_id（str）；失败返回 {'error': ..., 'memory_id': None} 错误结构
WriteMemoryResult = Union[str, Dict[str, Any]]


class MemoryActions:
    """自主系统记忆读写行动。

    注入主服务 memory manager 实例；agent_id 默认取配置值（AutonomyConfig.agent_id）或
    "default"，workspace_id 固定为 "default"，与 /memories 端点语义对齐。
    """

    def __init__(self, memory_manager: Any = None, agent_id: str = "default") -> None:
        """初始化记忆行动。

        Args:
            memory_manager: 主服务 memory manager 实例（须提供 write_memory_async 与
                search_memories_async）；可为 None，此时写入/检索优雅降级，不抛异常。
            agent_id: 记忆归属的 Agent ID（对齐 AutonomyConfig.agent_id），默认 "default"。
        """
        self.memory_manager = memory_manager
        self.agent_id = agent_id or "default"
        self.workspace_id = "default"

    async def write_memory(
        self,
        content: str,
        tags: Optional[List[str]] = None,
        type: str = "long_term",
        permanent: bool = False,
        importance: int = 3,
        metadata: Optional[dict] = None,
    ) -> WriteMemoryResult:
        """写入一条自主经历到记忆库（直调 memory_manager.write_memory_async）。

        对齐 /api/memories POST 语义：content 必填、type 默认 long_term、permanent 透传、
        importance / tags / metadata 透传、agent_id 取配置值或 "default"、workspace_id "default"。

        Args:
            content: 记忆内容（必填；空白抛 ValueError）
            tags: 标签列表
            type: 记忆类型，默认 long_term
            permanent: 是否永久记忆
            importance: 重要性等级（1-5）
            metadata: 附加元数据

        Returns:
            成功返回 memory_id（str）；失败返回 {'error': <原因>, 'memory_id': None}
            错误结构（不向上冒泡，由调用方记录审计）。

        Raises:
            ValueError: content 为空时抛出（参数错误，不进入失败降级路径）。
        """
        if not content or not content.strip():
            raise ValueError("记忆内容不能为空")

        if self.memory_manager is None:
            logger.error("memory_manager 未注入，无法写入记忆")
            return {"error": "memory_manager 未注入，无法写入记忆", "memory_id": None}

        try:
            memory_id = await self.memory_manager.write_memory_async(
                content=content,
                memory_type=type,
                importance=importance,
                tags=tags or [],
                metadata=metadata or {},
                permanent=permanent,
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
            )
        except Exception as e:
            logger.error(f"写入记忆失败: {e}", exc_info=True)
            return {"error": str(e), "memory_id": None}

        logger.info(f"写入记忆成功: memory_id={memory_id}, type={type}")
        return str(memory_id)

    async def retrieve_memory(
        self,
        query: str,
        limit: int = 5,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """检索记忆（直调 memory_manager.search_memories_async）。

        对齐 /api/memories/search 语义：query 关键词、tags 标签筛选、limit 数量限制、
        agent_id 取配置值或 "default"、workspace_id "default"。

        Args:
            query: 检索关键词
            limit: 返回数量限制
            tags: 标签筛选（None 表示不过滤）

        Returns:
            记忆列表，每条含 content / type / tags / importance / created_at 等字段
            （底层 memory_type 统一归一化为 type）。失败时优雅降级返回 [] 并记录日志，
            不向上冒泡。
        """
        if self.memory_manager is None:
            logger.error("memory_manager 未注入，无法检索记忆")
            return []

        try:
            memories = await self.memory_manager.search_memories_async(
                query=query,
                tags=tags,
                limit=limit,
                workspace_id=self.workspace_id,
                agent_id=self.agent_id,
            )
        except Exception as e:
            logger.error(f"检索记忆失败: {e}", exc_info=True)
            return []

        return [self._normalize_memory(m) for m in memories]

    @staticmethod
    def _normalize_memory(item: Dict[str, Any]) -> Dict[str, Any]:
        """归一化记忆字段：底层字段名为 memory_type，对外统一补充 type 字段。"""
        normalized = dict(item)
        if "type" not in normalized and "memory_type" in normalized:
            normalized["type"] = normalized["memory_type"]
        return normalized
