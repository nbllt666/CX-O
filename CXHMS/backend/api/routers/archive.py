"""
归档管理 API 路由
提供高级归档、去重、合并等功能
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class ArchiveRequest(BaseModel):
    """归档请求"""

    memory_id: int
    target_level: int = 1
    compress: bool = True


class MergeRequest(BaseModel):
    """合并请求"""

    memory_ids: List[int]
    strategy: str = "smart"  # smart, simple


class DeduplicateRequest(BaseModel):
    """去重检测请求"""

    memory_ids: Optional[List[int]] = None
    threshold: Optional[float] = None


class ArchiveOfArchivesRequest(BaseModel):
    """归档的归档请求"""

    target_level: int = 4


class SetDedupThresholdRequest(BaseModel):
    """设置去重阈值请求"""

    threshold: float


@router.post("/archive/memory")
async def archive_memory(request: ArchiveRequest):
    """归档单个记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not hasattr(memory_mgr, "archiver") or memory_mgr.archiver is None:
            raise HTTPException(status_code=503, detail="归档功能未启用")

        result = await memory_mgr.archiver.archive_memory(
            memory_id=request.memory_id,
            target_level=request.target_level,
            compress=request.compress,
        )

        if result is None:
            raise HTTPException(status_code=404, detail="记忆不存在或归档失败")

        return {
            "status": "success",
            "archive": result.to_dict(),
            "message": f"记忆已归档到级别 {request.target_level}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"归档记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"归档失败: {str(e)}")


@router.post("/archive/merge")
async def merge_memories(request: MergeRequest):
    """合并重复记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not hasattr(memory_mgr, "archiver") or memory_mgr.archiver is None:
            raise HTTPException(status_code=503, detail="归档功能未启用")

        if len(request.memory_ids) < 2:
            raise HTTPException(status_code=400, detail="至少需要两个记忆才能合并")

        result = await memory_mgr.archiver.merge_duplicate_memories(
            memory_ids=request.memory_ids, strategy=request.strategy
        )

        return {
            "status": "success" if result.success else "error",
            "result": {
                "success": result.success,
                "merged_memory_id": result.merged_memory_id,
                "merged_from": result.merged_from,
                "merged_content": result.merged_content,
                "merge_metadata": result.merge_metadata,
                "message": result.message,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"合并记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"合并失败: {str(e)}")


@router.post("/archive/deduplicate")
async def detect_duplicates(request: DeduplicateRequest):
    """检测重复记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if (
            not hasattr(memory_mgr, "deduplication_engine")
            or memory_mgr.deduplication_engine is None
        ):
            raise HTTPException(status_code=503, detail="去重功能未启用")

        dedup_engine = memory_mgr.deduplication_engine

        threshold = request.threshold
        if threshold is None:
            from config.settings import settings

            threshold = settings.config.memory.dedup_threshold

        groups = await dedup_engine.detect_duplicates_batch(
            memory_ids=request.memory_ids, threshold=threshold
        )

        return {
            "status": "success",
            "duplicate_groups": [group.to_dict() for group in groups],
            "total_groups": len(groups),
            "threshold": threshold,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检测重复失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检测失败: {str(e)}")


@router.get("/archive/duplicates")
async def get_duplicate_groups():
    """获取所有去重组"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if (
            not hasattr(memory_mgr, "deduplication_engine")
            or memory_mgr.deduplication_engine is None
        ):
            raise HTTPException(status_code=503, detail="去重功能未启用")

        groups = memory_mgr.deduplication_engine.get_duplicate_groups()

        return {
            "status": "success",
            "duplicate_groups": [group.to_dict() for group in groups],
            "total_groups": len(groups),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取去重组失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/archive/of-archives")
async def archive_of_archives(request: ArchiveOfArchivesRequest):
    """归档的归档 - 对已有归档进行二次压缩"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not hasattr(memory_mgr, "archiver") or memory_mgr.archiver is None:
            raise HTTPException(status_code=503, detail="归档功能未启用")

        results = await memory_mgr.archiver.archive_of_archives(archive_level=request.target_level)

        return {
            "status": "success",
            "results": results,
            "count": len(results),
            "target_level": request.target_level,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"归档的归档失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


@router.get("/archive/stats")
async def get_archive_stats():
    """获取归档统计"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not hasattr(memory_mgr, "archiver") or memory_mgr.archiver is None:
            raise HTTPException(status_code=503, detail="归档功能未启用")

        stats = memory_mgr.archiver.get_archive_stats()

        return {"status": "success", "statistics": stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取归档统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.get("/archive/levels")
async def get_archive_levels():
    """获取归档层级定义"""
    from backend.core.memory.archiver import AdvancedArchiver

    try:
        levels = {
            k: {
                "level": v.level,
                "name": v.name,
                "description": v.description,
                "compression_ratio": v.compression_ratio,
                "max_age_days": v.max_age_days,
            }
            for k, v in AdvancedArchiver.ARCHIVE_LEVELS.items()
        }

        return {"status": "success", "archive_levels": levels}

    except Exception as e:
        logger.error(f"获取归档层级失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/archive/threshold")
async def set_dedup_threshold(request: SetDedupThresholdRequest):
    """设置去重相似度阈值"""
    from backend.api.app import get_memory_manager

    try:
        if not 0.5 <= request.threshold <= 1.0:
            raise HTTPException(status_code=400, detail="阈值必须在 0.5 到 1.0 之间")

        memory_mgr = get_memory_manager()

        if hasattr(memory_mgr, "deduplication_engine") and memory_mgr.deduplication_engine:
            memory_mgr.deduplication_engine.threshold = request.threshold

        from config.settings import settings

        settings.config.memory.dedup_threshold = request.threshold

        return {
            "status": "success",
            "threshold": request.threshold,
            "message": f"去重阈值已设置为 {request.threshold}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置阈值失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"设置失败: {str(e)}")


@router.get("/archive/threshold")
async def get_dedup_threshold():
    """获取当前去重相似度阈值"""
    from config.settings import settings

    try:
        threshold = settings.config.memory.dedup_threshold

        return {"status": "success", "threshold": threshold}

    except Exception as e:
        logger.error(f"获取阈值失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/archive/auto-process")
async def auto_archive_process(
    min_age_days: int = 30, target_level: int = 1, auto_merge: bool = True
):
    """自动归档处理 - 归档旧记忆并合并重复项"""
    from datetime import datetime, timedelta

    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not hasattr(memory_mgr, "archiver") or memory_mgr.archiver is None:
            raise HTTPException(status_code=503, detail="归档功能未启用")

        results = {"archived": [], "merged": [], "errors": []}

        if auto_merge:
            from config.settings import settings

            threshold = settings.config.memory.dedup_threshold

            if hasattr(memory_mgr, "deduplication_engine") and memory_mgr.deduplication_engine:
                groups = await memory_mgr.deduplication_engine.detect_duplicates_batch(
                    threshold=threshold
                )

                for group in groups:
                    if not group.merged:
                        merge_result = await memory_mgr.archiver.merge_duplicate_memories(
                            memory_ids=group.memory_ids, strategy="smart"
                        )
                        if merge_result.success:
                            results["merged"].append(
                                {
                                    "group_id": group.group_id,
                                    "merged_memory_id": merge_result.merged_memory_id,
                                    "memory_count": len(group.memory_ids),
                                }
                            )

        cutoff_date = (datetime.now() - timedelta(days=min_age_days)).isoformat()

        old_memories = memory_mgr.search_memories(
            memory_type=None, limit=1000, include_deleted=False
        )

        for memory in old_memories:
            if memory.get("created_at", "") < cutoff_date:
                if not memory.get("archived_at"):
                    archive_result = await memory_mgr.archiver.archive_memory(
                        memory_id=memory["id"], target_level=target_level
                    )
                    if archive_result:
                        results["archived"].append(
                            {
                                "memory_id": memory["id"],
                                "archive_id": archive_result.archive_id,
                                "level": target_level,
                            }
                        )

        return {
            "status": "success",
            "results": results,
            "summary": {
                "archived_count": len(results["archived"]),
                "merged_count": len(results["merged"]),
                "error_count": len(results["errors"]),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动归档处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
