"""内存版 MemoryManager mock（CX-O-SERVER 测试基础设施 Phase 1）。

提供 ``InMemoryMemoryStore`` —— 一个不依赖外部存储（SQLite / 向量库）的记忆管理器替身。
方法签名与返回结构对齐 ``server/core/memory/manager.py`` 的 MemoryManager（经 8 个 mixin 提供），
返回的记忆字典结构对齐 ``crud_mixin._row_to_memory``。

适用场景：
- 后续批次补测中需要 MemoryManager 依赖但不想拉起真实数据库
- 作为 ``unittest.mock.Mock`` 的结构化替代，提供可预测的内存行为

注意：当前 ``public/schema/memory.schema.json`` 处于种子阶段（无完整字段定义），
本 mock 的字段结构以 server 真实实现为准，待 s0201 补全 schema 后可叠加契约校验。
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    """返回当前 ISO 时间戳。"""
    return datetime.now().isoformat()


class InMemoryMemoryStore:
    """内存版记忆存储，模拟 MemoryManager 的核心 CRUD 行为。

    线程安全（内部加锁）。所有数据仅存于内存，实例销毁即丢失。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: Dict[int, Dict[str, Any]] = {}
        self._next_id = 1

    # ------------------------------------------------------------------
    # write_memory —— 写入记忆，返回记忆 ID
    # ------------------------------------------------------------------
    def write_memory(
        self,
        content: str,
        memory_type: str = "long_term",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        permanent: bool = False,
        emotion_score: float = 0.0,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> int:
        """写入一条记忆，返回记忆 ID。

        参数与 ``crud_mixin._MemoryCRUDMixin.write_memory`` 对齐。
        """
        with self._lock:
            memory_id = self._next_id
            self._next_id += 1
            now = _now_iso()
            record = {
                "id": memory_id,
                "type": memory_type,
                "content": content,
                "vector_id": None,
                "metadata": metadata or {},
                "importance": importance,
                "importance_score": 1.0 if permanent else 0.6,
                "decay_type": "zero" if permanent else "exponential",
                "decay_params": {},
                "reactivation_count": 0,
                "emotion_score": emotion_score,
                "permanent": permanent,
                "psychological_age": 1.0,
                "tags": tags or [],
                "created_at": now,
                "updated_at": now,
                "archived_at": None,
                "is_deleted": False,
                "source": "mock",
                "workspace_id": workspace_id,
                "agent_id": agent_id,
            }
            self._store[memory_id] = record
            return memory_id

    # ------------------------------------------------------------------
    # get_memory —— 获取记忆
    # ------------------------------------------------------------------
    def get_memory(self, memory_id: int, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
        """获取记忆，不存在返回 None。"""
        with self._lock:
            record = self._store.get(memory_id)
            if record is None:
                return None
            if record.get("is_deleted") and not include_deleted:
                return None
            return dict(record)

    # ------------------------------------------------------------------
    # search_memories —— 搜索记忆
    # ------------------------------------------------------------------
    def search_memories(
        self,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
        include_deleted: bool = False,
        agent_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """搜索记忆（简易子串 + 字段过滤）。

        注意：真实实现使用向量+关键词混合搜索，本 mock 仅做子串匹配，不计算相关性分数。
        """
        with self._lock:
            results: List[Dict[str, Any]] = []
            for record in self._store.values():
                if record.get("is_deleted") and not include_deleted:
                    continue
                if record.get("agent_id") != agent_id:
                    continue
                if memory_type is not None and record.get("type") != memory_type:
                    continue
                if query is not None and query.lower() not in str(record.get("content", "")).lower():
                    continue
                if tags:
                    record_tags = set(record.get("tags") or [])
                    if not set(tags).issubset(record_tags):
                        continue
                results.append(dict(record))
            results = results[offset : offset + limit]
            return results

    # ------------------------------------------------------------------
    # update_memory —— 更新记忆
    # ------------------------------------------------------------------
    def update_memory(
        self,
        memory_id: int,
        new_content: str = None,
        new_tags: List[str] = None,
        new_importance: int = None,
        new_metadata: Dict[str, Any] = None,
        agent_id: str = "default",
    ) -> bool:
        """更新记忆，返回是否成功。"""
        with self._lock:
            record = self._store.get(memory_id)
            if record is None or record.get("is_deleted"):
                return False
            if new_content is not None:
                record["content"] = new_content
            if new_tags is not None:
                record["tags"] = new_tags
            if new_importance is not None:
                record["importance"] = new_importance
            if new_metadata is not None:
                record["metadata"] = new_metadata
            record["updated_at"] = _now_iso()
            return True

    # ------------------------------------------------------------------
    # delete_memory —— 删除记忆
    # ------------------------------------------------------------------
    def delete_memory(
        self, memory_id: int, soft_delete: bool = True, agent_id: str = "default"
    ) -> bool:
        """删除记忆，返回是否成功。"""
        with self._lock:
            record = self._store.get(memory_id)
            if record is None:
                return False
            if soft_delete:
                record["is_deleted"] = True
                record["updated_at"] = _now_iso()
            else:
                del self._store[memory_id]
            return True

    # ------------------------------------------------------------------
    # restore_memory —— 恢复软删除记忆
    # ------------------------------------------------------------------
    def restore_memory(self, memory_id: int, agent_id: str = "default") -> bool:
        """恢复软删除的记忆。"""
        with self._lock:
            record = self._store.get(memory_id)
            if record is None:
                return False
            record["is_deleted"] = False
            record["updated_at"] = _now_iso()
            return True

    # ------------------------------------------------------------------
    # get_statistics —— 统计信息
    # ------------------------------------------------------------------
    def get_statistics(self, workspace_id: str = "default") -> Dict[str, Any]:
        """返回记忆统计信息。"""
        with self._lock:
            total = 0
            deleted = 0
            permanent = 0
            for record in self._store.values():
                if record.get("workspace_id") != workspace_id:
                    continue
                total += 1
                if record.get("is_deleted"):
                    deleted += 1
                if record.get("permanent"):
                    permanent += 1
            return {
                "total_memories": total,
                "deleted_memories": deleted,
                "permanent_memories": permanent,
                "active_memories": total - deleted,
            }

    # ------------------------------------------------------------------
    # 辅助：清空全部记忆（测试间隔离）
    # ------------------------------------------------------------------
    def clear(self) -> None:
        """清空全部记忆（仅用于测试隔离）。"""
        with self._lock:
            self._store.clear()
            self._next_id = 1

    # ------------------------------------------------------------------
    # 辅助：直接注入一条记忆（测试种子数据）
    # ------------------------------------------------------------------
    def seed(self, record: Dict[str, Any]) -> int:
        """直接注入一条记忆记录，返回其 ID。

        若未提供 id，则自动分配。用于测试预置数据。
        """
        with self._lock:
            memory_id = record.get("id")
            if memory_id is None:
                memory_id = self._next_id
                self._next_id += 1
                record["id"] = memory_id
            else:
                if memory_id >= self._next_id:
                    self._next_id = memory_id + 1
            record.setdefault("created_at", _now_iso())
            record.setdefault("updated_at", _now_iso())
            record.setdefault("is_deleted", False)
            self._store[memory_id] = dict(record)
            return memory_id


def create_mock_memory_store() -> InMemoryMemoryStore:
    """工厂：创建一个空的内存版记忆存储实例。"""
    return InMemoryMemoryStore()


def create_mock_memory_store_with_seed(records: List[Dict[str, Any]]) -> InMemoryMemoryStore:
    """工厂：创建并预置多条记忆的内存版记忆存储实例。"""
    store = InMemoryMemoryStore()
    for record in records:
        store.seed(record)
    return store
