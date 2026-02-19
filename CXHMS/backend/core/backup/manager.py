import asyncio
import hashlib
import json
import os
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

from .models import BackupInfo, BackupManifest, BackupStats, BackupStatus, BackupType, RestoreResult

logger = get_contextual_logger(__name__)


class BackupManager:
    """备份管理器

    负责数据备份、恢复和管理
    """

    def __init__(self, backup_dir: str = "backups", data_dir: str = "data", max_backups: int = 10):
        self.backup_dir = Path(backup_dir)
        self.data_dir = Path(data_dir)
        self.max_backups = max_backups
        self._executor = ThreadPoolExecutor(max_workers=2)

        # 确保目录存在
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 备份记录
        self._backups: Dict[str, BackupInfo] = {}
        self._load_backup_index()

    def _load_backup_index(self):
        """加载备份索引"""
        index_file = self.backup_dir / "index.json"
        if index_file.exists():
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for backup_data in data.get("backups", []):
                        backup = BackupInfo(**backup_data)
                        self._backups[backup.id] = backup
            except Exception as e:
                logger.error(f"加载备份索引失败: {e}")

    def _save_backup_index(self):
        """保存备份索引"""
        index_file = self.backup_dir / "index.json"
        try:
            data = {"backups": [b.to_dict() for b in self._backups.values()]}
            with open(index_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存备份索引失败: {e}")

    def _calculate_checksum(self, file_path: Path) -> str:
        """计算文件校验和"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _get_data_files(self) -> List[Path]:
        """获取需要备份的数据文件"""
        files = []

        if self.data_dir.exists():
            for file_path in self.data_dir.rglob("*"):
                if file_path.is_file():
                    files.append(file_path)

        return files

    async def create_backup(
        self,
        backup_type: BackupType = BackupType.FULL,
        description: str = None,
        sources: List[str] = None,
    ) -> BackupInfo:
        """创建备份"""
        backup_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{backup_type.value}_{timestamp}_{backup_id}.zip"
        backup_path = self.backup_dir / backup_filename

        backup = BackupInfo(
            id=backup_id,
            backup_type=backup_type,
            status=BackupStatus.RUNNING,
            description=description or f"Backup {timestamp}",
            path=str(backup_path),
        )

        self._backups[backup_id] = backup

        try:
            # 在后台执行备份
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self._do_backup, backup, sources)

            # 清理旧备份
            self._cleanup_old_backups()

            return backup

        except Exception as e:
            backup.status = BackupStatus.FAILED
            backup.error_message = str(e)
            logger.error(f"备份失败: {e}")
            return backup
        finally:
            self._save_backup_index()

    def _do_backup(self, backup: BackupInfo, sources: List[str] = None):
        """执行备份（在后台线程中）"""
        try:
            data_files = self._get_data_files()

            if not data_files:
                backup.status = BackupStatus.FAILED
                backup.error_message = "没有数据文件需要备份"
                return

            # 创建ZIP文件
            with zipfile.ZipFile(backup.path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 添加清单文件
                manifest = BackupManifest(
                    backup_id=backup.id,
                    backup_type=backup.backup_type,
                    description=backup.description,
                    sources=sources or [str(self.data_dir)],
                )

                # 添加数据文件
                for file_path in data_files:
                    arcname = file_path.relative_to(self.data_dir)
                    zf.write(file_path, arcname)

                    # 计算校验和
                    checksum = self._calculate_checksum(file_path)
                    manifest.files[str(arcname)] = checksum

                    backup.total_size += file_path.stat().st_size
                    backup.file_count += 1

                # 写入清单
                zf.writestr("manifest.json", manifest.json())

            # 更新备份信息
            backup.compressed_size = Path(backup.path).stat().st_size
            backup.status = BackupStatus.COMPLETED
            backup.completed_at = datetime.now()

            logger.info(f"备份完成: {backup.id} ({backup.file_count} 个文件)")

        except Exception as e:
            backup.status = BackupStatus.FAILED
            backup.error_message = str(e)
            logger.error(f"备份失败: {e}")

    async def restore_backup(self, backup_id: str, target_dir: str = None) -> RestoreResult:
        """恢复备份"""
        if backup_id not in self._backups:
            return RestoreResult(success=False, error_message=f"备份不存在: {backup_id}")

        backup = self._backups[backup_id]

        if backup.status != BackupStatus.COMPLETED:
            return RestoreResult(
                success=False, error_message=f"备份状态不正确: {backup.status.value}"
            )

        backup.status = BackupStatus.RESTORING

        try:
            target = Path(target_dir) if target_dir else self.data_dir

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(self._executor, self._do_restore, backup, target)

            return result

        except Exception as e:
            return RestoreResult(success=False, error_message=str(e))
        finally:
            if backup.status == BackupStatus.RESTORING:
                backup.status = BackupStatus.COMPLETED
            self._save_backup_index()

    def _do_restore(self, backup: BackupInfo, target_dir: Path) -> RestoreResult:
        """执行恢复（在后台线程中）"""
        result = RestoreResult()

        try:
            # 备份当前数据
            if target_dir.exists():
                backup_current = target_dir.with_suffix(".backup")
                shutil.copytree(target_dir, backup_current, dirs_exist_ok=True)

            # 解压备份
            with zipfile.ZipFile(backup.path, "r") as zf:
                # 验证清单
                if "manifest.json" in zf.namelist():
                    manifest_data = json.loads(zf.read("manifest.json"))
                    manifest = BackupManifest(**manifest_data)

                    # 验证文件完整性
                    for filename, expected_checksum in manifest.files.items():
                        if filename in zf.namelist():
                            # 临时解压验证
                            temp_path = target_dir / filename
                            zf.extract(filename, target_dir.parent)
                            actual_checksum = self._calculate_checksum(temp_path)

                            if actual_checksum != expected_checksum:
                                result.failed_files += 1
                                logger.warning(f"校验和不匹配: {filename}")
                            else:
                                result.restored_files += 1
                        else:
                            result.failed_files += 1
                            logger.warning(f"文件缺失: {filename}")
                else:
                    # 没有清单，直接解压所有文件
                    zf.extractall(target_dir)
                    result.restored_files = len(zf.namelist()) - 1  # 减去manifest.json

            result.success = result.failed_files == 0
            result.completed_at = datetime.now()

            # 删除临时备份
            if target_dir.exists():
                backup_current = target_dir.with_suffix(".backup")
                if backup_current.exists():
                    shutil.rmtree(backup_current)

            logger.info(f"恢复完成: {backup.id} ({result.restored_files} 个文件)")

        except Exception as e:
            result.success = False
            result.error_message = str(e)
            logger.error(f"恢复失败: {e}")

        return result

    def delete_backup(self, backup_id: str) -> bool:
        """删除备份"""
        if backup_id not in self._backups:
            return False

        backup = self._backups[backup_id]

        try:
            # 删除备份文件
            backup_path = Path(backup.path)
            if backup_path.exists():
                backup_path.unlink()

            # 从索引中移除
            del self._backups[backup_id]
            self._save_backup_index()

            logger.info(f"备份已删除: {backup_id}")
            return True

        except Exception as e:
            logger.error(f"删除备份失败: {e}")
            return False

    def get_backup(self, backup_id: str) -> Optional[BackupInfo]:
        """获取备份信息"""
        return self._backups.get(backup_id)

    def get_all_backups(self) -> List[BackupInfo]:
        """获取所有备份"""
        return sorted(self._backups.values(), key=lambda b: b.created_at, reverse=True)

    def get_stats(self) -> BackupStats:
        """获取备份统计"""
        stats = BackupStats()

        if not self._backups:
            return stats

        stats.total_backups = len(self._backups)
        stats.full_backups = sum(
            1 for b in self._backups.values() if b.backup_type == BackupType.FULL
        )
        stats.incremental_backups = sum(
            1 for b in self._backups.values() if b.backup_type == BackupType.INCREMENTAL
        )
        stats.total_size = sum(b.compressed_size for b in self._backups.values())

        completed = [b for b in self._backups.values() if b.status == BackupStatus.COMPLETED]
        if completed:
            stats.oldest_backup = min(b.created_at for b in completed)
            stats.latest_backup = max(b.created_at for b in completed)

        return stats

    def _cleanup_old_backups(self):
        """清理旧备份"""
        if len(self._backups) <= self.max_backups:
            return

        # 按时间排序，保留最新的
        sorted_backups = sorted(self._backups.values(), key=lambda b: b.created_at, reverse=True)

        to_delete = sorted_backups[self.max_backups :]

        for backup in to_delete:
            self.delete_backup(backup.id)
            logger.info(f"旧备份已清理: {backup.id}")

    def export_backup(self, backup_id: str, export_path: str) -> bool:
        """导出备份到指定路径"""
        if backup_id not in self._backups:
            return False

        backup = self._backups[backup_id]
        source = Path(backup.path)
        target = Path(export_path)

        try:
            shutil.copy2(source, target)
            return True
        except Exception as e:
            logger.error(f"导出备份失败: {e}")
            return False

    def import_backup(self, import_path: str) -> Optional[BackupInfo]:
        """从文件导入备份"""
        source = Path(import_path)

        if not source.exists():
            return None

        try:
            # 生成新ID
            backup_id = str(uuid.uuid4())[:8]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"imported_{timestamp}_{backup_id}.zip"
            backup_path = self.backup_dir / backup_filename

            # 复制文件
            shutil.copy2(source, backup_path)

            # 读取清单
            with zipfile.ZipFile(backup_path, "r") as zf:
                if "manifest.json" in zf.namelist():
                    manifest_data = json.loads(zf.read("manifest.json"))
                    manifest = BackupManifest(**manifest_data)

                    backup = BackupInfo(
                        id=backup_id,
                        backup_type=manifest.backup_type,
                        status=BackupStatus.COMPLETED,
                        description=f"Imported: {manifest.description}",
                        path=str(backup_path),
                        total_size=manifest.total_size,
                        compressed_size=backup_path.stat().st_size,
                        file_count=manifest.file_count,
                        completed_at=datetime.now(),
                    )
                else:
                    # 没有清单，创建基本信息
                    backup = BackupInfo(
                        id=backup_id,
                        backup_type=BackupType.FULL,
                        status=BackupStatus.COMPLETED,
                        description="Imported backup",
                        path=str(backup_path),
                        compressed_size=backup_path.stat().st_size,
                        completed_at=datetime.now(),
                    )

            self._backups[backup_id] = backup
            self._save_backup_index()

            logger.info(f"备份已导入: {backup_id}")
            return backup

        except Exception as e:
            logger.error(f"导入备份失败: {e}")
            return None

    def shutdown(self, wait: bool = True):
        """关闭备份管理器，清理资源"""
        if self._executor:
            logger.info("正在关闭备份管理器线程池...")
            self._executor.shutdown(wait=wait)
            logger.info("备份管理器已关闭")


# 全局备份管理器实例
_backup_manager: Optional[BackupManager] = None


def get_backup_manager(
    backup_dir: str = "backups", data_dir: str = "data", max_backups: int = 10
) -> BackupManager:
    """获取全局备份管理器实例"""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager(backup_dir, data_dir, max_backups)
    return _backup_manager
