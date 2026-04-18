"""
高级归档管理器
实现归档的归档、智能合并、压缩等功能
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class ArchiveLevel:
    """归档层级"""

    level: int
    name: str
    description: str
    compression_ratio: float  # 压缩率
    max_age_days: int  # 最大保留天数


@dataclass
class ArchiveRecord:
    """归档记录"""

    archive_id: int
    original_memory_id: int
    archive_level: int
    compressed_content: str
    original_content: str
    compression_metadata: Dict[str, Any]
    archived_at: str = field(default_factory=lambda: datetime.now().isoformat())
    restored_at: Optional[str] = None
    access_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "archive_id": self.archive_id,
            "original_memory_id": self.original_memory_id,
            "archive_level": self.archive_level,
            "compressed_content": self.compressed_content,
            "original_content": self.original_content,
            "compression_metadata": self.compression_metadata,
            "archived_at": self.archived_at,
            "restored_at": self.restored_at,
            "access_count": self.access_count,
        }


@dataclass
class MergeResult:
    """合并结果"""

    success: bool
    merged_memory_id: Optional[int] = None
    merged_from: List[int] = field(default_factory=list)
    merged_content: str = ""
    merge_metadata: Dict[str, Any] = field(default_factory=dict)
    message: str = ""


class AdvancedArchiver:
    """高级归档管理器"""

    # 预定义的归档层级
    ARCHIVE_LEVELS = {
        0: ArchiveLevel(0, "活跃", "正常活跃的记忆", 1.0, 365),
        1: ArchiveLevel(1, "一级归档", "轻度压缩，保留主要信息", 0.7, 730),
        2: ArchiveLevel(2, "二级归档", "中度压缩，摘要形式", 0.4, 1095),
        3: ArchiveLevel(3, "三级归档", "高度压缩，仅保留要点", 0.2, 1825),
        4: ArchiveLevel(4, "深度归档", "归档的归档，元数据形式", 0.1, 3650),
    }

    def __init__(self, memory_manager, llm_client=None):
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        self._init_archive_db()

    def _init_archive_db(self):
        """初始化归档数据库表"""
        conn = None
        try:
            conn = self.memory_manager._get_connection()
            if not conn:
                logger.error("无法获取数据库连接")
                return

            cursor = conn.cursor()

            # 归档记录表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_memory_id INTEGER NOT NULL,
                    archive_level INTEGER DEFAULT 1,
                    compressed_content TEXT NOT NULL,
                    original_content TEXT NOT NULL,
                    compression_metadata TEXT,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    restored_at TIMESTAMP,
                    access_count INTEGER DEFAULT 0,
                    FOREIGN KEY (original_memory_id) REFERENCES memories(id)
                )
            """
            )

            # 记忆合并记录表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS merge_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merged_memory_id INTEGER NOT NULL,
                    merged_from TEXT NOT NULL,
                    merged_content TEXT NOT NULL,
                    merge_metadata TEXT,
                    merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (merged_memory_id) REFERENCES memories(id)
                )
            """
            )

            # 相似性记录表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS similarity_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id_1 INTEGER NOT NULL,
                    memory_id_2 INTEGER NOT NULL,
                    similarity_score REAL NOT NULL,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_duplicate BOOLEAN DEFAULT FALSE,
                    UNIQUE(memory_id_1, memory_id_2)
                )
            """
            )

            # 创建索引
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_archive_memory_id 
                ON archive_records(original_memory_id)
            """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_similarity_pair 
                ON similarity_records(memory_id_1, memory_id_2)
            """
            )

            conn.commit()
            logger.info("归档数据库表初始化完成")

        except Exception as e:
            logger.error(f"初始化归档数据库失败: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    async def archive_memory(
        self, memory_id: int, target_level: int = 1, compress: bool = True
    ) -> Optional[ArchiveRecord]:
        """归档单个记忆"""
        try:
            # 获取原记忆
            memory = self.memory_manager.get_memory(memory_id)
            if not memory:
                logger.warning(f"记忆不存在: {memory_id}")
                return None

            original_content = memory.get("content", "")

            # 压缩内容
            if compress and self.llm_client:
                compressed_content = await self._compress_content(original_content, target_level)
            else:
                compressed_content = original_content

            # 计算压缩率
            compression_ratio = (
                len(compressed_content) / len(original_content) if original_content else 1.0
            )

            # 保存归档记录
            conn = None
            try:
                conn = self.memory_manager._get_connection()
                if not conn:
                    logger.error("无法获取数据库连接")
                    return None

                cursor = conn.cursor()

                compression_metadata = {
                    "original_length": len(original_content),
                    "compressed_length": len(compressed_content),
                    "compression_ratio": compression_ratio,
                    "target_level": target_level,
                }

                cursor.execute(
                    """
                    INSERT INTO archive_records 
                    (original_memory_id, archive_level, compressed_content, original_content, compression_metadata)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        memory_id,
                        target_level,
                        compressed_content,
                        original_content,
                        json.dumps(compression_metadata),
                    ),
                )

                archive_id = cursor.lastrowid

                # 更新记忆状态为已归档
                cursor.execute(
                    """
                    UPDATE memories 
                    SET is_archived = TRUE, archive_level = ?
                    WHERE id = ?
                """,
                    (target_level, memory_id),
                )

                conn.commit()

                logger.info(f"记忆已归档: {memory_id} -> 级别 {target_level}")

                return ArchiveRecord(
                    archive_id=archive_id,
                    original_memory_id=memory_id,
                    archive_level=target_level,
                    compressed_content=compressed_content,
                    original_content=original_content,
                    compression_metadata=compression_metadata,
                )
            except Exception as e:
                if conn:
                    conn.rollback()
                raise
            finally:
                if conn:
                    conn.close()

        except Exception as e:
            logger.error(f"归档记忆失败: {e}")
            return None

    async def _compress_content(self, content: str, level: int) -> str:
        """使用 LLM 压缩内容"""
        if not self.llm_client:
            return content

        try:
            level_config = self.ARCHIVE_LEVELS.get(level, self.ARCHIVE_LEVELS[1])

            prompt = f"""请将以下内容进行压缩归档，压缩级别：{level_config.name}（{level_config.description}）

原始内容：
{content}

要求：
- 保留核心信息和关键要点
- 去除冗余描述和细节
- 压缩率目标：{level_config.compression_ratio * 100:.0f}%
- 使用简洁的语言

请直接输出压缩后的内容："""

            # 使用 chat 方法而不是 generate 方法
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}], stream=False
            )

            # 处理 LLMResponse 对象
            if hasattr(response, "content"):
                compressed = response.content.strip()
            elif isinstance(response, dict):
                compressed = response.get("content", content).strip()
            else:
                compressed = str(response).strip()

            return compressed if compressed else content

        except Exception as e:
            logger.error(f"压缩内容失败: {e}", exc_info=True)
            return content

    async def merge_duplicate_memories(
        self, memory_ids: List[int], strategy: str = "smart"
    ) -> MergeResult:
        """合并重复记忆"""
        if len(memory_ids) < 2:
            return MergeResult(success=False, message="至少需要两个记忆才能合并")

        try:
            # 获取所有记忆内容
            memories = []
            for mid in memory_ids:
                memory = self.memory_manager.get_memory(mid)
                if memory:
                    memories.append(memory)

            if len(memories) < 2:
                return MergeResult(success=False, message="无法获取足够的记忆")

            # 按创建时间排序，最早的作为主记忆
            memories.sort(key=lambda x: x.get("created_at", ""))
            primary_memory = memories[0]
            primary_id = primary_memory["id"]

            # 合并内容
            if strategy == "smart" and self.llm_client:
                merged_content = await self._smart_merge_content(memories)
            else:
                # 简单合并：保留最早的内容，合并标签
                merged_content = primary_memory.get("content", "")

            # 合并标签
            all_tags = set()
            for m in memories:
                all_tags.update(m.get("tags", []))

            # 合并元数据
            merge_metadata = {
                "merged_from": memory_ids,
                "merge_strategy": strategy,
                "merged_at": datetime.now().isoformat(),
                "memory_count": len(memories),
            }

            # 更新主记忆
            self.memory_manager.update_memory(
                memory_id=primary_id,
                new_content=merged_content,
                new_tags=list(all_tags),
                new_metadata={
                    **primary_memory.get("metadata", {}),
                    "merged_from": memory_ids,
                    "is_merged": True,
                },
            )

            # 标记其他记忆为已合并
            conn = self.memory_manager._get_connection()
            cursor = conn.cursor()

            for memory in memories[1:]:
                # 在Python中处理metadata更新，避免依赖SQLite JSON1扩展
                new_metadata = {**(memory.get("metadata") or {}), "merged_into": primary_id}
                cursor.execute(
                    """
                    UPDATE memories 
                    SET is_deleted = TRUE, 
                        metadata = ?
                    WHERE id = ?
                """,
                    (json.dumps(new_metadata), memory["id"]),
                )

                # 记录合并关系
                cursor.execute(
                    """
                    INSERT INTO merge_records 
                    (merged_memory_id, merged_from, merged_content, merge_metadata)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        primary_id,
                        json.dumps(memory_ids),
                        merged_content,
                        json.dumps(merge_metadata),
                    ),
                )

            conn.commit()

            logger.info(f"记忆已合并: {memory_ids} -> {primary_id}")

            return MergeResult(
                success=True,
                merged_memory_id=primary_id,
                merged_from=memory_ids,
                merged_content=merged_content,
                merge_metadata=merge_metadata,
                message=f"成功合并 {len(memory_ids)} 个记忆",
            )

        except Exception as e:
            logger.error(f"合并记忆失败: {e}")
            return MergeResult(success=False, message=str(e))

    async def _smart_merge_content(self, memories: List[Dict]) -> str:
        """智能合并记忆内容"""
        if not self.llm_client:
            # 返回最早的记忆内容
            return memories[0].get("content", "") if memories else ""

        try:
            # 构建合并提示
            contents = []
            for i, m in enumerate(memories):
                contents.append(f"记忆 {i+1}:\n{m.get('content', '')}")

            all_content = "\n\n---\n\n".join(contents)

            prompt = f"""请将以下相似的记忆内容合并为一个连贯的摘要。

{all_content}

要求：
- 保留所有重要信息，避免遗漏
- 去除重复内容
- 保持时间顺序和逻辑连贯
- 使用第三人称客观描述
- 长度适中，不要过度压缩

请直接输出合并后的内容："""

            # 使用 chat 方法而不是 generate 方法
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}], stream=False
            )

            # 处理 LLMResponse 对象
            if hasattr(response, "content"):
                merged = response.content.strip()
            elif isinstance(response, dict):
                merged = response.get("content", "").strip()
            else:
                merged = str(response).strip()

            return merged if merged else memories[0].get("content", "")

        except Exception as e:
            logger.error(f"智能合并失败: {e}", exc_info=True)
            return memories[0].get("content", "") if memories else ""

    async def archive_of_archives(self, archive_level: int = 4):
        """归档的归档 - 对已有归档进行二次压缩"""
        try:
            conn = self.memory_manager._get_connection()
            cursor = conn.cursor()

            # 获取指定层级的归档记录
            cursor.execute(
                """
                SELECT * FROM archive_records 
                WHERE archive_level = ?
                ORDER BY archived_at DESC
            """,
                (archive_level - 1,),
            )

            archives = cursor.fetchall()

            if not archives:
                logger.info(f"没有需要二次归档的级别 {archive_level - 1} 记录")
                return []

            results = []

            for archive in archives:
                archive_id = archive[0]
                original_id = archive[1]
                current_level = archive[2]
                current_content = archive[3]
                original_content = archive[4]

                # 进一步压缩
                if self.llm_client:
                    further_compressed = await self._compress_content(
                        current_content, archive_level
                    )
                else:
                    further_compressed = current_content

                # 保存新的归档记录
                compression_metadata = {
                    "previous_archive_id": archive_id,
                    "original_length": len(original_content),
                    "previous_length": len(current_content),
                    "compressed_length": len(further_compressed),
                    "total_compression_ratio": (
                        len(further_compressed) / len(original_content) if original_content else 1.0
                    ),
                }

                cursor.execute(
                    """
                    INSERT INTO archive_records 
                    (original_memory_id, archive_level, compressed_content, original_content, compression_metadata)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        original_id,
                        archive_level,
                        further_compressed,
                        original_content,
                        json.dumps(compression_metadata),
                    ),
                )

                new_archive_id = cursor.lastrowid

                results.append(
                    {
                        "archive_id": new_archive_id,
                        "original_memory_id": original_id,
                        "archive_level": archive_level,
                        "compression_ratio": compression_metadata["total_compression_ratio"],
                    }
                )

            conn.commit()

            logger.info(f"完成归档的归档: {len(results)} 条记录升级到级别 {archive_level}")

            return results

        except Exception as e:
            logger.error(f"归档的归档失败: {e}")
            return []

    def get_archive_stats(self) -> Dict[str, Any]:
        """获取归档统计"""
        try:
            conn = self.memory_manager._get_connection()
            cursor = conn.cursor()

            # 各级别归档数量
            cursor.execute(
                """
                SELECT archive_level, COUNT(*) FROM archive_records GROUP BY archive_level
            """
            )
            level_counts = {row[0]: row[1] for row in cursor.fetchall()}

            # 合并记录数量
            cursor.execute("SELECT COUNT(*) FROM merge_records")
            merge_count = cursor.fetchone()[0]

            # 相似性记录数量
            cursor.execute("SELECT COUNT(*) FROM similarity_records WHERE is_duplicate = TRUE")
            duplicate_count = cursor.fetchone()[0]

            return {
                "archive_level_counts": level_counts,
                "total_archived": sum(level_counts.values()),
                "merge_count": merge_count,
                "duplicate_count": duplicate_count,
                "archive_levels": {
                    k: {
                        "name": v.name,
                        "description": v.description,
                        "compression_ratio": v.compression_ratio,
                    }
                    for k, v in self.ARCHIVE_LEVELS.items()
                },
            }

        except Exception as e:
            logger.error(f"获取归档统计失败: {e}")
            return {}

    def record_similarity(
        self,
        memory_id_1: int,
        memory_id_2: int,
        similarity_score: float,
        is_duplicate: bool = False,
    ):
        """记录相似性"""
        try:
            conn = self.memory_manager._get_connection()
            cursor = conn.cursor()

            # 确保顺序一致
            id_1, id_2 = min(memory_id_1, memory_id_2), max(memory_id_1, memory_id_2)

            cursor.execute(
                """
                INSERT OR REPLACE INTO similarity_records 
                (memory_id_1, memory_id_2, similarity_score, is_duplicate, checked_at)
                VALUES (?, ?, ?, ?, ?)
            """,
                (id_1, id_2, similarity_score, is_duplicate, datetime.now().isoformat()),
            )

            conn.commit()

        except Exception as e:
            logger.warning(f"记录相似性失败: {e}")
