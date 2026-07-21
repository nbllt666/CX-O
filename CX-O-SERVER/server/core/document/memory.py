"""文档记忆管理器模块。

迁移自 CXHMS backend/core/document/memory.py（适配 CX-O 路径与 API 风格）。

职责：
    1. 文档元数据管理（SQLite: data/documents.db）
    2. 文档内容解析（复用 server.core.document.parser）
    3. 文档内容持久化到永久记忆（调用 MemoryManager.write_permanent_memory）
    4. 文档与 workspace 的关联管理

依赖：
    - server.core.document.parser: 文档解析（复用 parse_document 与大小常量）
    - MemoryManager（通过构造函数注入，避免循环依赖）：永久记忆读写
"""

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Dict, Optional

from server.core.document.parser import MAX_DOCUMENT_SIZE, parse_document

logger = logging.getLogger(__name__)

# === 路径解析（禁止相对路径如 ../../ 或 ..\\） ===
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# _THIS_DIR = .../CX-O-SERVER/server/core/document
# 向上三级到 CX-O-SERVER 目录（后端服务根，含 data/）：document -> core -> server -> CX-O-SERVER
_SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
# 向上四级到 CX-O 项目根（含 public/ 目录）：document -> core -> server -> CX-O-SERVER -> CX-O
_PROJECT_ROOT = os.path.dirname(_SERVER_ROOT)

# === 默认配置（配置文件缺失时使用） ===
_DEFAULT_CONFIG: Dict = {
    "db_path": "data/documents.db",
    "max_file_size": MAX_DOCUMENT_SIZE,  # 10MB，与 parser 模块保持一致
    "default_folder": "custom-documents",
}

# 默认配置文件路径（基于项目根解析）
_DEFAULT_CONFIG_PATH = os.path.join(
    _PROJECT_ROOT, "public", "config_template", "anythingllm_document_config.json"
)


class DocumentMemoryManager:
    """文档记忆管理器。

    职责：
        1. 文档元数据管理（SQLite: data/documents.db）
        2. 文档内容解析（复用 server.core.document.parser）
        3. 文档内容持久化到永久记忆（调用 MemoryManager.write_permanent_memory）
        4. 文档与 workspace 的关联管理

    Attributes:
        memory_manager: MemoryManager 实例（构造函数注入）
        config: 配置字典（含 db_path / max_file_size / default_folder）
        db_path: SQLite 数据库绝对路径
        conn: SQLite 连接对象
    """

    def __init__(self, memory_manager, config_path: str = None):
        """初始化文档记忆管理器。

        加载配置（缺失字段自动补充默认值）、初始化 SQLite 数据库与表结构。

        Args:
            memory_manager: MemoryManager 实例，用于读写永久记忆
            config_path: 配置文件路径；默认为
                public/config_template/anythingllm_document_config.json。
                文件不存在时使用全部默认值。
        """
        self.memory_manager = memory_manager
        self.config = self._load_config(config_path)

        # 解析 db_path 为绝对路径（相对 CX-O-SERVER 服务根，与其他后端数据一致）
        db_path = self.config["db_path"]
        if not os.path.isabs(db_path):
            db_path = os.path.join(_SERVER_ROOT, db_path)

        # 确保数据目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(
                f"[{datetime.now().isoformat()}] [INFO] 创建数据目录: {db_dir}"
            )

        self.db_path = db_path
        # 可重入线程锁：保护 conn 并发访问（check_same_thread=False 允许跨线程，但需自行加锁）
        # 使用 RLock 因 delete_document 调用 get_document，update_workspace_documents 调用 get_workspace_documents
        self._lock = threading.RLock()
        self.conn = self._init_db()
        logger.info(
            f"[{datetime.now().isoformat()}] [INFO] DocumentMemoryManager 初始化完成, "
            f"db={db_path}"
        )

    # ===== 内部工具方法 =====

    def _load_config(self, config_path: str = None) -> Dict:
        """加载配置文件，自动补充缺失字段。

        Args:
            config_path: 配置文件路径

        Returns:
            配置字典（含全部必填字段：db_path / max_file_size / default_folder）
        """
        path = config_path or _DEFAULT_CONFIG_PATH
        config = dict(_DEFAULT_CONFIG)

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                if isinstance(user_config, dict):
                    config.update(user_config)
                logger.info(
                    f"[{datetime.now().isoformat()}] [INFO] 加载配置成功: {path}"
                )
            except Exception as e:
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 加载配置失败: {e}, 使用默认值"
                )
        else:
            logger.info(
                f"[{datetime.now().isoformat()}] [INFO] 配置文件不存在, 使用默认值: {path}"
            )

        return config

    def _init_db(self) -> sqlite3.Connection:
        """初始化 SQLite 数据库，创建表结构（如不存在）。

        Returns:
            sqlite3.Connection 连接对象

        Raises:
            sqlite3.Error: 建表失败时抛出
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_name TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    doc_author TEXT DEFAULT 'Unknown',
                    description TEXT DEFAULT 'Unknown',
                    doc_source TEXT,
                    mime_type TEXT,
                    word_count INTEGER DEFAULT 0,
                    token_count_estimate INTEGER DEFAULT 0,
                    text_content TEXT,
                    memory_id INTEGER,
                    folder TEXT DEFAULT 'custom-documents',
                    file_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_deleted BOOLEAN DEFAULT FALSE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_slug TEXT NOT NULL,
                    document_id INTEGER NOT NULL,
                    is_pinned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(workspace_slug, document_id)
                )
                """
            )
            conn.commit()
            logger.info(
                f"[{datetime.now().isoformat()}] [INFO] 数据库表已就绪: documents, workspace_documents"
            )
            return conn
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(
                f"[{datetime.now().isoformat()}] [ERROR] 初始化数据库失败: {e}"
            )
            raise

    def _extract_metadata(
        self, metadata: Optional[dict], filename: str = None
    ) -> Dict:
        """从 metadata 字典提取标准化字段，补充默认值。

        Args:
            metadata: 用户传入的元数据
            filename: 文件名（用于推断默认 title）

        Returns:
            标准化后的元数据字典
        """
        metadata = metadata or {}

        # title：优先 metadata，其次 filename 去扩展名，最后 "Untitled"
        title = metadata.get("title")
        if not title:
            if filename:
                title = os.path.splitext(filename)[0]
            else:
                title = "Untitled"

        return {
            "title": title,
            "doc_author": metadata.get("author", "Unknown"),
            "description": metadata.get("description", "Unknown"),
            "doc_source": metadata.get("source", "file"),
            "folder": metadata.get("folder", self.config["default_folder"]),
            "file_path": metadata.get("file_path"),
            "mime_type": metadata.get("mime_type"),
        }

    def _persist_document(
        self,
        text: str,
        meta: Dict,
        workspaces: Optional[list],
    ) -> dict:
        """内部共享逻辑：写永久记忆 → 存 documents 元数据 → 关联 workspace。

        被 upload_file 与 upload_text 复用。

        Args:
            text: 文档纯文本内容
            meta: 标准化后的元数据（含 title/author/description/source/folder/mime_type）
            workspaces: 关联的 workspace slug 列表

        Returns:
            {"doc_name", "title", "word_count", "token_count_estimate", "memory_id"}

        Raises:
            ValueError: 写永久记忆失败
            sqlite3.Error: 存元数据失败（已回滚永久记忆）
        """
        # 计算 word_count / token_count_estimate
        word_count = len(text.split())
        token_count_estimate = int(word_count * 1.3)

        # 生成 doc_name（title + 完整 UUID + .json，与 schema pattern 一致）
        doc_name = f"{meta['title']}-{uuid.uuid4()}.json"

        # 写永久记忆
        try:
            memory_id = self.memory_manager.write_permanent_memory(
                content=text,
                tags=[doc_name, "document"],
                metadata={
                    "doc_name": doc_name,
                    "title": meta["title"],
                    "source": meta["doc_source"],
                },
                source="document",
            )
        except Exception as e:
            logger.error(
                f"[{datetime.now().isoformat()}] [ERROR] 写入永久记忆失败: {e}"
            )
            raise ValueError(f"写入永久记忆失败: {e}")

        # 存 documents 元数据（加锁保护 SQLite 跨线程访问）
        now = datetime.now().isoformat()
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO documents (
                        doc_name, title, doc_author, description, doc_source,
                        mime_type, word_count, token_count_estimate, text_content,
                        memory_id, folder, file_path, created_at, updated_at, is_deleted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        doc_name,
                        meta["title"],
                        meta["doc_author"],
                        meta["description"],
                        meta["doc_source"],
                        meta["mime_type"],
                        word_count,
                        token_count_estimate,
                        text,
                        memory_id,
                        meta["folder"],
                        meta["file_path"],
                        now,
                        now,
                    ),
                )
                doc_id = cursor.lastrowid  # commit 前获取，避免后续 execute 覆盖
                self.conn.commit()
                logger.info(
                    f"[{datetime.now().isoformat()}] [INFO] 文档已存储: "
                    f"doc_name={doc_name}, memory_id={memory_id}, word_count={word_count}"
                )
            except sqlite3.Error as e:
                self.conn.rollback()
                # 回滚已写入的永久记忆（尽力补偿）
                try:
                    self.memory_manager.delete_permanent_memory(
                        memory_id, is_from_main=True
                    )
                    logger.info(
                        f"[{datetime.now().isoformat()}] [INFO] 已回滚永久记忆: memory_id={memory_id}"
                    )
                except Exception as cleanup_err:
                    logger.error(
                        f"[{datetime.now().isoformat()}] [ERROR] 回滚永久记忆失败: {cleanup_err}"
                    )
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 存储文档元数据失败: {e}"
                )
                raise

            # 关联 workspace（失败不回滚主文档，仅记录日志）
            if workspaces:
                for slug in workspaces:
                    try:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO workspace_documents
                                (workspace_slug, document_id, is_pinned, created_at)
                            VALUES (?, ?, 0, ?)
                            """,
                            (slug, doc_id, now),
                        )
                        self.conn.commit()
                    except sqlite3.Error as e:
                        self.conn.rollback()
                        logger.error(
                            f"[{datetime.now().isoformat()}] [ERROR] "
                            f"关联 workspace '{slug}' 失败: {e}"
                        )

        return {
            "doc_name": doc_name,
            "title": meta["title"],
            "word_count": word_count,
            "token_count_estimate": token_count_estimate,
            "memory_id": memory_id,
        }

    # ===== 对外 API =====

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime: str,
        metadata: dict = None,
        workspaces: list = None,
    ) -> dict:
        """上传文件 → 解析 → 存永久记忆 → 存元数据。

        流程：
            1. 检查文件大小（max_file_size）
            2. 调用 parser.parse_document 解析为纯文本
            3. 调用 memory_manager.write_permanent_memory 持久化（tags=[doc_name, "document"]）
            4. 计算 word_count / token_count_estimate
            5. 生成 doc_name = f"{title}-{uuid.uuid4().hex[:8]}.json"
            6. 存入 documents 表
            7. 如有 workspaces，存入 workspace_documents 关联表
            8. 返回文档摘要

        Args:
            file_bytes: 文件原始字节
            filename: 文件名（用于推断 title 与格式）
            mime: MIME 类型
            metadata: 元数据（title/author/description/source/folder 等）
            workspaces: 关联的 workspace slug 列表

        Returns:
            {"doc_name", "title", "word_count", "token_count_estimate", "memory_id"}

        Raises:
            ValueError: 文件大小超限或解析失败
        """
        max_size = self.config["max_file_size"]

        # 1. 检查文件大小
        if len(file_bytes) > max_size:
            raise ValueError(
                f"文件大小超过限制: {len(file_bytes)} > {max_size}"
            )

        # 2. 解析文档为纯文本
        try:
            text = parse_document(filename, mime, file_bytes)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"文档解析失败: {e}")

        # 提取标准化元数据（mime 覆盖为实际上传 mime）
        meta = self._extract_metadata(metadata, filename=filename)
        meta["mime_type"] = mime

        # 3~8. 共享持久化逻辑
        return self._persist_document(text, meta, workspaces)

    def upload_text(
        self,
        text_content: str,
        metadata: dict = None,
        workspaces: list = None,
    ) -> dict:
        """上传纯文本 → 存永久记忆 → 存元数据。

        逻辑同 upload_file，但跳过解析步骤。

        Args:
            text_content: 纯文本内容
            metadata: 元数据
            workspaces: 关联的 workspace slug 列表

        Returns:
            {"doc_name", "title", "word_count", "token_count_estimate", "memory_id"}

        Raises:
            ValueError: 文本内容为空
        """
        if not text_content or not text_content.strip():
            raise ValueError("文本内容不能为空")

        meta = self._extract_metadata(metadata, filename=None)
        meta["mime_type"] = "text/plain"

        return self._persist_document(text_content, meta, workspaces)

    def get_document(self, doc_name: str) -> Optional[dict]:
        """获取单个文档详情（is_deleted=False）。

        Args:
            doc_name: 文档唯一名

        Returns:
            文档详情字典；不存在或已删除返回 None
        """
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT * FROM documents
                    WHERE doc_name = ? AND is_deleted = 0
                    """,
                    (doc_name,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)
            except sqlite3.Error as e:
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 查询文档失败: {e}"
                )
                return None

    def list_documents(self, folder: str = None) -> list:
        """列出所有未删除文档。

        Args:
            folder: 仅列出指定 folder 的文档（None 表示全部）

        Returns:
            文档详情列表（按 id 升序）；查询失败返回空列表
        """
        with self._lock:
            cursor = self.conn.cursor()
            try:
                if folder:
                    cursor.execute(
                        """
                        SELECT * FROM documents
                        WHERE is_deleted = 0 AND folder = ?
                        ORDER BY id ASC
                        """,
                        (folder,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT * FROM documents
                        WHERE is_deleted = 0
                        ORDER BY id ASC
                        """
                    )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            except sqlite3.Error as e:
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 列出文档失败: {e}"
                )
                return []

    def delete_document(self, doc_name: str) -> bool:
        """删除文档：documents 表标记 is_deleted=True，并删除对应永久记忆。

        Args:
            doc_name: 文档唯一名

        Returns:
            True 表示删除成功；False 表示文档不存在或失败
        """
        with self._lock:
            doc = self.get_document(doc_name)
            if not doc:
                return False

            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE documents
                    SET is_deleted = 1, updated_at = ?
                    WHERE doc_name = ? AND is_deleted = 0
                    """,
                    (datetime.now().isoformat(), doc_name),
                )
                self.conn.commit()

                # 删除永久记忆（失败不影响文档软删除结果，仅记录日志）
                memory_id = doc.get("memory_id")
                if memory_id:
                    try:
                        self.memory_manager.delete_permanent_memory(
                            memory_id, is_from_main=True
                        )
                    except Exception as e:
                        logger.error(
                            f"[{datetime.now().isoformat()}] [ERROR] 删除永久记忆失败: "
                            f"memory_id={memory_id}, error={e}"
                        )

                logger.info(
                    f"[{datetime.now().isoformat()}] [INFO] 文档已删除: doc_name={doc_name}"
                )
                return True
            except sqlite3.Error as e:
                self.conn.rollback()
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 删除文档失败: {e}"
                )
                return False

    def update_workspace_documents(
        self,
        slug: str,
        adds: list = None,
        deletes: list = None,
    ) -> dict:
        """管理 workspace 文档关联。

        Args:
            slug: workspace 标识
            adds: 要添加关联的 doc_name 列表
            deletes: 要移除关联的 doc_name 列表

        Returns:
            {"workspace": slug, "documents": [...当前关联的文档...]}
        """
        adds = adds or []
        deletes = deletes or []
        now = datetime.now().isoformat()

        with self._lock:
            cursor = self.conn.cursor()
            try:
                # 添加关联
                for doc_name in adds:
                    cursor.execute(
                        "SELECT id FROM documents WHERE doc_name = ? AND is_deleted = 0",
                        (doc_name,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        logger.warning(
                            f"[{now}] [INFO] 添加关联时文档不存在或已删除: {doc_name}"
                        )
                        continue
                    doc_id = row["id"]
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO workspace_documents
                            (workspace_slug, document_id, is_pinned, created_at)
                        VALUES (?, ?, 0, ?)
                        """,
                        (slug, doc_id, now),
                    )

                # 移除关联
                for doc_name in deletes:
                    cursor.execute(
                        "SELECT id FROM documents WHERE doc_name = ?",
                        (doc_name,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        continue
                    doc_id = row["id"]
                    cursor.execute(
                        """
                        DELETE FROM workspace_documents
                        WHERE workspace_slug = ? AND document_id = ?
                        """,
                        (slug, doc_id),
                    )

                self.conn.commit()
                logger.info(
                    f"[{now}] [INFO] workspace '{slug}' 关联更新: "
                    f"adds={len(adds)}, deletes={len(deletes)}"
                )
            except sqlite3.Error as e:
                self.conn.rollback()
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 更新 workspace 关联失败: {e}"
                )

            return {
                "workspace": slug,
                "documents": self.get_workspace_documents(slug),
            }

    def get_workspace_documents(self, slug: str) -> list:
        """获取 workspace 关联的文档列表。

        Args:
            slug: workspace 标识

        Returns:
            文档详情列表（含 is_pinned / associated_at 字段，按关联 id 升序）；
            查询失败返回空列表
        """
        with self._lock:
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT d.*, wd.is_pinned, wd.created_at AS associated_at
                    FROM workspace_documents wd
                    JOIN documents d ON wd.document_id = d.id
                    WHERE wd.workspace_slug = ? AND d.is_deleted = 0
                    ORDER BY wd.id ASC
                    """,
                    (slug,),
                )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
            except sqlite3.Error as e:
                logger.error(
                    f"[{datetime.now().isoformat()}] [ERROR] 查询 workspace 文档失败: {e}"
                )
                return []

    def search_in_workspace(
        self,
        slug: str,
        query: str,
        limit: int = 10,
    ) -> list:
        """在 workspace 文档中搜索。

        CX-O 适配：使用 CX-O MemoryManager.search_memories（CXHMS 用 search_all_memories）。
        CX-O 的 search_memories 支持 workspace_id 和 agent_id 参数。

        Args:
            slug: workspace 标识
            query: 搜索关键词
            limit: 返回数量限制

        Returns:
            搜索结果列表；调用失败返回空列表
        """
        try:
            results = self.memory_manager.search_memories(
                query=query,
                workspace_id=slug,
                limit=limit,
            )
            logger.info(
                f"[{datetime.now().isoformat()}] [INFO] workspace '{slug}' 搜索 '{query}': "
                f"返回 {len(results)} 条结果"
            )
            return results
        except Exception as e:
            logger.error(
                f"[{datetime.now().isoformat()}] [ERROR] 搜索失败: {e}"
            )
            return []

    def close(self):
        """关闭数据库连接。"""
        try:
            if self.conn:
                self.conn.close()
                logger.info(
                    f"[{datetime.now().isoformat()}] [INFO] 数据库连接已关闭"
                )
        except Exception as e:
            logger.error(
                f"[{datetime.now().isoformat()}] [ERROR] 关闭数据库连接失败: {e}"
            )
