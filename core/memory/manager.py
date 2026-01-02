#!/usr/bin/env python3
"""
记忆管理器

功能：
- 记忆的创建、读取、更新、删除
- RAG检索
- 归档管理
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path
import json
import logging
import sqlite3
import threading

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆管理器"""
    
    def __init__(self, db_path: str = "database/memories.db"):
        """
        初始化记忆管理器
        
        Args:
            db_path: SQLite数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 初始化数据库
        self._init_db()
        
        logger.info(f"记忆管理器初始化完成: db={db_path}")
    
    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 创建记忆表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                vector_id VARCHAR(100),
                metadata TEXT,
                importance INTEGER DEFAULT 3,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                archived_at TIMESTAMP,
                is_deleted BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # 创建审计日志表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation VARCHAR(50) NOT NULL,
                memory_id INTEGER,
                operator VARCHAR(20) NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建索引
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_memories_type 
            ON memories(type)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_memories_created_at 
            ON memories(created_at)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_memories_is_deleted 
            ON memories(is_deleted)
        ''')
        
        conn.commit()
        conn.close()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(str(self.db_path))
    
    def write_memory(
        self,
        content: str,
        memory_type: str = "long_term",
        importance: int = 3,
        tags: List[str] = None,
        metadata: Dict = None
    ) -> int:
        """
        写入记忆
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型（permanent/long_term/short_term）
            importance: 重要性（1-5）
            tags: 标签列表
            metadata: 元数据
        
        Returns:
            记忆ID
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 插入记忆
            cursor.execute('''
                INSERT INTO memories (
                    type, content, importance, tags, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                memory_type,
                content,
                importance,
                json.dumps(tags or [], ensure_ascii=False),
                json.dumps(metadata or {}, ensure_ascii=False),
                datetime.now().isoformat()
            ))
            
            memory_id = cursor.lastrowid
            
            # 记录审计日志
            self._log_operation(cursor, "create", memory_id, "system", {
                "type": memory_type,
                "importance": importance
            })
            
            conn.commit()
            conn.close()
            
            logger.info(f"记忆已写入: id={memory_id}, type={memory_type}")
            
            return memory_id
    
    def get_memory(self, memory_id: int, include_deleted: bool = False) -> Optional[Dict]:
        """
        获取记忆
        
        Args:
            memory_id: 记忆ID
            include_deleted: 是否包含已删除的记忆
        
        Returns:
            记忆数据
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM memories WHERE id = ?"
        if not include_deleted:
            query += " AND is_deleted = FALSE"
        
        cursor.execute(query, (memory_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_memory(row)
        
        return None
    
    def search_memories(
        self,
        query: str = None,
        memory_type: str = None,
        tags: List[str] = None,
        time_range: str = None,
        limit: int = 10,
        include_deleted: bool = False
    ) -> List[Dict]:
        """
        搜索记忆（简单关键词搜索）
        
        Args:
            query: 搜索关键词
            memory_type: 记忆类型筛选
            tags: 标签筛选
            time_range: 时间范围
            limit: 返回数量限制
            include_deleted: 是否包含已删除的记忆
        
        Returns:
            记忆列表
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 构建查询
        conditions = []
        params = []
        
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        
        if memory_type:
            conditions.append("type = ?")
            params.append(memory_type)
        
        if tags:
            conditions.append("tags LIKE ?")
            tag_condition = " OR ".join([f"tags LIKE ?" for _ in tags])
            conditions.append(f"({tag_condition})")
            for tag in tags:
                params.append(f'%"{tag}"%')
        
        if time_range:
            # 简单处理：只支持 today, last_week, last_month
            from datetime import timedelta
            now = datetime.now()
            
            if time_range == "today":
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif time_range == "last_week":
                start_time = now - timedelta(days=7)
            elif time_range == "last_month":
                start_time = now - timedelta(days=30)
            else:
                start_time = now - timedelta(days=1)
            
            conditions.append("created_at >= ?")
            params.append(start_time.isoformat())
        
        if not include_deleted:
            conditions.append("is_deleted = FALSE")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"SELECT * FROM memories WHERE {where_clause} ORDER BY importance DESC, created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_memory(row) for row in rows]
    
    def update_memory(
        self,
        memory_id: int,
        new_content: str = None,
        new_tags: List[str] = None,
        new_importance: int = None
    ) -> bool:
        """
        更新记忆
        
        Args:
            memory_id: 记忆ID
            new_content: 新内容
            new_tags: 新标签
            new_importance: 新重要性
        
        Returns:
            是否成功
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 构建更新语句
            updates = []
            params = []
            
            if new_content is not None:
                updates.append("content = ?")
                params.append(new_content)
            
            if new_tags is not None:
                updates.append("tags = ?")
                params.append(json.dumps(new_tags, ensure_ascii=False))
            
            if new_importance is not None:
                updates.append("importance = ?")
                params.append(new_importance)
            
            if not updates:
                return False
            
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(memory_id)
            
            query = f"UPDATE memories SET {', '.join(updates)} WHERE id = ? AND is_deleted = FALSE"
            cursor.execute(query, params)
            
            success = cursor.rowcount > 0
            
            # 记录审计日志
            if success:
                self._log_operation(cursor, "update", memory_id, "system", {
                    "updates": list(updates)
                })
            
            conn.commit()
            conn.close()
            
            logger.info(f"记忆已更新: id={memory_id}, success={success}")
            
            return success
    
    def delete_memory(self, memory_id: int, soft_delete: bool = True) -> bool:
        """
        删除记忆
        
        Args:
            memory_id: 记忆ID
            soft_delete: 是否软删除（默认软删除）
        
        Returns:
            是否成功
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if soft_delete:
                # 软删除
                query = "UPDATE memories SET is_deleted = TRUE, updated_at = ? WHERE id = ? AND is_deleted = FALSE"
                params = (datetime.now().isoformat(), memory_id)
            else:
                # 硬删除
                query = "DELETE FROM memories WHERE id = ?"
                params = (memory_id,)
            
            cursor.execute(query, params)
            
            success = cursor.rowcount > 0
            
            # 记录审计日志
            if success:
                self._log_operation(cursor, "delete" if not soft_delete else "soft_delete", memory_id, "system", {
                    "soft_delete": soft_delete
                })
            
            conn.commit()
            conn.close()
            
            logger.info(f"记忆已删除: id={memory_id}, soft={soft_delete}")
            
            return success
    
    def restore_memory(self, memory_id: int) -> bool:
        """
        恢复软删除的记忆
        
        Args:
            memory_id: 记忆ID
        
        Returns:
            是否成功
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query = "UPDATE memories SET is_deleted = FALSE, updated_at = ? WHERE id = ? AND is_deleted = TRUE"
            cursor.execute(query, (datetime.now().isoformat(), memory_id))
            
            success = cursor.rowcount > 0
            
            # 记录审计日志
            if success:
                self._log_operation(cursor, "restore", memory_id, "system", {})
            
            conn.commit()
            conn.close()
            
            logger.info(f"记忆已恢复: id={memory_id}")
            
            return success
    
    def get_statistics(self) -> Dict:
        """获取记忆统计信息"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 总数
        cursor.execute("SELECT COUNT(*) FROM memories WHERE is_deleted = FALSE")
        total = cursor.fetchone()[0]
        
        # 按类型统计
        cursor.execute("SELECT type, COUNT(*) FROM memories WHERE is_deleted = FALSE GROUP BY type")
        by_type = {row[0]: row[1] for row in cursor.fetchall()}
        
        # 软删除数
        cursor.execute("SELECT COUNT(*) FROM memories WHERE is_deleted = TRUE")
        soft_deleted = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total": total,
            "by_type": by_type,
            "soft_deleted": soft_deleted
        }
    
    def _row_to_memory(self, row: tuple) -> Dict:
        """将数据库行转换为记忆字典"""
        return {
            "id": row[0],
            "type": row[1],
            "content": row[2],
            "vector_id": row[3],
            "metadata": json.loads(row[4] or "{}"),
            "importance": row[5],
            "tags": json.loads(row[6] or "[]"),
            "created_at": row[7],
            "updated_at": row[8],
            "archived_at": row[9],
            "is_deleted": bool(row[10])
        }
    
    def _log_operation(
        self,
        cursor,
        operation: str,
        memory_id: int,
        operator: str,
        details: Dict
    ):
        """记录审计日志"""
        try:
            cursor.execute('''
                INSERT INTO audit_logs (operation, memory_id, operator, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                operation,
                memory_id,
                operator,
                json.dumps(details, ensure_ascii=False),
                datetime.now().isoformat()
            ))
        except Exception as e:
            logger.error(f"记录审计日志失败: {e}")
    
    def get_audit_logs(self, memory_id: int = None, limit: int = 100) -> List[Dict]:
        """获取审计日志"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if memory_id:
            cursor.execute(
                "SELECT * FROM audit_logs WHERE memory_id = ? ORDER BY timestamp DESC LIMIT ?",
                (memory_id, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "id": row[0],
                "operation": row[1],
                "memory_id": row[2],
                "operator": row[3],
                "details": json.loads(row[4] or "{}"),
                "timestamp": row[5]
            }
            for row in rows
        ]
