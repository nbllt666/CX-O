"""
Avatar 模型管理路由 - 提供 VRM/Live2D 模型上传、下载、管理 API
"""

import asyncio
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)
router = APIRouter()

# 项目根（CX-O-SERVER），基于文件位置解析，避免依赖运行时工作目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AVATARS_DIR = _PROJECT_ROOT / "data" / "avatars"
VRM_DIR = AVATARS_DIR / "vrm"
LIVE2D_DIR = AVATARS_DIR / "live2d"

ALLOWED_VRM_EXTENSIONS = {".vrm"}
ALLOWED_LIVE2D_EXTENSIONS = {".model.json", ".model3.json", ".zip"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _ensure_avatars_dirs():
    """确保 avatars 目录结构存在"""
    VRM_DIR.mkdir(parents=True, exist_ok=True)
    LIVE2D_DIR.mkdir(parents=True, exist_ok=True)


def _get_avatar_dir(avatar_type: str) -> Path:
    """根据模型类型获取存储目录"""
    if avatar_type == "vrm":
        return VRM_DIR
    elif avatar_type == "live2d":
        return LIVE2D_DIR
    else:
        raise HTTPException(status_code=400, detail=f"不支持的模型类型: {avatar_type}")


def _validate_file(filename: str, avatar_type: str) -> bool:
    """验证文件扩展名是否合法"""
    name_lower = filename.lower()
    if avatar_type == "vrm":
        return any(name_lower.endswith(ext) for ext in ALLOWED_VRM_EXTENSIONS)
    elif avatar_type == "live2d":
        return any(name_lower.endswith(ext) for ext in ALLOWED_LIVE2D_EXTENSIONS)
    return False


def _validate_avatar_id(avatar_id: str, avatar_type: str) -> None:
    """验证 avatar_id 防止路径遍历攻击

    Args:
        avatar_id: Avatar 唯一标识
        avatar_type: 模型类型 (vrm/live2d)

    Raises:
        HTTPException: 如果 avatar_id 包含非法字符或试图路径遍历
    """
    if not avatar_id or not re.match(r'^[A-Za-z0-9_-]+$', avatar_id):
        raise HTTPException(status_code=400, detail="无效的 avatar_id")

    avatar_dir = _get_avatar_dir(avatar_type)
    # 二次检查：确保拼接后的路径仍在 avatar_dir 内
    test_path = (avatar_dir / f"{avatar_id}.json").resolve()
    if not test_path.is_relative_to(avatar_dir.resolve()):
        raise HTTPException(status_code=400, detail="无效的 avatar_id")


class AvatarMetadata(BaseModel):
    """Avatar 元数据"""
    id: str
    name: str
    type: str
    size: int
    created_at: str
    updated_at: Optional[str] = None
    metadata: Optional[dict] = None


class AvatarListResponse(BaseModel):
    """Avatar 列表响应"""
    avatars: List[AvatarMetadata]
    total: int


class AvatarUploadResponse(BaseModel):
    """Avatar 上传响应"""
    status: str
    avatar: AvatarMetadata


class AvatarUpdateRequest(BaseModel):
    """Avatar 更新请求"""
    name: Optional[str] = None
    metadata: Optional[dict] = None


def _load_avatar_metadata(avatar_id: str, avatar_type: str) -> Optional[AvatarMetadata]:
    """从 JSON 文件加载 avatar 元数据"""
    _validate_avatar_id(avatar_id, avatar_type)
    avatar_dir = _get_avatar_dir(avatar_type)
    meta_path = avatar_dir / f"{avatar_id}.json"
    
    if not meta_path.exists():
        return None
    
    try:
        import json
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AvatarMetadata(**data)
    except Exception as e:
        logger.error(f"加载 avatar 元数据失败: {e}")
        return None


def _save_avatar_metadata(metadata: AvatarMetadata):
    """保存 avatar 元数据到 JSON 文件"""
    avatar_dir = _get_avatar_dir(metadata.type)
    meta_path = avatar_dir / f"{metadata.id}.json"
    
    try:
        import json
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata.model_dump(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存 avatar 元数据失败: {e}")
        raise


def _delete_avatar_files(avatar_id: str, avatar_type: str):
    """删除 avatar 的文件和元数据"""
    _validate_avatar_id(avatar_id, avatar_type)
    avatar_dir = _get_avatar_dir(avatar_type)
    
    # 删除元数据文件
    meta_path = avatar_dir / f"{avatar_id}.json"
    if meta_path.exists():
        meta_path.unlink()
    
    # 删除模型文件（支持任何扩展名）
    for ext in [".vrm", ".zip", ".model.json", ".model3.json"]:
        file_path = avatar_dir / f"{avatar_id}{ext}"
        if file_path.exists():
            file_path.unlink()
            break


def _get_model_file_path(avatar_id: str, avatar_type: str) -> Optional[Path]:
    """获取模型文件路径"""
    _validate_avatar_id(avatar_id, avatar_type)
    avatar_dir = _get_avatar_dir(avatar_type)
    
    for ext in [".vrm", ".zip", ".model.json", ".model3.json"]:
        file_path = avatar_dir / f"{avatar_id}{ext}"
        if file_path.exists():
            return file_path
    
    return None


@router.get("/avatars", response_model=AvatarListResponse)
async def list_avatars(type: Optional[str] = None):
    """获取所有已上传的模型列表"""
    try:
        _ensure_avatars_dirs()
        
        avatars = []
        
        # 扫描 VRM 目录
        if type is None or type == "vrm":
            for meta_file in VRM_DIR.glob("*.json"):
                avatar_id = meta_file.stem
                metadata = _load_avatar_metadata(avatar_id, "vrm")
                if metadata:
                    avatars.append(metadata)
        
        # 扫描 Live2D 目录
        if type is None or type == "live2d":
            for meta_file in LIVE2D_DIR.glob("*.json"):
                avatar_id = meta_file.stem
                metadata = _load_avatar_metadata(avatar_id, "live2d")
                if metadata:
                    avatars.append(metadata)
        
        # 按创建时间排序（最新的在前）
        avatars.sort(key=lambda x: x.created_at, reverse=True)
        
        return AvatarListResponse(avatars=avatars, total=len(avatars))
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取模型列表失败")


@router.post("/avatars/upload", response_model=AvatarUploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    avatar_type: str = Form(...),
):
    """上传 VRM 或 Live2D 模型文件"""
    try:
        _ensure_avatars_dirs()
        
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        
        # 验证文件类型
        if not _validate_file(file.filename, avatar_type):
            raise HTTPException(
                status_code=400, 
                detail=f"不支持的文件格式。VRM 支持: {ALLOWED_VRM_EXTENSIONS}, Live2D 支持: {ALLOWED_LIVE2D_EXTENSIONS}"
            )
        
        # C4: 分块读上传（1MB 块），边读边校验总量，避免超大请求整读进内存放大
        size = 0
        chunks = []
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件大小不能超过 {MAX_FILE_SIZE / 1024 / 1024}MB",
                )
            chunks.append(chunk)
        content = b"".join(chunks)
        
        # 生成唯一 ID
        avatar_id = str(uuid.uuid4())
        
        # 确定文件扩展名
        filename_lower = file.filename.lower()
        if filename_lower.endswith(".model3.json"):
            ext = ".model3.json"
        elif filename_lower.endswith(".model.json"):
            ext = ".model.json"
        else:
            ext = Path(file.filename).suffix.lower()
        
        # 保存文件（C4: 线程包裹阻塞写盘，避免卡事件循环）
        avatar_dir = _get_avatar_dir(avatar_type)
        file_path = avatar_dir / f"{avatar_id}{ext}"
        await asyncio.to_thread(file_path.write_bytes, content)
        
        # 创建元数据
        display_name = name or file.filename.replace(ext, "")
        metadata = AvatarMetadata(
            id=avatar_id,
            name=display_name,
            type=avatar_type,
            size=len(content),
            created_at=datetime.now().isoformat(),
            metadata={"original_filename": file.filename, "extension": ext},
        )
        
        _save_avatar_metadata(metadata)
        
        logger.info(f"模型上传成功: {avatar_id} ({display_name}, {len(content)} bytes)")
        
        return AvatarUploadResponse(status="success", avatar=metadata)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传模型失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="上传模型失败")


@router.get("/avatars/{avatar_id}", response_model=AvatarMetadata)
async def get_avatar(avatar_id: str, avatar_type: str):
    """获取单个模型的元数据"""
    try:
        metadata = _load_avatar_metadata(avatar_id, avatar_type)
        if not metadata:
            raise HTTPException(status_code=404, detail="模型不存在")
        return metadata
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模型元数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取模型元数据失败")


@router.get("/avatars/{avatar_id}/file")
async def get_avatar_file(avatar_id: str, avatar_type: str):
    """下载模型文件"""
    try:
        metadata = _load_avatar_metadata(avatar_id, avatar_type)
        if not metadata:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        file_path = _get_model_file_path(avatar_id, avatar_type)
        if not file_path or not file_path.exists():
            raise HTTPException(status_code=404, detail="模型文件不存在")
        
        # 根据文件类型设置 media_type
        ext = file_path.suffix.lower()
        if ext == ".vrm":
            media_type = "model/gltf-binary"
        elif ext == ".zip":
            media_type = "application/zip"
        else:
            media_type = "application/octet-stream"
        
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=f"{metadata.name}{ext}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载模型文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="下载模型文件失败")


@router.put("/avatars/{avatar_id}")
async def update_avatar(avatar_id: str, avatar_type: str, request: AvatarUpdateRequest):
    """更新模型元数据"""
    try:
        metadata = _load_avatar_metadata(avatar_id, avatar_type)
        if not metadata:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        if request.name is not None:
            metadata.name = request.name
        if request.metadata is not None:
            metadata.metadata = request.metadata
        
        metadata.updated_at = datetime.now().isoformat()
        
        _save_avatar_metadata(metadata)
        
        return {"status": "success", "avatar": metadata}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新模型元数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新模型元数据失败")


@router.delete("/avatars/{avatar_id}")
async def delete_avatar(avatar_id: str, avatar_type: str):
    """删除模型"""
    try:
        metadata = _load_avatar_metadata(avatar_id, avatar_type)
        if not metadata:
            raise HTTPException(status_code=404, detail="模型不存在")
        
        _delete_avatar_files(avatar_id, avatar_type)
        
        logger.info(f"模型已删除: {avatar_id}")
        
        return {"status": "success", "message": f"模型 {avatar_id} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除模型失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除模型失败")
