from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BackupType(str, Enum):
    """备份类型"""

    FULL = "full"  # 全量备份
    INCREMENTAL = "incremental"  # 增量备份
    DIFFERENTIAL = "differential"  # 差异备份


class BackupStatus(str, Enum):
    """备份状态"""

    PENDING = "pending"  # 等待中
    RUNNING = "running"  # 进行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    RESTORING = "restoring"  # 恢复中


class BackupManifest(BaseModel):
    """备份清单"""

    version: str = Field(default="1.0", description="备份格式版本")
    backup_id: str = Field(..., description="备份ID")
    backup_type: BackupType = Field(..., description="备份类型")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    description: Optional[str] = Field(default=None, description="备份描述")

    # 数据源
    sources: List[str] = Field(default_factory=list, description="备份的数据源")

    # 文件列表
    files: Dict[str, str] = Field(default_factory=dict, description="文件名 -> 校验和")

    # 统计
    total_size: int = Field(default=0, description="总大小（字节）")
    compressed_size: int = Field(default=0, description="压缩后大小")
    file_count: int = Field(default=0, description="文件数量")

    # 依赖（增量/差异备份需要）
    parent_backup_id: Optional[str] = Field(default=None, description="父备份ID")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class BackupInfo(BaseModel):
    """备份信息"""

    id: str = Field(..., description="备份ID")
    backup_type: BackupType = Field(..., description="备份类型")
    status: BackupStatus = Field(default=BackupStatus.PENDING, description="状态")

    # 时间
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")

    # 描述
    description: Optional[str] = Field(default=None, description="备份描述")

    # 路径
    path: str = Field(..., description="备份文件路径")

    # 统计
    total_size: int = Field(default=0, description="原始大小")
    compressed_size: int = Field(default=0, description="压缩后大小")
    file_count: int = Field(default=0, description="文件数量")

    # 错误信息
    error_message: Optional[str] = Field(default=None, description="错误信息")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "backup_type": self.backup_type.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "description": self.description,
            "path": self.path,
            "total_size": self.total_size,
            "compressed_size": self.compressed_size,
            "file_count": self.file_count,
            "error_message": self.error_message,
        }


class RestoreResult(BaseModel):
    """恢复结果"""

    success: bool = Field(default=False, description="是否成功")
    restored_files: int = Field(default=0, description="恢复的文件数")
    failed_files: int = Field(default=0, description="失败的文件数")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


class BackupStats(BaseModel):
    """备份统计"""

    total_backups: int = Field(default=0, description="备份总数")
    full_backups: int = Field(default=0, description="全量备份数")
    incremental_backups: int = Field(default=0, description="增量备份数")
    total_size: int = Field(default=0, description="总大小")
    oldest_backup: Optional[datetime] = Field(default=None, description="最早备份")
    latest_backup: Optional[datetime] = Field(default=None, description="最新备份")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}
