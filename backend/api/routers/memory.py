from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.exceptions import MemoryOperationError
from backend.core.logging_config import get_contextual_logger
from backend.core.memory.secondary_router import SecondaryInstruction

router = APIRouter()
logger = get_contextual_logger(__name__)


class MemoryCreateRequest(BaseModel):
    """创建记忆请求"""

    content: str
    type: str = "long_term"
    importance: int = 3
    tags: List[str] = []
    metadata: Dict = {}
    permanent: bool = False
    workspace_id: str = "default"


class MemoryUpdateRequest(BaseModel):
    """更新记忆请求"""

    content: Optional[str] = None
    importance: Optional[int] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict] = None


class MemorySearchRequest(BaseModel):
    """搜索记忆请求"""

    query: Optional[str] = None
    type: Optional[str] = None
    memory_type: Optional[str] = None
    tags: Optional[List[str]] = None
    time_range: Optional[str] = None
    limit: int = 10
    offset: int = 0
    include_deleted: bool = False
    workspace_id: str = "default"
    agent_id: str = "default"


@router.get("/memories/agents")
async def list_agent_memory_tables():
    """获取所有Agent的记忆表列表"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        conn = memory_mgr._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT agent_id, table_name, created_at 
            FROM agent_memory_tables 
            ORDER BY created_at DESC
        """
        )
        rows = cursor.fetchall()
        conn.close()

        agents = []
        for row in rows:
            agents.append({"agent_id": row[0], "table_name": row[1], "created_at": row[2]})

        # 添加默认Agent
        agents.insert(0, {"agent_id": "default", "table_name": "memories", "created_at": None})

        return {"status": "success", "agents": agents, "total": len(agents)}
    except Exception as e:
        logger.error(f"获取Agent记忆表列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories")
async def list_memories(
    workspace_id: str = "default",
    type: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    agent_id: str = "default",
):
    """列出记忆"""
    from backend.api.app import get_memory_manager

    actual_type = type or memory_type

    try:
        memory_mgr = get_memory_manager()

        # 处理永久记忆类型
        if actual_type == "permanent":
            memories = memory_mgr.get_permanent_memories(limit=limit, offset=offset)
            # 统一字段名：importance_score -> importance
            normalized_memories = []
            for m in memories:
                normalized_memories.append(
                    {
                        "id": m.get("id"),
                        "content": m.get("content"),
                        "type": "permanent",
                        "importance": m.get("importance_score", 3),
                        "tags": m.get("tags", []),
                        "created_at": m.get("created_at"),
                        "updated_at": m.get("updated_at"),
                        "is_archived": False,
                        "metadata": m.get("metadata", {}),
                        "emotion_score": m.get("emotion_score", 0),
                        "source": m.get("source", "user"),
                        "verified": m.get("verified", True),
                    }
                )
            return {
                "status": "success",
                "memories": normalized_memories,
                "total": len(normalized_memories),
            }

        # 普通记忆查询
        memories = memory_mgr.search_memories(
            memory_type=actual_type,
            limit=limit,
            offset=offset,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        return {"status": "success", "memories": memories, "total": len(memories)}
    except MemoryOperationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"列出记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/memories")
async def create_memory(request: MemoryCreateRequest):
    from backend.api.app import get_memory_manager
    from backend.core.memory.emotion import get_emotion_for_decay

    try:
        memory_mgr = get_memory_manager()
        emotion_score = get_emotion_for_decay(request.content)

        memory_id = memory_mgr.write_memory(
            content=request.content,
            memory_type=request.type,
            importance=request.importance,
            tags=request.tags,
            metadata=request.metadata,
            permanent=request.permanent,
            emotion_score=emotion_score,
            workspace_id=request.workspace_id,
        )

        return {"status": "success", "memory_id": memory_id, "message": "记忆创建成功"}
    except MemoryOperationError as e:
        logger.error(f"创建记忆失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.warning(f"创建记忆参数错误: {e}")
        raise HTTPException(status_code=400, detail=f"参数错误: {str(e)}")
    except Exception as e:
        logger.error(f"创建记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/memories/{memory_id}")
async def get_memory(memory_id: int):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memory = memory_mgr.get_memory(memory_id)

        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")

        return {"status": "success", "memory": memory}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/memories/{memory_id}")
async def update_memory(memory_id: int, request: MemoryUpdateRequest):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        success = memory_mgr.update_memory(
            memory_id=memory_id,
            new_content=request.content,
            new_importance=request.importance,
            new_tags=request.tags,
            new_metadata=request.metadata,
        )

        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在或更新失败")

        return {"status": "success", "message": "记忆更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, soft_delete: bool = False):
    """删除记忆（默认硬删除）"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        success = memory_mgr.delete_memory(memory_id, soft_delete=soft_delete)

        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")

        return {"status": "success", "message": "记忆删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/search")
async def search_memories(request: MemorySearchRequest):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        actual_type = request.type or request.memory_type
        memories = memory_mgr.search_memories(
            query=request.query,
            memory_type=actual_type,
            tags=request.tags,
            time_range=request.time_range,
            limit=request.limit,
            offset=request.offset,
            include_deleted=request.include_deleted,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
        )

        return {"status": "success", "memories": memories, "total": len(memories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/rag")
async def rag_search(query: str, workspace_id: str = "default", limit: int = 5):
    """RAG搜索"""
    from backend.api.app import get_memory_manager
    from backend.core.exceptions import VectorStoreError

    try:
        memory_mgr = get_memory_manager()

        if memory_mgr.is_vector_search_enabled():
            results = await memory_mgr.hybrid_search(
                query=query, limit=limit, workspace_id=workspace_id
            )
        else:
            results = memory_mgr.search_memories(
                query=query, limit=limit, workspace_id=workspace_id
            )

        return {"status": "success", "query": query, "results": results, "total": len(results)}
    except VectorStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"RAG搜索失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/memories/stats")
async def get_memory_stats(workspace_id: str = "default"):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        stats = memory_mgr.get_statistics(workspace_id)

        return {"status": "success", "statistics": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/permanent")
async def create_permanent_memory(
    content: str,
    tags: List[str] = None,
    metadata: Dict = None,
    emotion_score: float = 0.0,
    source: str = "user",
):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memory_id = memory_mgr.write_permanent_memory(
            content=content,
            tags=tags or [],
            metadata=metadata or {},
            emotion_score=emotion_score,
            source=source,
            is_from_main=True,
        )

        return {"status": "success", "memory_id": memory_id, "message": "永久记忆创建成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/permanent/{memory_id}")
async def get_permanent_memory(memory_id: int):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memory = memory_mgr.get_permanent_memory(memory_id)

        if not memory:
            raise HTTPException(status_code=404, detail="永久记忆不存在")

        return {"status": "success", "memory": memory}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/permanent")
async def list_permanent_memories(limit: int = 20, offset: int = 0, tags: List[str] = []):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memories = memory_mgr.get_permanent_memories(
            limit=limit, offset=offset, tags=tags if tags else None
        )

        return {"status": "success", "memories": memories, "total": len(memories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/memories/permanent/{memory_id}")
async def update_permanent_memory(
    memory_id: int, content: str = None, tags: List[str] = None, metadata: Dict = None
):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        success = memory_mgr.update_permanent_memory(
            memory_id=memory_id, content=content, tags=tags, metadata=metadata
        )

        if not success:
            raise HTTPException(status_code=404, detail="永久记忆不存在或更新失败")

        return {"status": "success", "message": "永久记忆更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memories/permanent/{memory_id}")
async def delete_permanent_memory(memory_id: int):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        success = memory_mgr.delete_permanent_memory(memory_id, is_from_main=True)

        if not success:
            raise HTTPException(status_code=404, detail="永久记忆不存在")

        return {"status": "success", "message": "永久记忆删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/3d")
async def search_memories_3d(
    query: str = None,
    memory_type: str = None,
    tags: List[str] = [],
    limit: int = 10,
    weights: List[float] = [0.35, 0.25, 0.4],
    workspace_id: str = "default",
):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if len(weights) != 3:
            raise HTTPException(status_code=400, detail="权重必须包含3个值")

        memories = memory_mgr.search_memories_3d(
            query=query,
            memory_type=memory_type,
            tags=tags if tags else None,
            limit=limit,
            weights=tuple(weights),
            workspace_id=workspace_id,
        )

        return {
            "status": "success",
            "memories": memories,
            "total": len(memories),
            "applied_weights": {
                "importance": weights[0],
                "time": weights[1],
                "relevance": weights[2],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/recall/{memory_id}")
async def recall_memory(memory_id: int, emotion_intensity: float = 0.0):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memory = memory_mgr.recall_memory(memory_id, emotion_intensity)

        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")

        return {"status": "success", "memory": memory, "message": "记忆召回成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/batch/write")
async def batch_write_memories(memories: List[Dict], raise_on_error: bool = False):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        result = memory_mgr.batch_write_memories(memories, raise_on_error)

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""

    ids: List[int]
    data: Dict[str, Any]  # { content?, tags?, importance? }
    agent_id: str = "default"


@router.post("/memories/batch/update")
async def batch_update_memories(request: BatchUpdateRequest):
    """批量更新记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        # 将前端格式转换为后端格式
        updates = []
        for memory_id in request.ids:
            update_item = {"memory_id": memory_id}
            if "content" in request.data:
                update_item["content"] = request.data["content"]
            if "tags" in request.data:
                update_item["tags"] = request.data["tags"]
            if "importance" in request.data:
                update_item["importance"] = request.data["importance"]
            updates.append(update_item)

        result = memory_mgr.batch_update_memories(updates, agent_id=request.agent_id)

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BatchIdsRequest(BaseModel):
    """批量操作请求"""

    ids: List[int]
    agent_id: str = "default"


class BatchTagsRequest(BaseModel):
    """批量标签更新请求"""

    ids: List[int]
    tags: List[str]
    operation: str = "add"
    agent_id: str = "default"


@router.post("/memories/batch/delete")
async def batch_delete_memories(
    request: BatchIdsRequest, soft_delete: bool = False, raise_on_error: bool = False
):
    """批量删除记忆（默认硬删除）"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        result = memory_mgr.batch_delete_memories(
            request.ids, soft_delete, raise_on_error, request.agent_id
        )

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/batch/tags")
async def batch_update_memory_tags(request: BatchTagsRequest):
    """批量更新记忆标签

    Args:
        request: 包含ids(记忆ID列表), tags(标签列表), operation(操作类型), agent_id
    """
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        result = memory_mgr.batch_update_tags(
            memory_ids=request.ids,
            tags=request.tags,
            operation=request.operation,
            agent_id=request.agent_id,
        )

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/batch/archive")
async def batch_archive_memories(request: BatchIdsRequest):
    """批量归档记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        result = memory_mgr.batch_archive_memories(request.ids, request.agent_id)

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/batch/restore")
async def batch_restore_memories(request: BatchIdsRequest):
    """批量恢复记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        restored_count = 0
        failed_count = 0

        for memory_id in request.ids:
            try:
                success = memory_mgr.restore_memory(memory_id, request.agent_id)
                if success:
                    restored_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

        return {
            "status": "success",
            "result": {"restored_count": restored_count, "failed_count": failed_count},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BatchTagByQueryRequest(BaseModel):
    """按查询批量更新标签请求"""

    query: str
    tags: List[str]
    operation: str = "add"
    agent_id: str = "default"


@router.post("/memories/batch/tag-by-query")
async def batch_tag_by_query(request: BatchTagByQueryRequest):
    """按查询批量更新标签"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memories = memory_mgr.search_memories(
            query=request.query, limit=100, agent_id=request.agent_id
        )
        ids = [m["id"] for m in memories]

        if not ids:
            return {
                "status": "success",
                "result": {"updated_count": 0, "message": "没有找到匹配的记忆"},
            }

        result = memory_mgr.batch_update_tags(
            memory_ids=ids,
            tags=request.tags,
            operation=request.operation,
            agent_id=request.agent_id,
        )

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BatchDeleteByQueryRequest(BaseModel):
    """按查询批量删除请求"""

    query: str
    agent_id: str = "default"


@router.post("/memories/batch/delete-by-query")
async def batch_delete_by_query(request: BatchDeleteByQueryRequest):
    """按查询批量删除"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memories = memory_mgr.search_memories(
            query=request.query, limit=100, agent_id=request.agent_id
        )
        ids = [m["id"] for m in memories]

        if not ids:
            return {
                "status": "success",
                "result": {"deleted_count": 0, "message": "没有找到匹配的记忆"},
            }

        result = memory_mgr.batch_delete_memories(ids, agent_id=request.agent_id)

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BatchArchiveByQueryRequest(BaseModel):
    """按查询批量归档请求"""

    query: str
    target_level: int = 1
    agent_id: str = "default"


@router.post("/memories/batch/archive-by-query")
async def batch_archive_by_query(request: BatchArchiveByQueryRequest):
    """按查询批量归档"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memories = memory_mgr.search_memories(
            query=request.query, limit=100, agent_id=request.agent_id
        )
        ids = [m["id"] for m in memories]

        if not ids:
            return {
                "status": "success",
                "result": {"archived_count": 0, "message": "没有找到匹配的记忆"},
            }

        result = memory_mgr.batch_archive_memories(ids, request.agent_id)

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/type/{memory_type}")
async def get_memories_by_type(
    memory_type: str, limit: int = 20, workspace_id: str = "default", agent_id: str = "default"
):
    """按类型获取记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memories = memory_mgr.search_memories(
            memory_type=memory_type, limit=limit, workspace_id=workspace_id, agent_id=agent_id
        )

        return {"status": "success", "memories": memories, "count": len(memories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/search-by-tag")
async def search_by_tag(
    tag: str, limit: int = 20, workspace_id: str = "default", agent_id: str = "default"
):
    """按标签搜索记忆"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        memories = memory_mgr.search_memories(
            tags=[tag], limit=limit, workspace_id=workspace_id, agent_id=agent_id
        )

        return {"status": "success", "memories": memories, "count": len(memories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/sync-decay")
async def sync_decay_values(workspace_id: str = "default"):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        result = memory_mgr.sync_decay_values(workspace_id)

        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/decay-stats")
async def get_decay_statistics(workspace_id: str = "default"):
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        stats = memory_mgr.get_decay_statistics(workspace_id)

        return {"status": "success", "statistics": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/secondary/execute")
async def execute_secondary_command(
    command: str,
    target_id: str = None,
    target_type: str = None,
    parameters: Dict = {},
    context: Dict = {},
    priority: int = 0,
):
    from backend.api.app import get_memory_manager, get_secondary_router

    try:
        memory_mgr = get_memory_manager()
        secondary_router = get_secondary_router()

        if not secondary_router:
            raise HTTPException(status_code=503, detail="副模型路由器未初始化")

        instruction = SecondaryInstruction(
            command=command,
            target_id=target_id,
            target_type=target_type,
            parameters=parameters,
            context=context,
            priority=priority,
        )

        result = await secondary_router.execute_command(instruction, is_from_main=False)

        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/secondary/commands")
async def get_secondary_commands():
    from backend.api.app import get_secondary_router

    try:
        secondary_router = get_secondary_router()

        if not secondary_router:
            raise HTTPException(status_code=503, detail="副模型路由器未初始化")

        commands = secondary_router.get_available_commands()

        return {"status": "success", "commands": commands}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/secondary/history")
async def get_secondary_history(limit: int = 10):
    from backend.api.app import get_secondary_router

    try:
        secondary_router = get_secondary_router()

        if not secondary_router:
            raise HTTPException(status_code=503, detail="副模型路由器未初始化")

        history = secondary_router.get_execution_history(limit)

        return {"status": "success", "history": history}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SemanticSearchRequest(BaseModel):
    """语义搜索请求"""

    query: str
    limit: int = 10
    threshold: float = 0.7
    workspace_id: str = "default"


@router.post("/memories/semantic-search")
async def semantic_search(request: SemanticSearchRequest):
    """语义搜索 - 基于向量相似度的搜索"""
    from backend.api.app import get_memory_manager
    from backend.core.exceptions import VectorStoreError

    try:
        memory_mgr = get_memory_manager()

        if not memory_mgr.is_vector_search_enabled():
            raise HTTPException(status_code=503, detail="向量搜索未启用")

        results = await memory_mgr.hybrid_search(
            query=request.query, limit=request.limit, workspace_id=request.workspace_id
        )

        filtered_results = [r for r in results if r.get("score", 0) >= request.threshold]

        return {
            "status": "success",
            "query": request.query,
            "results": filtered_results,
            "total": len(filtered_results),
            "threshold": request.threshold,
        }
    except VectorStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"语义搜索失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="语义搜索失败")


@router.get("/memories/vectors/status")
async def get_vector_status():
    """获取向量数据库状态"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        enabled = memory_mgr.is_vector_search_enabled()

        result = {
            "enabled": enabled,
            "backend": None,
            "vector_count": 0,
            "sqlite_count": 0,
            "healthy": False,
            "last_sync": None,
        }

        conn = memory_mgr._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memories WHERE is_deleted = 0")
        row = cursor.fetchone()
        result["sqlite_count"] = row[0] if row else 0
        conn.close()

        if enabled:
            vector_store = memory_mgr._vector_store
            config = getattr(memory_mgr, "_vector_store_config", {})

            result["backend"] = config.get("backend", "unknown")

            if vector_store:
                try:
                    healthy = vector_store.is_available()
                    result["healthy"] = healthy

                    if healthy:
                        info = vector_store.get_collection_info()
                        if "error" not in info:
                            if "count" in info:
                                result["vector_count"] = info["count"]
                            elif "vectors_count" in info:
                                result["vector_count"] = info["vectors_count"]
                            elif "row_count" in info:
                                result["vector_count"] = info["row_count"]
                        else:
                            result["healthy"] = False
                except Exception as e:
                    logger.warning(f"获取向量存储状态失败: {e}")
                    result["healthy"] = False

        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"获取向量状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
