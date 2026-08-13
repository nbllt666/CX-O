"""备份管理核心模块（最小 stub）。

提供 BackupType 枚举和 get_backup_manager 单例，
当前为占位实现，返回空结果。完整实现待后续补充。
"""
from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional


class BackupType(enum.Enum):
    """备份类型枚举，区分全量、增量和差异三种备份模式。"""
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"


class BackupManager:
    """最小占位实现。"""

    def list_backups(self) -> List[Dict[str, Any]]:
        return []

    def create_backup(self, backup_type: BackupType = BackupType.FULL, description: Optional[str] = None) -> Dict[str, Any]:
        return {
            "id": "",
            "backup_type": backup_type.value,
            "status": "not_implemented",
            "created_at": "",
            "completed_at": None,
            "description": description,
            "total_size": 0,
            "compressed_size": 0,
            "file_count": 0,
        }

    def get_status(self) -> Dict[str, Any]:
        return {"total_backups": 0}

    def get_backup(self, backup_id: str) -> Optional[Dict[str, Any]]:
        return None

    def delete_backup(self, backup_id: str) -> bool:
        return False

    def restore_backup(self, backup_id: str) -> Dict[str, Any]:
        return {"status": "not_implemented"}

    def import_backup(self, file_path: str) -> Dict[str, Any]:
        return {"status": "not_implemented"}


_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """返回 BackupManager 单例（惰性创建）。"""
    global _manager
    if _manager is None:
        _manager = BackupManager()
    return _manager
