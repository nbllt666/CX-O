"""记忆端点——记忆写入、检索与二次指令应用接口。"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.api.routers._pagination import clamp_pagination
from server.config import Settings
from server.core.exceptions import MemoryOperationError
from server.core.logging_config import get_contextual_logger
from server.core.memory.secondary_router import SecondaryInstruction
from server.core.utils import run_io

router = APIRouter()
logger = get_contextual_logger(__name__)


def _collect_agent_tables(memory_mgr) -> list:
    """同步收集全部 Agent 记忆表列表（sqlite 直连 + agents.json 合并），
    供 async 热路径经 run_io 移入 IO 线程池执行。"""
    conn = None
    try:
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

        agents = []
        for row in rows:
            agents.append({"agent_id": row[0], "table_name": row[1], "created_at": row[2]})

        # 添加默认Agent
        agents.insert(0, {"agent_id": "default", "table_name": "memories", "created_at": None})

        # 合并 agents.json 中全部已注册 agent（复用 agents router 的 _load_agents）
        try:
            from server.api.routers.agents import _load_agents

            registered = _load_agents()
            known = {x["agent_id"] for x in agents}
            for reg in registered:
                aid = reg.get("id")
                if aid and aid != "default" and aid not in known:
                    agents.append(
                        {"agent_id": aid, "table_name": "memories", "created_at": None}
                    )
                    known.add(aid)
        except Exception as e:
            logger.warning(f"合并已注册 agent 到记忆表列表失败（保持现有列表）: {e}")

        agents.sort(key=lambda a: a["agent_id"] != "default")
        return agents
    finally:
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close
        # （对照 archiver.py:165-167 注释）；连接归还由池管理，无需清理。
        pass


def _count_active_memories(memory_mgr) -> int:
    """同步统计未删除记忆总数（sqlite 直连），供 async 端点经 run_io 移入
    IO 线程池执行。M-D3: 连接所有权归 MemoryManager 连接池，获取后不得
    close（对照 archiver.py:165-167 注释），归还由池管理。"""
    conn = memory_mgr._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memories WHERE is_deleted = 0")
    row = cursor.fetchone()
    return row[0] if row else 0


class MemoryCreateRequest(BaseModel):
    """创建记忆请求"""

    content: str
    type: str = "long_term"
    importance: int = 3
    tags: List[str] = Field(default_factory=list)
    metadata: Dict = Field(default_factory=dict)
    permanent: bool = False
    workspace_id: str = "default"
    agent_id: str = "default"


class MemoryUpdateRequest(BaseModel):
    """更新记忆请求"""

    content: Optional[str] = None
    importance: Optional[int] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict] = None
    agent_id: str = "default"


class MemorySearchRequest(BaseModel):
    """搜索记忆请求"""

    query: Optional[str] = None
    type: Optional[str] = None
    memory_type: Optional[str] = None
    tags: Optional[List[str]] = None
    time_range: Optional[str] = None
    # R9: 分页参数边界约束，防恶意大 limit 拖库（tuner.py:252 口径为 max(1, min(x, 100))，本端点上限 200）
    limit: int = Field(default=10, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    include_deleted: bool = False
    workspace_id: str = "default"
    agent_id: str = "default"


@router.get("/memories/agents")
async def list_agent_memory_tables():
    """获取所有Agent的记忆表列表"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        agents = await run_io(_collect_agent_tables, memory_mgr)
        return {"status": "success", "agents": agents, "total": len(agents)}
    except Exception as e:
        logger.error(f"获取Agent记忆表列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取Agent记忆表列表失败")


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
    # T-07: 分页钳制统一走 _pagination.clamp_pagination，下游 get_permanent_memories/search_memories 直传
    limit, offset = clamp_pagination(limit, offset)
    from server.dependencies import get_memory_manager

    actual_type = type or memory_type

    try:
        memory_mgr = get_memory_manager()

        # 处理永久记忆类型
        if actual_type == "permanent":
            # 经 run_io 把同步 sqlite 查询移入 IO 线程池，避免阻塞事件循环
            memories = await run_io(memory_mgr.get_permanent_memories, limit=limit, offset=offset)
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

        # 普通记忆查询（经 run_io 移入 IO 线程池，避免阻塞事件循环）
        memories = await run_io(
            memory_mgr.search_memories,
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
    from server.dependencies import get_memory_manager
    from server.core.memory.emotion import get_emotion_for_decay

    if not request.content or not request.content.strip():
        raise HTTPException(status_code=400, detail="记忆内容不能为空")

    try:
        memory_mgr = get_memory_manager()
        emotion_score = await get_emotion_for_decay(request.content)

        memory_id = await memory_mgr.write_memory_async(
            content=request.content,
            memory_type=request.type,
            importance=request.importance,
            tags=request.tags,
            metadata=request.metadata,
            permanent=request.permanent,
            emotion_score=emotion_score,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
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


@router.get("/memories/stats")
async def get_memory_stats(workspace_id: str = "default"):
    """获取记忆统计信息。"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把同步 sqlite 聚合查询移入 IO 线程池
        stats = await run_io(memory_mgr.get_statistics, workspace_id)

        return {"status": "success", "statistics": stats}
    except Exception as e:
        logger.error(f"获取记忆统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取记忆统计失败")


@router.get("/memories/diary")
async def get_diary_entries(
    limit: int = 100, workspace_id: str = "default", agent_id: str = "default"
):
    """获取日记条目，按日期分组返回

    迁移自 CXHMS: backend/api/routers/memory.py:L208-L240

    Returns:
        [{"date": "2026-06-20", "entries": [{...}, ...]}] 按日期降序
    """
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把日记检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
            memory_type="diary", limit=limit, workspace_id=workspace_id, agent_id=agent_id
        )

        grouped: Dict[str, list] = {}
        for m in memories:
            meta = m.get("metadata") or {}
            date = meta.get("date") or "未知日期"
            grouped.setdefault(date, []).append(m)

        sorted_dates = sorted(grouped.keys(), reverse=True)
        result = [{"date": d, "entries": grouped[d]} for d in sorted_dates]

        return {
            "status": "success",
            "diary_groups": result,
            "count": len(memories),
        }
    except Exception as e:
        logger.error(f"获取日记条目失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/search-by-tag")
async def search_by_tag(
    tag: str, limit: int = 20, workspace_id: str = "default", agent_id: str = "default"
):
    """按标签搜索记忆"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把标签检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
            tags=[tag], limit=limit, workspace_id=workspace_id, agent_id=agent_id
        )

        return {"status": "success", "memories": memories, "count": len(memories)}
    except Exception as e:
        logger.error(f"按标签搜索记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="按标签搜索记忆失败")


@router.get("/memories/decay-stats")
async def get_decay_statistics(workspace_id: str = "default"):
    """获取记忆衰减统计信息。"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把衰减统计的同步 sqlite 查询移入 IO 线程池
        stats = await run_io(memory_mgr.get_decay_statistics, workspace_id)

        return {"status": "success", "statistics": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memories/permanent")
async def list_permanent_memories(limit: int = 20, offset: int = 0, tags: Optional[List[str]] = None):
    """列出永久记忆。

    注意：本路由必须声明在 ``/memories/{memory_id}`` 之前，否则单段路径
    ``permanent`` 会被 ``memory_id`` 参数吞掉，导致本端点恒 422 不可达。
    """
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # G1/A11: 消除可变默认参数；空/缺省 tags 归一为 []（下游对 falsy tags 行为一致）
        tags = tags or []
        # 经 run_io 把永久记忆列表的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.get_permanent_memories,
            limit=limit, offset=offset, tags=tags
        )

        return {"status": "success", "memories": memories, "total": len(memories)}
    except Exception as e:
        logger.error(f"获取永久记忆列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取永久记忆列表失败")


@router.get("/memories/{memory_id}")
async def get_memory(memory_id: int, agent_id: str = "default"):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把单条记忆查询的同步 sqlite 移入 IO 线程池
        memory = await run_io(memory_mgr.get_memory, memory_id, agent_id=agent_id)

        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")

        return {"status": "success", "memory": memory}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取记忆失败")


@router.put("/memories/{memory_id}")
async def update_memory(memory_id: int, request: MemoryUpdateRequest):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        success = await memory_mgr.update_memory_async(
            memory_id=memory_id,
            new_content=request.content,
            new_importance=request.importance,
            new_tags=request.tags,
            new_metadata=request.metadata,
            agent_id=request.agent_id,
        )

        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在或更新失败")

        return {"status": "success", "message": "记忆更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新记忆失败")


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, soft_delete: bool = True, agent_id: str = "default"):
    """删除记忆（默认软删除，对齐 CXHMS 行为）

    统一为 soft_delete=True（软删除），更安全：
    - 误删可恢复（restore_memory）
    - 7 天后自动清理
    - 如需硬删除，显式传 soft_delete=False
    """
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        success = await memory_mgr.delete_memory_async(memory_id, soft_delete=soft_delete, agent_id=agent_id)

        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")

        return {"status": "success", "message": "记忆删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除记忆失败")


@router.post("/memories/search")
async def search_memories(request: MemorySearchRequest):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        actual_type = request.type or request.memory_type
        # 经 run_io 把搜索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
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
        logger.error(f"搜索记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="搜索记忆失败")


@router.post("/memories/rag")
async def rag_search(query: str, workspace_id: str = "default", limit: int = None, agent_id: str = "default"):
    """RAG搜索"""
    if limit is None:
        limit = Settings().config.limits.memory.rag_search_limit
    from server.dependencies import get_memory_manager
    from server.core.exceptions import VectorStoreError

    try:
        memory_mgr = get_memory_manager()

        if memory_mgr.is_vector_search_enabled():
            results = await memory_mgr.hybrid_search(
                query=query, limit=limit, workspace_id=workspace_id, agent_id=agent_id
            )
        else:
            # 向量未启用：经 run_io 把同步 sqlite 回退检索移入 IO 线程池
            results = await run_io(
                memory_mgr.search_memories,
                query=query, limit=limit, workspace_id=workspace_id, agent_id=agent_id
            )

        return {"status": "success", "query": query, "results": results, "total": len(results)}
    except VectorStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"RAG搜索失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/memories/permanent")
async def create_permanent_memory(
    content: str,
    tags: List[str] = None,
    metadata: Dict = None,
    emotion_score: float = 0.0,
    source: str = "user",
):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把永久记忆写入的同步 sqlite 操作移入 IO 线程池
        memory_id = await run_io(
            memory_mgr.write_permanent_memory,
            content=content,
            tags=tags or [],
            metadata=metadata or {},
            emotion_score=emotion_score,
            source=source,
            is_from_main=True,
        )

        return {"status": "success", "memory_id": memory_id, "message": "永久记忆创建成功"}
    except Exception as e:
        logger.error(f"创建永久记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建永久记忆失败")


@router.get("/memories/permanent/{memory_id}")
async def get_permanent_memory(memory_id: int):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把永久记忆读取的同步 sqlite 查询移入 IO 线程池
        memory = await run_io(memory_mgr.get_permanent_memory, memory_id)

        if not memory:
            raise HTTPException(status_code=404, detail="永久记忆不存在")

        return {"status": "success", "memory": memory}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取永久记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取永久记忆失败")


@router.put("/memories/permanent/{memory_id}")
async def update_permanent_memory(
    memory_id: int, content: str = None, tags: List[str] = None, metadata: Dict = None
):
    """更新指定永久记忆的内容、标签或元数据。"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把永久记忆更新的同步 sqlite 操作移入 IO 线程池
        success = await run_io(
            memory_mgr.update_permanent_memory,
            memory_id=memory_id, content=content, tags=tags, metadata=metadata
        )

        if not success:
            raise HTTPException(status_code=404, detail="永久记忆不存在或更新失败")

        return {"status": "success", "message": "永久记忆更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新永久记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新永久记忆失败")


@router.delete("/memories/permanent/{memory_id}")
async def delete_permanent_memory(memory_id: int):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把永久记忆删除的同步 sqlite 操作移入 IO 线程池
        success = await run_io(
            memory_mgr.delete_permanent_memory, memory_id, is_from_main=True
        )

        if not success:
            raise HTTPException(status_code=404, detail="永久记忆不存在")

        return {"status": "success", "message": "永久记忆删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"召回记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="召回记忆失败")


@router.post("/memories/3d")
async def search_memories_3d(
    query: str = None,
    memory_type: str = None,
    tags: List[str] = [],
    limit: int = 10,
    weights: List[float] = [0.35, 0.25, 0.4],
    workspace_id: str = "default",
):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if len(weights) != 3:
            raise HTTPException(status_code=400, detail="权重必须包含3个值")

        # 经 run_io 把三维检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories_3d,
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
async def recall_memory(memory_id: int, emotion_intensity: float = 0.0, agent_id: str = "default"):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把记忆召回的同步操作移入 IO 线程池
        memory = await run_io(
            memory_mgr.recall_memory, memory_id, emotion_intensity, agent_id=agent_id
        )

        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")

        return {"status": "success", "memory": memory, "message": "记忆召回成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memories/batch/write")
async def batch_write_memories(memories: List[Dict], raise_on_error: bool = False):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把批量写入的同步 sqlite 操作移入 IO 线程池
        #（raise_on_error 默认值保持显式传参）
        result = await run_io(memory_mgr.batch_write_memories, memories, raise_on_error)

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"批量写入记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="批量写入记忆失败")


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""

    ids: List[int]
    data: Dict[str, Any]  # { content?, tags?, importance? }
    agent_id: str = "default"


@router.post("/memories/batch/update")
async def batch_update_memories(request: BatchUpdateRequest):
    """批量更新记忆"""
    from server.dependencies import get_memory_manager

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

        # 经 run_io 把批量更新的同步 sqlite 操作移入 IO 线程池
        result = await run_io(
            memory_mgr.batch_update_memories, updates, agent_id=request.agent_id
        )

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"批量更新记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="批量更新记忆失败")


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
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把批量删除的同步 sqlite 操作移入 IO 线程池
        result = await run_io(
            memory_mgr.batch_delete_memories,
            request.ids, soft_delete, raise_on_error, request.agent_id
        )

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"批量删除记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="批量删除记忆失败")


@router.post("/memories/batch/tags")
async def batch_update_memory_tags(request: BatchTagsRequest):
    """批量更新记忆标签

    Args:
        request: 包含ids(记忆ID列表), tags(标签列表), operation(操作类型), agent_id
    """
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把批量标签更新的同步 sqlite 操作移入 IO 线程池
        result = await run_io(
            memory_mgr.batch_update_tags,
            memory_ids=request.ids,
            tags=request.tags,
            operation=request.operation,
            agent_id=request.agent_id,
        )

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"批量更新标签失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="批量更新标签失败")


@router.post("/memories/batch/archive")
async def batch_archive_memories(request: BatchIdsRequest):
    """批量归档记忆"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把批量归档的同步 sqlite 操作移入 IO 线程池
        result = await run_io(
            memory_mgr.batch_archive_memories, request.ids, request.agent_id
        )

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"批量归档记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="批量归档记忆失败")


@router.post("/memories/batch/restore")
async def batch_restore_memories(request: BatchIdsRequest):
    """批量恢复记忆"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        restored_count = 0
        failed_count = 0

        for memory_id in request.ids:
            try:
                # 逐条经 run_io 移入 IO 线程池，异常语义与同步直调一致
                success = await run_io(
                    memory_mgr.restore_memory, memory_id, request.agent_id
                )
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
        logger.error(f"批量恢复记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="批量恢复记忆失败")


class BatchTagByQueryRequest(BaseModel):
    """按查询批量更新标签请求"""

    query: str
    tags: List[str]
    operation: str = "add"
    agent_id: str = "default"


@router.post("/memories/batch/tag-by-query")
async def batch_tag_by_query(request: BatchTagByQueryRequest):
    """按查询批量更新标签"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把按查询检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
            query=request.query, limit=100, agent_id=request.agent_id
        )
        ids = [m["id"] for m in memories]

        if not ids:
            return {
                "status": "success",
                "result": {"updated_count": 0, "message": "没有找到匹配的记忆"},
            }

        # 第二步写入同样经 run_io 移入 IO 线程池（第一步 search 已包裹）
        result = await run_io(
            memory_mgr.batch_update_tags,
            memory_ids=ids,
            tags=request.tags,
            operation=request.operation,
            agent_id=request.agent_id,
        )

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"按查询批量更新标签失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="按查询批量更新标签失败")


class BatchDeleteByQueryRequest(BaseModel):
    """按查询批量删除请求"""

    query: str
    agent_id: str = "default"


@router.post("/memories/batch/delete-by-query")
async def batch_delete_by_query(request: BatchDeleteByQueryRequest):
    """按查询批量删除"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把按查询检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
            query=request.query, limit=100, agent_id=request.agent_id
        )
        ids = [m["id"] for m in memories]

        if not ids:
            return {
                "status": "success",
                "result": {"deleted_count": 0, "message": "没有找到匹配的记忆"},
            }

        # 第二步删除同样经 run_io 移入 IO 线程池（第一步 search 已包裹）
        result = await run_io(
            memory_mgr.batch_delete_memories, ids, agent_id=request.agent_id
        )

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"按查询批量删除失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="按查询批量删除失败")


class BatchArchiveByQueryRequest(BaseModel):
    """按查询批量归档请求"""

    query: str
    target_level: int = 1
    agent_id: str = "default"


@router.post("/memories/batch/archive-by-query")
async def batch_archive_by_query(request: BatchArchiveByQueryRequest):
    """按查询批量归档"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把按查询检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
            query=request.query, limit=100, agent_id=request.agent_id
        )
        ids = [m["id"] for m in memories]

        if not ids:
            return {
                "status": "success",
                "result": {"archived_count": 0, "message": "没有找到匹配的记忆"},
            }

        # 第二步归档同样经 run_io 移入 IO 线程池（第一步 search 已包裹）
        result = await run_io(memory_mgr.batch_archive_memories, ids, request.agent_id)

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"按查询批量归档失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="按查询批量归档失败")


@router.get("/memories/type/{memory_type}")
async def get_memories_by_type(
    memory_type: str, limit: int = 20, workspace_id: str = "default", agent_id: str = "default"
):
    """按类型获取记忆"""
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把按类型检索的同步 sqlite 查询移入 IO 线程池
        memories = await run_io(
            memory_mgr.search_memories,
            memory_type=memory_type, limit=limit, workspace_id=workspace_id, agent_id=agent_id
        )

        return {"status": "success", "memories": memories, "count": len(memories)}
    except Exception as e:
        logger.error(f"按类型获取记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="按类型获取记忆失败")


@router.post("/memories/sync-decay")
async def sync_decay_values(workspace_id: str = "default"):
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        # 经 run_io 把衰减值同步的批量 sqlite 写移入 IO 线程池
        result = await run_io(memory_mgr.sync_decay_values, workspace_id)

        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"同步衰减值失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="同步衰减值失败")


@router.post("/memories/secondary/execute")
async def execute_secondary_command(
    command: str,
    target_id: str = None,
    target_type: str = None,
    parameters: Dict = {},
    context: Dict = {},
    priority: int = 0,
):
    from server.dependencies import get_secondary_router

    try:
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
        logger.error(f"执行副模型命令失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="执行副模型命令失败")


@router.get("/memories/secondary/commands")
async def get_secondary_commands():
    """获取副模型可用命令列表。"""
    from server.dependencies import get_secondary_router

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
    """获取副模型指令执行历史。"""
    from server.dependencies import get_secondary_router

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
    threshold: float = 0.3
    workspace_id: str = "default"
    agent_id: str = "default"


@router.post("/memories/semantic-search")
async def semantic_search(request: SemanticSearchRequest):
    """语义搜索 - 基于向量相似度的搜索

    迁移自 CXHMS：调用纯向量搜索 semantic_search（而非 hybrid_search），
    保留 agent_id 以支持 per-agent 隔离。threshold 默认值改为 0.3（与 CXHMS 一致，更宽松）。
    """
    from server.dependencies import get_memory_manager
    from server.core.exceptions import VectorStoreError

    try:
        memory_mgr = get_memory_manager()

        if not memory_mgr.is_vector_search_enabled():
            raise HTTPException(status_code=503, detail="向量搜索未启用")

        # 调用纯向量搜索（而非 hybrid_search），保留 agent_id 以支持 agent 隔离
        results = await memory_mgr.semantic_search(
            query=request.query, limit=request.limit, agent_id=request.agent_id
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
    from server.dependencies import get_memory_manager

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

        # 经 run_io 把同步 sqlite 计数移入 IO 线程池（连接所有权归池，
        # 不再手动 close——M-D3，对照 archiver.py:165-167 注释）
        result["sqlite_count"] = await run_io(_count_active_memories, memory_mgr)

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
        raise HTTPException(status_code=500, detail="获取向量状态失败")
