"""CXFC 存储——插件配置与状态的持久化读写。"""
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiosqlite

from server.core.logging_config import get_contextual_logger

from .models import CXFCPluginInfo, PluginStatus

logger = get_contextual_logger(__name__)


class CXFCStorage:
    """CXFC 插件存储，基于 SQLite 持久化插件的配置信息与连接状态。"""

    def __init__(self, db_path: str = "data/cxfc_plugins.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init_db(self):
        """初始化数据库连接并创建 cxfc_plugins 表（不存在时）。

        Task3 电脑控制接入：表结构新增 token 与 tls_cert_fingerprint 列。为兼容
        既有数据库文件，创建后检测缺失列并执行 ALTER TABLE ADD COLUMN 迁移，旧库
        中历史插件的 token/指纹保持 NULL，不影响既有插件加载。
        B-1 修复：新增 tls_cert_pem 列，沿用幂等 ADD COLUMN 迁移，保持旧库兼容。
        """
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cxfc_plugins (
                plugin_id TEXT PRIMARY KEY,
                host TEXT,
                port INTEGER,
                name TEXT,
                version TEXT,
                capabilities TEXT,
                status TEXT,
                last_seen TEXT,
                tools TEXT,
                skills TEXT,
                token TEXT,
                tls_cert_fingerprint TEXT,
                tls_cert_pem TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        # 向后兼容迁移：为旧库补充新增列（幂等，仅在缺失时执行）
        await self._ensure_column("token", "TEXT")
        await self._ensure_column("tls_cert_fingerprint", "TEXT")
        await self._ensure_column("tls_cert_pem", "TEXT")
        await self._db.commit()

    async def _ensure_column(self, column: str, col_type: str):
        """若表中缺失指定列则 ALTER TABLE 补齐（幂等）。"""
        cursor = await self._db.execute("PRAGMA table_info(cxfc_plugins)")
        rows = await cursor.fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            await self._db.execute(
                f"ALTER TABLE cxfc_plugins ADD COLUMN {column} {col_type}"
            )

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def save_plugin(self, plugin: CXFCPluginInfo):
        await self._db.execute(
            """
            INSERT OR REPLACE INTO cxfc_plugins
            (plugin_id, host, port, name, version, capabilities, status, last_seen, tools, skills, token, tls_cert_fingerprint, tls_cert_pem, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plugin.plugin_id,
                plugin.host,
                plugin.port,
                plugin.name,
                plugin.version,
                json.dumps(plugin.capabilities),
                plugin.status.value,
                plugin.last_seen.isoformat() if plugin.last_seen else None,
                json.dumps(plugin.tools),
                json.dumps(plugin.skills),
                plugin.token,
                plugin.tls_cert_fingerprint,
                plugin.tls_cert_pem,
                plugin.created_at.isoformat() if plugin.created_at else None,
                plugin.updated_at.isoformat() if plugin.updated_at else None,
            ),
        )
        await self._db.commit()

    async def load_plugins(self) -> List[CXFCPluginInfo]:
        cursor = await self._db.execute("SELECT * FROM cxfc_plugins")
        rows = await cursor.fetchall()
        plugins = []
        for row in rows:
            plugin = CXFCPluginInfo(
                plugin_id=row["plugin_id"],
                host=row["host"],
                port=row["port"],
                name=row["name"],
                version=row["version"],
                capabilities=json.loads(row["capabilities"]) if row["capabilities"] else [],
                status=PluginStatus(row["status"]) if row["status"] else PluginStatus.DISCONNECTED,
                last_seen=datetime.fromisoformat(row["last_seen"]) if row["last_seen"] else None,
                tools=json.loads(row["tools"]) if row["tools"] else [],
                skills=json.loads(row["skills"]) if row["skills"] else [],
                token=row["token"] if "token" in row.keys() else None,
                tls_cert_fingerprint=row["tls_cert_fingerprint"] if "tls_cert_fingerprint" in row.keys() else None,
                tls_cert_pem=row["tls_cert_pem"] if "tls_cert_pem" in row.keys() else None,
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )
            plugins.append(plugin)
        return plugins

    async def delete_plugin(self, plugin_id: str):
        """按插件 ID 删除持久化的插件记录。"""
        await self._db.execute("DELETE FROM cxfc_plugins WHERE plugin_id = ?", (plugin_id,))
        await self._db.commit()

    async def update_status(self, plugin_id: str, status: PluginStatus, last_seen: Optional[datetime] = None):
        """更新指定插件的连接状态、最后可见时间并刷新更新时间戳。"""
        await self._db.execute(
            "UPDATE cxfc_plugins SET status = ?, last_seen = ?, updated_at = ? WHERE plugin_id = ?",
            (
                status.value,
                last_seen.isoformat() if last_seen else None,
                datetime.now().isoformat(),
                plugin_id,
            ),
        )
        await self._db.commit()
