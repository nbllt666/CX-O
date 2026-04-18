"""
备份管理路由 - 提供数据备份和恢复 API
"""

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.core.backup import BackupType, get_backup_manager
from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)
router = APIRouter()


class CreateBackupRequest(BaseModel):
    """创建备份请求"""

    backup_type: str = "full"
    description: Optional[str] = None


class BackupResponse(BaseModel):
    """备份响应"""

    id: str
    backup_type: str
    status: str
    created_at: str
    completed_at: Optional[str]
    description: Optional[str]
    total_size: int
    compressed_size: int
    file_count: int


class RestoreResponse(BaseModel):
    """恢复响应"""

    success: bool
    restored_files: int
    failed_files: int
    error_message: Optional[str] = None


class BackupStatsResponse(BaseModel):
    """备份统计响应"""

    total_backups: int
    full_backups: int
    incremental_backups: int
    total_size: int
    oldest_backup: Optional[str]
    latest_backup: Optional[str]


def _backup_to_response(backup) -> BackupResponse:
    """转换备份信息为响应"""
    return BackupResponse(
        id=backup.id,
        backup_type=backup.backup_type.value,
        status=backup.status.value,
        created_at=backup.created_at.isoformat(),
        completed_at=backup.completed_at.isoformat() if backup.completed_at else None,
        description=backup.description,
        total_size=backup.total_size,
        compressed_size=backup.compressed_size,
        file_count=backup.file_count,
    )


@router.get("/backups", response_model=List[BackupResponse])
async def list_backups():
    """获取所有备份列表"""
    try:
        manager = get_backup_manager()
        backups = manager.get_all_backups()
        return [_backup_to_response(b) for b in backups]
    except Exception as e:
        logger.error(f"获取备份列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backups", response_model=BackupResponse)
async def create_backup(request: CreateBackupRequest):
    """创建新备份"""
    try:
        manager = get_backup_manager()

        backup_type = BackupType.FULL
        if request.backup_type == "incremental":
            backup_type = BackupType.INCREMENTAL
        elif request.backup_type == "differential":
            backup_type = BackupType.DIFFERENTIAL

        backup = await manager.create_backup(
            backup_type=backup_type, description=request.description
        )

        return _backup_to_response(backup)
    except Exception as e:
        logger.error(f"创建备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backups/{backup_id}", response_model=BackupResponse)
async def get_backup(backup_id: str):
    """获取备份详情"""
    try:
        manager = get_backup_manager()
        backup = manager.get_backup(backup_id)

        if not backup:
            raise HTTPException(status_code=404, detail=f"备份不存在: {backup_id}")

        return _backup_to_response(backup)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取备份详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backups/{backup_id}/restore", response_model=RestoreResponse)
async def restore_backup(backup_id: str):
    """恢复备份"""
    try:
        manager = get_backup_manager()

        backup = manager.get_backup(backup_id)
        if not backup:
            raise HTTPException(status_code=404, detail=f"备份不存在: {backup_id}")

        result = await manager.restore_backup(backup_id)

        return RestoreResponse(
            success=result.success,
            restored_files=result.restored_files,
            failed_files=result.failed_files,
            error_message=result.error_message,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/backups/{backup_id}")
async def delete_backup(backup_id: str):
    """删除备份"""
    try:
        manager = get_backup_manager()

        backup = manager.get_backup(backup_id)
        if not backup:
            raise HTTPException(status_code=404, detail=f"备份不存在: {backup_id}")

        success = manager.delete_backup(backup_id)

        if success:
            return {"status": "success", "message": f"备份 {backup_id} 已删除"}
        else:
            raise HTTPException(status_code=500, detail="删除备份失败")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backups/stats", response_model=BackupStatsResponse)
async def get_backup_stats():
    """获取备份统计"""
    try:
        manager = get_backup_manager()
        stats = manager.get_stats()

        return BackupStatsResponse(
            total_backups=stats.total_backups,
            full_backups=stats.full_backups,
            incremental_backups=stats.incremental_backups,
            total_size=stats.total_size,
            oldest_backup=stats.oldest_backup.isoformat() if stats.oldest_backup else None,
            latest_backup=stats.latest_backup.isoformat() if stats.latest_backup else None,
        )
    except Exception as e:
        logger.error(f"获取备份统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backups/import")
async def import_backup(file: UploadFile = File(...)):
    """导入备份文件"""
    try:
        manager = get_backup_manager()

        # 保存上传的文件
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # 导入备份
            backup = manager.import_backup(tmp_path)

            if backup:
                return {"status": "success", "backup": _backup_to_response(backup)}
            else:
                raise HTTPException(status_code=400, detail="导入备份失败，文件可能损坏")
        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导入备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backups/{backup_id}/export")
async def export_backup(backup_id: str):
    """导出备份文件"""
    from fastapi.responses import FileResponse

    try:
        manager = get_backup_manager()

        backup = manager.get_backup(backup_id)
        if not backup:
            raise HTTPException(status_code=404, detail=f"备份不存在: {backup_id}")

        backup_path = backup.path
        if not backup_path or not backup_path.exists():
            raise HTTPException(status_code=404, detail="备份文件不存在")

        return FileResponse(
            path=backup_path, filename=f"cxhms_backup_{backup_id}.zip", media_type="application/zip"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出备份失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
