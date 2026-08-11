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
    def __init__(self, db_path: str = "data/cxfc_plugins.db"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def init_db(self):
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
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def save_plugin(self, plugin: CXFCPluginInfo):
        await self._db.execute(
            """
            INSERT OR REPLACE INTO cxfc_plugins
            (plugin_id, host, port, name, version, capabilities, status, last_seen, tools, skills, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            )
            plugins.append(plugin)
        return plugins

    async def delete_plugin(self, plugin_id: str):
        await self._db.execute("DELETE FROM cxfc_plugins WHERE plugin_id = ?", (plugin_id,))
        await self._db.commit()

    async def update_status(self, plugin_id: str, status: PluginStatus, last_seen: Optional[datetime] = None):
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
