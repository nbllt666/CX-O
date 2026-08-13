"""
图数据库 API 路由

迁移自 CXHMS（agent_id per-agent 隔离），保留 CX-O 独有端点：
- /status：前端 GraphCard/GraphDataPage 期望的复合状态格式
- /config：配置查询
- /semantic/query-hops：多跳语义查询
- /semantic/path-constrained：路径约束语义搜索
- /export/json, /export/graphml, /export/dot：图导出

所有端点支持 agent_id 参数（默认 "default"），通过 per-agent 注册表实现隔离。
详见 .trae/documents/20260720_模块0_从CXHMS迁移图数据库.md
"""

import json
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from server.core.graph import GraphDatabase
from server.core.graph.models import (
    GraphNode, GraphEdge,
    NodeCreate, NodeUpdate, EdgeCreate, EdgeUpdate
)
from server.core.graph.visualization import GraphExporter
from server.core.graph.semantic_query import SemanticQueryManager
from server.core.graph.monitoring import GraphMonitor
from server.dependencies import _get_or_create_graph_database

router = APIRouter(tags=["graph"])


def _resolve_graph_database(agent_id: str) -> GraphDatabase:
    """按 agent_id 解析对应图数据库实例（按需创建）。

    首次访问时通过 _get_or_create_graph_database 触发实例化与初始化，
    避免启动时全局初始化的开销，同时保证 REST API 可用。
    """
    try:
        return _get_or_create_graph_database(agent_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图数据库初始化失败: {e}")


# ============ Request Models ============

class NodeCreateRequest(BaseModel):
    """创建节点请求"""
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    text_content: Optional[str] = None
    agent_id: str = "default"


class NodeUpdateRequest(BaseModel):
    """更新节点请求"""
    type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None


class EdgeCreateRequest(BaseModel):
    """创建边请求"""
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    text_content: Optional[str] = None
    agent_id: str = "default"


class EdgeUpdateRequest(BaseModel):
    """更新边请求"""
    relation_type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None


class SemanticSearchRequest(BaseModel):
    """语义搜索请求"""
    query: str
    node_type: Optional[str] = None
    limit: int = 10
    agent_id: str = "default"


class HybridSearchRequest(BaseModel):
    """混合搜索请求"""
    query: str
    node_type: Optional[str] = None
    properties_filter: Optional[Dict[str, Any]] = None
    limit: int = 10
    agent_id: str = "default"


class TraversalBFSRequest(BaseModel):
    """BFS 遍历请求"""
    start_id: str
    max_depth: int = 10
    node_type_filter: Optional[str] = None
    agent_id: str = "default"


class TraversalDFSRequest(BaseModel):
    """DFS 遍历请求"""
    start_id: str
    max_depth: int = 10
    node_type_filter: Optional[str] = None
    agent_id: str = "default"


class SemanticQueryHopsRequest(BaseModel):
    """多跳语义查询请求（CX-O 独有）"""
    start_node_id: str
    query: str
    hops: int = 2
    limit: int = 10
    direction: str = "both"
    agent_id: str = "default"


class PathConstrainedSearchRequest(BaseModel):
    """路径约束语义搜索请求（CX-O 独有）"""
    start_node_id: str
    end_node_id: str
    query: str
    max_path_length: int = 5
    limit: int = 10
    agent_id: str = "default"


# ============ Node Endpoints ============
# 注意：FastAPI 路由按定义顺序匹配，/nodes/search 和 /nodes/batch 必须在 /nodes/{node_id} 之前定义，
# 否则 "search"/"batch" 会被当作 node_id 匹配到 GET /nodes/{node_id}，导致返回 404 "节点不存在"。

@router.post("/nodes", response_model=GraphNode)
async def create_node(request: NodeCreateRequest, agent_id: str = Query("default")):
    """创建节点"""
    graph = _resolve_graph_database(agent_id)
    node_data = NodeCreate(
        type=request.type,
        properties=request.properties,
        text_content=request.text_content,
    )
    return graph.nodes.create(node_data, agent_id=agent_id)


@router.get("/nodes/search")
async def search_nodes(
    node_type: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    agent_id: str = Query("default"),
):
    """搜索节点"""
    graph = _resolve_graph_database(agent_id)
    result = graph.nodes.search(node_type=node_type, limit=limit, offset=offset, agent_id=agent_id)
    return result


@router.post("/nodes/batch")
async def batch_create_nodes(requests: List[NodeCreateRequest], agent_id: str = Query("default")):
    """批量创建节点"""
    graph = _resolve_graph_database(agent_id)
    nodes_data = [
        NodeCreate(type=r.type, properties=r.properties, text_content=r.text_content, agent_id=r.agent_id)
        for r in requests
    ]
    nodes = graph.nodes.batch_create(nodes_data)
    return {"created": len(nodes), "nodes": nodes}


@router.get("/nodes/{node_id}", response_model=Optional[GraphNode])
async def get_node(node_id: str, agent_id: str = Query("default")):
    """获取节点"""
    graph = _resolve_graph_database(agent_id)
    node = graph.nodes.get(node_id, agent_id=agent_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    return node


@router.put("/nodes/{node_id}", response_model=Optional[GraphNode])
async def update_node(node_id: str, request: NodeUpdateRequest, agent_id: str = Query("default")):
    """更新节点"""
    graph = _resolve_graph_database(agent_id)
    update_data = NodeUpdate(
        type=request.type,
        properties=request.properties,
        text_content=request.text_content,
    )
    node = graph.nodes.update(node_id, update_data, agent_id=agent_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    return node


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str, cascade: bool = True, agent_id: str = Query("default")):
    """删除节点"""
    graph = _resolve_graph_database(agent_id)
    graph.nodes.delete(node_id, cascade=cascade, agent_id=agent_id)
    return {"status": "ok", "message": f"节点 {node_id} 已删除"}


@router.get("/nodes/{node_id}/neighbors")
async def get_neighbors(
    node_id: str,
    max_depth: int = Query(default=1, ge=1, le=10),
    direction: str = Query(default="both", pattern="^(outgoing|incoming|both)$"),
    agent_id: str = Query("default"),
):
    """获取邻居节点"""
    graph = _resolve_graph_database(agent_id)
    neighbors = graph.traversal.get_neighbors(node_id, max_depth=max_depth, direction=direction, agent_id=agent_id)
    return {
        "node_id": node_id,
        "neighbors": [
            {"node": node.to_dict() if hasattr(node, 'to_dict') else node, "edges": [e.to_dict() if hasattr(e, 'to_dict') else e for e in edges]}
            for node, edges in neighbors
        ]
    }


# ============ Edge Endpoints ============
# 注意：/edges/search 必须在 /edges/{edge_id} 之前定义，避免 "search" 被当作 edge_id 匹配。

@router.post("/edges", response_model=GraphEdge)
async def create_edge(request: EdgeCreateRequest, agent_id: str = Query("default")):
    """创建边"""
    graph = _resolve_graph_database(agent_id)
    edge_data = EdgeCreate(
        source_id=request.source_id,
        target_id=request.target_id,
        relation_type=request.relation_type,
        properties=request.properties,
        text_content=request.text_content,
    )
    try:
        return graph.edges.create(edge_data, agent_id=request.agent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/edges/search")
async def search_edges(
    relation_type: Optional[str] = None,
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    agent_id: str = Query("default"),
):
    """搜索边"""
    graph = _resolve_graph_database(agent_id)
    result = graph.edges.search(
        relation_type=relation_type,
        source_id=source_id,
        target_id=target_id,
        limit=limit,
        offset=offset,
        agent_id=agent_id,
    )
    return result


@router.get("/edges/{edge_id}", response_model=Optional[GraphEdge])
async def get_edge(edge_id: str, agent_id: str = Query("default")):
    """获取边"""
    graph = _resolve_graph_database(agent_id)
    edge = graph.edges.get(edge_id, agent_id=agent_id)
    if not edge:
        raise HTTPException(status_code=404, detail="边不存在")
    return edge


@router.put("/edges/{edge_id}", response_model=Optional[GraphEdge])
async def update_edge(edge_id: str, request: EdgeUpdateRequest, agent_id: str = Query("default")):
    """更新边"""
    graph = _resolve_graph_database(agent_id)
    update_data = EdgeUpdate(
        relation_type=request.relation_type,
        properties=request.properties,
        text_content=request.text_content,
    )
    edge = graph.edges.update(edge_id, update_data, agent_id=agent_id)
    if not edge:
        raise HTTPException(status_code=404, detail="边不存在")
    return edge


@router.delete("/edges/{edge_id}")
async def delete_edge(edge_id: str, agent_id: str = Query("default")):
    """删除边"""
    graph = _resolve_graph_database(agent_id)
    graph.edges.delete(edge_id, agent_id=agent_id)
    return {"status": "ok", "message": f"边 {edge_id} 已删除"}


# ============ Traversal Endpoints ============

@router.post("/traverse/bfs")
async def traverse_bfs(request: TraversalBFSRequest):
    """广度优先遍历"""
    graph = _resolve_graph_database(request.agent_id)
    nodes = graph.traversal.bfs_traverse(
        start_id=request.start_id,
        max_depth=request.max_depth,
        node_type_filter=request.node_type_filter,
        agent_id=request.agent_id,
    )
    return {"start_id": request.start_id, "nodes": [n.to_dict() if hasattr(n, 'to_dict') else n for n in nodes]}


@router.post("/traverse/dfs")
async def traverse_dfs(request: TraversalDFSRequest):
    """深度优先遍历"""
    graph = _resolve_graph_database(request.agent_id)
    nodes = graph.traversal.dfs_traverse(
        start_id=request.start_id,
        max_depth=request.max_depth,
        node_type_filter=request.node_type_filter,
        agent_id=request.agent_id,
    )
    return {"start_id": request.start_id, "nodes": [n.to_dict() if hasattr(n, 'to_dict') else n for n in nodes]}


@router.get("/paths/shortest")
async def shortest_path(
    start_id: str,
    end_id: str,
    max_length: int = Query(default=10, ge=1, le=50),
    agent_id: str = Query("default"),
):
    """最短路径"""
    graph = _resolve_graph_database(agent_id)
    path = graph.traversal.shortest_path(start_id, end_id, max_length, agent_id=agent_id)
    if not path:
        raise HTTPException(status_code=404, detail="路径不存在")
    return {
        "start_id": start_id,
        "end_id": end_id,
        "path": path.path,
        "length": path.length,
        "edges": [e.to_dict() if hasattr(e, 'to_dict') else e for e in path.edges],
    }


# ============ Semantic Search Endpoints ============

@router.post("/semantic/search")
async def semantic_search(request: SemanticSearchRequest):
    """语义搜索"""
    graph = _resolve_graph_database(request.agent_id)
    results = graph.semantic.search(
        query=request.query,
        node_type=request.node_type,
        limit=request.limit,
        agent_id=request.agent_id,
    )
    return {
        "query": request.query,
        "results": [
            {
                "node_id": r.node_id if hasattr(r, 'node_id') else r.get('node_id'),
                "node_type": r.node_type if hasattr(r, 'node_type') else r.get('node_type'),
                "text_content": r.text_content if hasattr(r, 'text_content') else r.get('text_content'),
                "score": r.score if hasattr(r, 'score') else r.get('score', 0),
            }
            for r in results
        ]
    }


@router.post("/semantic/hybrid")
async def hybrid_search(request: HybridSearchRequest):
    """混合搜索"""
    graph = _resolve_graph_database(request.agent_id)
    results = graph.hybrid.filtered_semantic_search(
        query=request.query,
        node_type=request.node_type,
        properties_filter=request.properties_filter,
        limit=request.limit,
        agent_id=request.agent_id,
    )
    return {
        "query": request.query,
        "results": [
            {
                "node_id": r.node_id if hasattr(r, 'node_id') else r.get('node_id'),
                "node_type": r.node_type if hasattr(r, 'node_type') else r.get('node_type'),
                "text_content": r.text_content if hasattr(r, 'text_content') else r.get('text_content'),
                "score": r.score if hasattr(r, 'score') else r.get('score', 0),
            }
            for r in results
        ]
    }


@router.get("/semantic/neighbors/{node_id}")
async def semantic_neighbors(
    node_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    depth: int = Query(default=1, ge=1, le=5),
    agent_id: str = Query("default"),
):
    """语义邻居"""
    graph = _resolve_graph_database(agent_id)
    results = graph.hybrid.semantic_neighbors(node_id=node_id, limit=limit, depth=depth, agent_id=agent_id)
    return {
        "node_id": node_id,
        "results": [
            {
                "node_id": r.node_id if hasattr(r, 'node_id') else r.get('node_id'),
                "score": r.score if hasattr(r, 'score') else r.get('score', 0),
            }
            for r in results
        ]
    }


# ============ Health / Status / Metrics Endpoints ============

@router.get("/health")
async def health_check(agent_id: str = Query("default")):
    """健康检查"""
    graph = _resolve_graph_database(agent_id)
    status = graph.health_check()
    return status


@router.get("/status")
async def get_graph_status(agent_id: str = Query("default")):
    """综合状态：连接 + 健康检查 + 统计（CX-O 独有，前端 GraphCard/GraphDataPage 调用）。

    返回前端期望的格式：
    {connected, graph_enabled, message, libraries: {user/thing/concept/event: {entity_count, relation_count}}, database_path}
    """
    graph = _resolve_graph_database(agent_id)
    health = graph.health_check()
    monitor = GraphMonitor(graph.db)
    stats = monitor.get_graph_stats(agent_id=agent_id)

    edge_count = stats.get("edge_count", 0)
    node_types = stats.get("node_types", {}) or {}

    libraries: Dict[str, Dict[str, int]] = {
        "user": {"entity_count": 0, "relation_count": 0},
        "thing": {"entity_count": 0, "relation_count": 0},
        "concept": {"entity_count": 0, "relation_count": 0},
        "event": {"entity_count": 0, "relation_count": 0},
    }
    for lib_name in libraries:
        if lib_name in node_types:
            libraries[lib_name]["entity_count"] = int(node_types[lib_name])
    if edge_count > 0:
        libraries["user"]["relation_count"] = edge_count

    return {
        "connected": health.get("overall") == "healthy",
        "graph_enabled": True,
        "message": health.get("overall", "unknown"),
        "libraries": libraries,
        "database_path": graph.config.database_path,
    }


@router.get("/metrics")
async def get_metrics(agent_id: str = Query("default")):
    """获取性能指标"""
    graph = _resolve_graph_database(agent_id)
    monitor = GraphMonitor(graph.db)
    return monitor.get_metrics()


@router.get("/stats")
async def get_graph_stats(agent_id: str = Query("default")):
    """获取图统计信息"""
    graph = _resolve_graph_database(agent_id)
    monitor = GraphMonitor(graph.db)
    return monitor.get_graph_stats(agent_id=agent_id)


# ============ Algorithm Endpoints ============

@router.get("/algorithm/pagerank")
async def get_pagerank(
    damping: float = Query(default=0.85, ge=0.0, le=1.0),
    max_iterations: int = Query(default=100, ge=1, le=1000),
    agent_id: str = Query("default"),
):
    """PageRank 算法"""
    graph = _resolve_graph_database(agent_id)
    scores = graph.traversal.pagerank(damping=damping, max_iterations=max_iterations, agent_id=agent_id)
    return {"damping": damping, "scores": scores}


@router.get("/algorithm/important-nodes")
async def get_important_nodes(
    limit: int = Query(default=10, ge=1, le=100),
    agent_id: str = Query("default"),
):
    """获取最重要的节点"""
    graph = _resolve_graph_database(agent_id)
    nodes = graph.traversal.get_important_nodes(limit=limit, agent_id=agent_id)
    return {
        "limit": limit,
        "nodes": [
            {
                "node": n["node"].to_dict() if hasattr(n["node"], 'to_dict') else n["node"],
                "pagerank": n["pagerank"],
            }
            for n in nodes
        ]
    }


@router.get("/algorithm/communities")
async def get_communities(
    method: str = Query(default="lpa", pattern="^(lpa|louvain)$"),
    agent_id: str = Query("default"),
):
    """社区发现"""
    graph = _resolve_graph_database(agent_id)
    communities = graph.traversal.community_detection(method=method, agent_id=agent_id)
    return {
        "method": method,
        "communities": communities,
    }


@router.get("/algorithm/community-stats")
async def get_community_stats(
    method: str = Query(default="lpa", pattern="^(lpa|louvain)$"),
    agent_id: str = Query("default"),
):
    """获取社区统计信息"""
    graph = _resolve_graph_database(agent_id)
    stats = graph.traversal.get_community_stats(agent_id=agent_id)
    return {
        "method": method,
        "stats": stats,
    }


# ============ Semantic Query Endpoints (CX-O 独有) ============

@router.post("/semantic/query-hops")
async def semantic_query_hops(request: SemanticQueryHopsRequest):
    """多跳语义查询（CX-O 独有）"""
    graph = _resolve_graph_database(request.agent_id)
    semantic_query_mgr = SemanticQueryManager(graph.db)
    results = semantic_query_mgr.semantic_query_with_hops(
        start_node_id=request.start_node_id,
        query=request.query,
        hops=request.hops,
        limit=request.limit,
        direction=request.direction,
    )
    return {
        "start_node_id": request.start_node_id,
        "query": request.query,
        "hops": request.hops,
        "results": [
            {
                "node": r["node"].to_dict() if hasattr(r["node"], 'to_dict') else r["node"],
                "similarity": r["similarity"],
                "path": r["path"],
            }
            for r in results
        ]
    }


@router.post("/semantic/path-constrained")
async def path_constrained_search(request: PathConstrainedSearchRequest):
    """路径约束的语义搜索（CX-O 独有）"""
    graph = _resolve_graph_database(request.agent_id)
    semantic_query_mgr = SemanticQueryManager(graph.db)
    results = semantic_query_mgr.path_constrained_semantic_search(
        start_node_id=request.start_node_id,
        end_node_id=request.end_node_id,
        query=request.query,
        max_path_length=request.max_path_length,
        limit=request.limit,
    )
    return {
        "start_node_id": request.start_node_id,
        "end_node_id": request.end_node_id,
        "query": request.query,
        "results": [
            {
                "node": r["node"].to_dict() if hasattr(r["node"], 'to_dict') else r["node"],
                "similarity": r["similarity"],
                "path": r["path"],
            }
            for r in results
        ]
    }


# ============ Export Endpoints (CX-O 独有) ============

@router.get("/export/json")
async def export_json(agent_id: str = Query("default")):
    """导出为 JSON 格式"""
    graph = _resolve_graph_database(agent_id)
    exporter = GraphExporter(graph.db)
    json_str = exporter.export_json()
    return {"format": "json", "data": json.loads(json_str)}


@router.get("/export/graphml")
async def export_graphml(
    file_path: str = Query(default="graph_export.graphml"),
    agent_id: str = Query("default"),
):
    """导出为 GraphML 格式"""
    graph = _resolve_graph_database(agent_id)
    exporter = GraphExporter(graph.db)
    exporter.export_graphml(file_path)
    return {"format": "graphml", "file_path": file_path, "status": "exported"}


@router.get("/export/dot")
async def export_dot(
    file_path: str = Query(default="graph_export.dot"),
    agent_id: str = Query("default"),
):
    """导出为 DOT 格式"""
    graph = _resolve_graph_database(agent_id)
    exporter = GraphExporter(graph.db)
    exporter.export_dot(file_path)
    return {"format": "dot", "file_path": file_path, "status": "exported"}


# ============ Config Endpoint (CX-O 独有) ============

@router.get("/config")
async def get_graph_config_endpoint(agent_id: str = Query("default")):
    """获取图数据库配置（CX-O 独有）"""
    graph = _resolve_graph_database(agent_id)
    config = graph.config
    return {
        "status": "success",
        "config": {
            "database_path": config.database_path,
            "auto_create_schema": config.auto_create_schema,
            "pool_size": config.pool_size,
            "timeout": config.timeout,
            "weaviate": {
                "url": config.weaviate.url,
                "api_key": "***" if config.weaviate.api_key else None,
                "vector_dim": config.weaviate.vector_dim,
                "batch_size": config.weaviate.batch_size,
                "ef_construction": config.weaviate.ef_construction,
                "max_connections": config.weaviate.max_connections,
            },
            "embedding": {
                "model": config.embedding.model,
                "batch_size": config.embedding.batch_size,
                "device": config.embedding.device,
                "cache_folder": config.embedding.cache_folder,
            }
        }
    }
