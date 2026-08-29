"""
高级归档管理器
实现归档的归档、智能合并、压缩等功能
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

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
        """初始化高级归档管理器（可选 LLM 客户端用于智能压缩/合并）。"""
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
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close——
        # finally 关闭的是池内缓存连接，后续复用需付重建代价且易触发
        # "Cannot operate on a closed database"

    async def archive_memory(
        self, memory_id: int, target_level: int = 1, compress: bool = True
    ) -> Optional[ArchiveRecord]:
        """归档单个记忆。

        两阶段结构（消除"LLM await 与 sqlite 写段交错"的隐式事务跨 await 问题）：
        - 阶段1（async）：读取原记忆 + LLM 压缩，全部 await 在进入事务段前完成；
        - 阶段2（同步事务段）：经 asyncio.to_thread 卸载到工作线程执行，
          段内无任何 await，thread_id 共享连接不再被其他协程的 commit/rollback 污染。
        """
        try:
            # 阶段1a：获取原记忆（同步 sqlite 读同样卸载到 IO 线程，不阻塞事件循环）
            memory = await asyncio.to_thread(self.memory_manager.get_memory, memory_id)
            if not memory:
                logger.warning(f"记忆不存在: {memory_id}")
                return None

            original_content = memory.get("content", "")

            # 阶段1b：压缩内容（LLM await 全部完成后才进入事务段）
            if compress and self.llm_client:
                compressed_content = await self._compress_content(original_content, target_level)
            else:
                compressed_content = original_content

            # 计算压缩率
            compression_ratio = (
                len(compressed_content) / len(original_content) if original_content else 1.0
            )

            compression_metadata = {
                "original_length": len(original_content),
                "compressed_length": len(compressed_content),
                "compression_ratio": compression_ratio,
                "target_level": target_level,
            }

            # 阶段2：同步事务段（INSERT 归档记录 + UPDATE 记忆归档标记 + commit）
            # 整体卸载到工作线程，行为与返回值（ArchiveRecord）与原实现一致；
            # 段内异常回滚后向 async 侧抛出，由外层统一捕获返回 None。
            return await asyncio.to_thread(
                self._archive_memory_sync,
                memory_id,
                target_level,
                compressed_content,
                original_content,
                compression_metadata,
            )

        except Exception as e:
            logger.error(f"归档记忆失败: {e}")
            return None

    def _archive_memory_sync(
        self,
        memory_id: int,
        target_level: int,
        compressed_content: str,
        original_content: str,
        compression_metadata: Dict[str, Any],
    ) -> ArchiveRecord:
        """archive_memory 阶段2 的同步事务段（仅供 asyncio.to_thread 调度）。

        事务段内严禁出现 await：INSERT + UPDATE 在同一事务内提交，
        任一步失败整体 rollback 后向调用方抛出（外层 async 捕获返回 None）。
        连接所有权归 MemoryManager 连接池，此处不得 close（M-D3）。
        """
        conn = self.memory_manager._get_connection()
        if not conn:
            logger.error("无法获取数据库连接")
            raise RuntimeError("无法获取数据库连接")

        cursor = conn.cursor()

        try:
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

            # 更新记忆状态为已归档（设置 archived_at 与 updated_at）
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE memories
                SET archived_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, memory_id),
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
        except Exception:
            if conn:
                conn.rollback()
            raise

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

            # 原子化修复: 原实现分两阶段写——先经 update_memory_async 在独立连接提交主记忆，
            # 再裸 cursor 更新其余记忆 + INSERT merge_records 后才 commit。两阶段跨连接无事务，
            # 中途中断即产生"主记忆已改、其余记忆未标删"的半合并状态。
            # 现将全部写收敛到同一连接的同一显式事务（BEGIN IMMEDIATE）内，任一步失败整体回滚。
            # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）
            # 线程卸载: BEGIN IMMEDIATE 事务段整体经 asyncio.to_thread 在工作线程执行——
            # 段内无任何 await，事件循环不再被同步 sqlite 阻塞，共享连接也不会在
            # 事务中途被其他协程的 commit/rollback 污染。
            await asyncio.to_thread(
                self._merge_memories_txn_sync,
                memories,
                primary_memory,
                primary_id,
                memory_ids,
                merged_content,
                merge_metadata,
                all_tags,
            )

            # 向量同步（对齐 update_memory 成功路径语义：失败仅告警，不影响主操作）
            try:
                self.memory_manager._update_vector_for_memory(
                    primary_id,
                    merged_content,
                    {
                        "tags": list(all_tags),
                        "agent_id": "default",
                        **(primary_memory.get("metadata") or {}),
                        "merged_from": memory_ids,
                        "is_merged": True,
                    },
                )
            except Exception as vec_e:
                logger.warning(
                    f"合并后向量更新失败，不影响主操作: memory_id={primary_id}, error={vec_e}"
                )

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

    def _merge_memories_txn_sync(
        self,
        memories: List[Dict],
        primary_memory: Dict,
        primary_id: int,
        memory_ids: List[int],
        merged_content: str,
        merge_metadata: Dict[str, Any],
        all_tags: set,
    ) -> None:
        """merge_duplicate_memories 的同步事务段（仅供 asyncio.to_thread 调度）。

        段内严禁出现 await：BEGIN IMMEDIATE 先取写锁，标记次记忆软删 +
        写合并审计 + 更新主记忆全部在同一事务内提交，任一步失败整体回滚；
        rowcount==0 视为主记忆不存在/已删除，抛错触发整体回滚（原样保留）。
        连接所有权归 MemoryManager 连接池，此处不得 close（M-D3）。
        """
        conn = self.memory_manager._get_connection()
        cursor = conn.cursor()

        try:
            # 显式开启 IMMEDIATE 事务：先取写锁，全部写要么整体生效要么整体回滚
            cursor.execute("BEGIN IMMEDIATE")

            # 阶段1：标记其余记忆为已合并（软删除 + merged_into 元数据）并写合并审计记录
            for memory in memories[1:]:
                new_metadata = {**(memory.get("metadata") or {}), "merged_into": primary_id}
                cursor.execute(
                    """
                    UPDATE memories
                    SET is_deleted = TRUE,
                        metadata = ?
                    WHERE id = ?
                    """,
                    (json.dumps(new_metadata, ensure_ascii=False), memory["id"]),
                )

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

            # 阶段2：更新主记忆——SQL 语义复制自 crud_mixin.update_memory
            # （content/tags/metadata/updated_at 四列，WHERE id AND is_deleted=FALSE，
            #   tags/metadata 以 ensure_ascii=False 序列化）。原先经 update_memory_async
            #   在独立连接提前提交，是半合并的根因，现并入本事务保证原子性。
            cursor.execute(
                """
                UPDATE memories
                SET content = ?,
                    tags = ?,
                    metadata = ?,
                    updated_at = ?
                WHERE id = ? AND is_deleted = FALSE
                """,
                (
                    merged_content,
                    json.dumps(list(all_tags), ensure_ascii=False),
                    json.dumps(
                        {
                            **(primary_memory.get("metadata") or {}),
                            "merged_from": memory_ids,
                            "is_merged": True,
                        },
                        ensure_ascii=False,
                    ),
                    datetime.now().isoformat(),
                    primary_id,
                ),
            )
            if cursor.rowcount == 0:
                # 主记忆不存在或已被删除：整体回滚，避免只标删了其余记忆的半合并
                raise RuntimeError(f"主记忆更新失败（不存在或已删除）: id={primary_id}")

            conn.commit()
        except Exception:
            # 任一步失败整体回滚：主记忆与其余记忆均保持合并前状态，
            # 并清掉连接上的悬挂事务（连接将复用回池，不得残留未提交写）
            try:
                conn.rollback()
            except Exception:
                logger.warning("合并事务回滚失败", exc_info=True)
            raise

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
        """归档的归档 - 对已有归档进行二次压缩。

        两阶段结构（对齐 merge_duplicate_memories 第九轮事务化）：
        - 阶段1（async）：读取候选归档 + 循环外先对全部待归档条目完成 LLM
          压缩收集结果，全部 await 在进入事务段前结束；
        - 阶段2（同步事务段）：经 asyncio.to_thread 卸载，BEGIN IMMEDIATE 下
          全部 INSERT 后统一 commit、异常整体 rollback——消除旧实现
          "LLM await 与 cursor.execute(INSERT) 交错"导致的隐式事务跨 await
          持 thread_id 共享连接、被其他协程 commit/rollback 污染的问题。
        """
        try:
            # 阶段1a：读取候选归档（同步 sqlite 读卸载到 IO 线程）
            archives = await asyncio.to_thread(
                self._fetch_archives_by_level, archive_level - 1
            )

            if not archives:
                logger.info(f"没有需要二次归档的级别 {archive_level - 1} 记录")
                return []

            # 阶段1b：循环外先对全部待归档条目完成 LLM 压缩收集结果（无 sqlite 写）
            rows = []
            for archive in archives:
                archive_id = archive[0]
                original_id = archive[1]
                current_content = archive[3]
                original_content = archive[4]

                if self.llm_client:
                    further_compressed = await self._compress_content(
                        current_content, archive_level
                    )
                else:
                    further_compressed = current_content

                compression_metadata = {
                    "previous_archive_id": archive_id,
                    "original_length": len(original_content),
                    "previous_length": len(current_content),
                    "compressed_length": len(further_compressed),
                    "total_compression_ratio": (
                        len(further_compressed) / len(original_content) if original_content else 1.0
                    ),
                }

                rows.append(
                    (
                        original_id,
                        archive_level,
                        further_compressed,
                        original_content,
                        json.dumps(compression_metadata),
                        compression_metadata["total_compression_ratio"],
                    )
                )

            # 阶段2：同步事务段（BEGIN IMMEDIATE + 全部 INSERT + commit，段内无 await）
            results = await asyncio.to_thread(self._insert_second_level_archives_sync, rows)

            logger.info(f"完成归档的归档: {len(results)} 条记录升级到级别 {archive_level}")

            return results

        except Exception as e:
            logger.error(f"归档的归档失败: {e}")
            return []
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）

    def _fetch_archives_by_level(self, level: int) -> list:
        """读取指定级别的归档记录（同步 sqlite 读，仅供 asyncio.to_thread 调度）。"""
        conn = self.memory_manager._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM archive_records
            WHERE archive_level = ?
            ORDER BY archived_at DESC
            """,
            (level,),
        )

        return cursor.fetchall()

    def _insert_second_level_archives_sync(self, rows: List[tuple]) -> List[Dict[str, Any]]:
        """archive_of_archives 阶段2 的同步事务段（仅供 asyncio.to_thread 调度）。

        段内严禁出现 await：BEGIN IMMEDIATE 先取写锁，全部 INSERT 要么整体
        生效要么整体回滚；连接所有权归 MemoryManager 连接池，此处不得 close。
        """
        conn = self.memory_manager._get_connection()
        cursor = conn.cursor()
        results: List[Dict[str, Any]] = []

        try:
            cursor.execute("BEGIN IMMEDIATE")

            for (
                original_id,
                archive_level,
                further_compressed,
                original_content,
                metadata_json,
                total_ratio,
            ) in rows:
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
                        metadata_json,
                    ),
                )

                new_archive_id = cursor.lastrowid

                results.append(
                    {
                        "archive_id": new_archive_id,
                        "original_memory_id": original_id,
                        "archive_level": archive_level,
                        "compression_ratio": total_ratio,
                    }
                )

            conn.commit()
        except Exception:
            # 任一步失败整体回滚：不残留半提交的二次归档行
            try:
                conn.rollback()
            except Exception:
                logger.warning("二次归档事务回滚失败", exc_info=True)
            raise

        return results

    def get_archive_stats(self) -> Dict[str, Any]:
        """获取归档统计"""
        conn = None
        try:
            conn = self.memory_manager._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT archive_level, COUNT(*) FROM archive_records GROUP BY archive_level
            """
            )
            level_counts = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) FROM merge_records")
            merge_count = cursor.fetchone()[0]

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
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）

    def record_similarity(
        self,
        memory_id_1: int,
        memory_id_2: int,
        similarity_score: float,
        is_duplicate: bool = False,
    ):
        """记录相似性"""
        conn = None
        try:
            conn = self.memory_manager._get_connection()
            cursor = conn.cursor()

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
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）
