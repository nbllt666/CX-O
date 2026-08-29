"""
向量数据库管理 API 路由
用于向量数据库配置、状态监控和数据管理
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from server.api.routers.admin import verify_admin_api_key
from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class VectorConfig(BaseModel):
    backend: str = "chroma"
    vector_size: int = 768
    db_path: Optional[str] = None
    collection_name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None


@router.get("/vector/config")
async def get_vector_config():
    from server.config import get_settings

    try:
        settings = get_settings()
        memory_config = settings.config.memory

        config = {
            "vector_enabled": getattr(memory_config, "vector_enabled", False),
            "vector_backend": getattr(memory_config, "vector_backend", "chroma"),
            "vector_size": 768,
        }

        backend = config["vector_backend"]
        if backend == "chroma" and hasattr(memory_config, "chroma"):
            chroma_cfg = memory_config.chroma
            config["db_path"] = getattr(chroma_cfg, "db_path", "data/chroma_db")
            config["collection_name"] = getattr(chroma_cfg, "collection_name", "memory_vectors")
            config["vector_size"] = getattr(chroma_cfg, "vector_size", 768)
        elif backend == "milvus_lite" and hasattr(memory_config, "milvus_lite"):
            milvus_cfg = memory_config.milvus_lite
            config["db_path"] = getattr(milvus_cfg, "db_path", "data/milvus_lite.db")
            config["vector_size"] = getattr(milvus_cfg, "vector_size", 768)
        elif backend in ["weaviate", "weaviate_embedded"] and hasattr(memory_config, "weaviate"):
            weaviate_cfg = memory_config.weaviate
            config["host"] = getattr(weaviate_cfg, "host", "localhost")
            config["port"] = getattr(weaviate_cfg, "port", 8080)
            config["vector_size"] = getattr(weaviate_cfg, "vector_size", 768)
            config["schema_class"] = getattr(weaviate_cfg, "schema_class", "CXOMemory")
        elif backend == "qdrant" and hasattr(memory_config, "qdrant"):
            qdrant_cfg = memory_config.qdrant
            config["host"] = getattr(qdrant_cfg, "host", "localhost")
            config["port"] = getattr(qdrant_cfg, "port", 6333)
            config["vector_size"] = getattr(qdrant_cfg, "vector_size", 768)

        return {"status": "success", "config": config}
    except Exception as e:
        logger.error(f"获取向量数据库配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取向量数据库配置失败: {str(e)}")


@router.get("/vector/status")
async def get_vector_status():
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        vector_enabled = hasattr(mm, "_vector_store") and mm._vector_store is not None

        stats = {
            "vector_enabled": vector_enabled,
            "vector_backend": getattr(mm, "_vector_store_config", {}).get("backend", "unknown") if hasattr(mm, "_vector_store_config") else "unknown",
            "connected": False,
            "collection_info": {},
        }

        if vector_enabled and mm._vector_store:
            try:
                stats["connected"] = mm._vector_store.is_available()
                stats["collection_info"] = mm._vector_store.get_collection_info()
            except Exception as e:
                stats["error"] = str(e)

        return {"status": "success", "vector_status": stats}
    except Exception as e:
        logger.error(f"获取向量数据库状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取向量数据库状态失败: {str(e)}")


@router.get("/vector/health")
async def vector_health_check():
    """向量数据库健康检查。"""
    from server.dependencies import get_memory_manager

    health = {
        "status": "unknown",
        "vector_enabled": False,
        "connected": False,
        "message": "",
    }

    try:
        mm = get_memory_manager()
        health["vector_enabled"] = hasattr(mm, "_vector_store") and mm._vector_store is not None

        if health["vector_enabled"] and mm._vector_store:
            try:
                health["connected"] = mm._vector_store.is_available()
                health["status"] = "healthy" if health["connected"] else "unhealthy"
                health["message"] = "向量数据库连接正常" if health["connected"] else "向量数据库连接失败"
            except Exception as e:
                health["status"] = "unhealthy"
                health["message"] = f"向量数据库连接失败: {str(e)}"
        else:
            health["status"] = "disabled"
            health["message"] = "向量数据库未启用"

    except Exception as e:
        health["status"] = "error"
        health["message"] = str(e)

    return health


@router.get("/vector/vectors")
async def list_vectors(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    memory_type: Optional[str] = Query(None, description="按记忆类型过滤"),
):
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        if not hasattr(mm, "_vector_store") or not mm._vector_store:
            raise HTTPException(status_code=503, detail="向量数据库未启用")

        store = mm._vector_store

        collection_info = store.get_collection_info()
        total = collection_info.get("count", 0)

        vectors = []
        if hasattr(store, "list_vectors"):
            vectors = await store.list_vectors(limit=limit, offset=offset, memory_type=memory_type)
        else:
            memories = mm.read_memories(limit=limit, offset=offset, memory_type=memory_type)
            for mem in memories:
                exists = await store.check_exists(mem["id"])
                if exists:
                    vec_data = await store.get_vector_by_id(mem["id"])
                    if vec_data:
                        vectors.append({
                            "memory_id": mem["id"],
                            "content": mem.get("content", "")[:100] + "..." if len(mem.get("content", "")) > 100 else mem.get("content", ""),
                            "memory_type": mem.get("type", "unknown"),
                            "importance": mem.get("importance", 0),
                            "created_at": mem.get("created_at", ""),
                            "has_vector": True,
                        })

        return {
            "status": "success",
            "vectors": vectors,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取向量列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取向量列表失败: {str(e)}")


@router.get("/vector/vectors/{memory_id}")
async def get_vector(memory_id: int):
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        if not hasattr(mm, "_vector_store") or not mm._vector_store:
            raise HTTPException(status_code=503, detail="向量数据库未启用")

        store = mm._vector_store
        vec_data = await store.get_vector_by_id(memory_id)

        if not vec_data:
            raise HTTPException(status_code=404, detail=f"向量不存在: {memory_id}")

        memory = mm.get_memory(memory_id)

        return {
            "status": "success",
            "vector": {
                "memory_id": memory_id,
                "vector_size": len(vec_data.get("vector", [])),
                "metadata": vec_data.get("metadata", {}),
                "memory": memory,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取向量失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取向量失败: {str(e)}")


@router.delete("/vector/vectors/{memory_id}")
async def delete_vector(memory_id: int, _: bool = Depends(verify_admin_api_key)):
    """删除向量（写路径，补挂管理员鉴权）。"""
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        if not hasattr(mm, "_vector_store") or not mm._vector_store:
            raise HTTPException(status_code=503, detail="向量数据库未启用")

        store = mm._vector_store
        success = await store.delete_by_memory_id(memory_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"向量不存在: {memory_id}")

        return {"status": "success", "message": "向量删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除向量失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除向量失败: {str(e)}")


@router.post("/vector/sync")
async def sync_vectors(_: bool = Depends(verify_admin_api_key)):
    """向量与 SQLite 同步（写路径，补挂管理员鉴权）。"""
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        if not hasattr(mm, "_vector_store") or not mm._vector_store:
            raise HTTPException(status_code=503, detail="向量数据库未启用")

        store = mm._vector_store
        result = await store.sync_with_sqlite(mm)

        return {
            "status": "success",
            "message": "向量同步完成",
            "result": {
                "total_checked": result.total_checked,
                "synced": result.synced,
                "removed": result.removed,
                "errors": result.errors,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"向量同步失败: {e}")
        raise HTTPException(status_code=500, detail=f"向量同步失败: {str(e)}")


@router.post("/vector/rebuild")
async def rebuild_vectors(_: bool = Depends(verify_admin_api_key)):
    """清空并重建向量数据库（破坏性写路径，补挂管理员鉴权）。"""
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        if not hasattr(mm, "_vector_store") or not mm._vector_store:
            raise HTTPException(status_code=503, detail="向量数据库未启用")

        store = mm._vector_store

        store.clear_collection()

        result = await store.sync_with_sqlite(mm, last_sync_time=None)

        return {
            "status": "success",
            "message": "向量重建完成",
            "result": {
                "total_checked": result.total_checked,
                "synced": result.synced,
                "removed": result.removed,
                "errors": result.errors,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"向量重建失败: {e}")
        raise HTTPException(status_code=500, detail=f"向量重建失败: {str(e)}")


@router.post("/vector/search")
async def search_vectors(
    query: str,
    limit: int = Query(10, ge=1, le=100),
    min_score: float = Query(0.5, ge=0.0, le=1.0),
    memory_type: Optional[str] = Query(None, description="按记忆类型过滤"),
):
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        if not hasattr(mm, "_vector_store") or not mm._vector_store:
            raise HTTPException(status_code=503, detail="向量数据库未启用")

        if not mm._embedding_model:
            raise HTTPException(status_code=503, detail="嵌入模型未初始化")

        embedding = await mm._embedding_model.get_embedding(query)

        store = mm._vector_store
        results = await store.search_similar(
            query_embedding=embedding,
            limit=limit,
            memory_type=memory_type,
            min_score=min_score,
        )

        enriched_results = []
        for result in results:
            memory_id = result.get("memory_id") or result.get("id")
            if memory_id:
                memory = mm.get_memory(memory_id)
                result["memory"] = memory
            enriched_results.append(result)

        return {
            "status": "success",
            "query": query,
            "results": enriched_results,
            "total": len(enriched_results),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"向量搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"向量搜索失败: {str(e)}")


@router.get("/vector/stats")
async def get_vector_stats():
    """获取向量数据库统计信息。"""
    from server.dependencies import get_memory_manager

    try:
        mm = get_memory_manager()
        vector_enabled = hasattr(mm, "_vector_store") and mm._vector_store is not None

        stats = {
            "vector_enabled": vector_enabled,
            "total_vectors": 0,
            "collection_info": {},
            "backend": "unknown",
        }

        if vector_enabled and mm._vector_store:
            store = mm._vector_store
            collection_info = store.get_collection_info()
            stats["collection_info"] = collection_info
            stats["total_vectors"] = collection_info.get("count", 0)
            stats["backend"] = type(store).__name__

            if hasattr(mm, "_vector_store_config"):
                stats["backend"] = mm._vector_store_config.get("backend", stats["backend"])

        memories = mm.search_memories(limit=10000)
        stats["total_memories"] = len(memories)
        stats["indexed_ratio"] = (
            stats["total_vectors"] / stats["total_memories"] if stats["total_memories"] > 0 else 0
        )

        return {"status": "success", "stats": stats}
    except Exception as e:
        logger.error(f"获取向量统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取向量统计失败: {str(e)}")
