"""
图数据库管理 API 路由
用于 Neo4j 配置、状态监控和管理
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    max_connection_pool_size: int = 50


class GraphLibraryConfig(BaseModel):
    enabled: bool = True
    label_prefix: str = ""


class GraphConfig(BaseModel):
    graph_enabled: bool = True
    graph_backend: str = "neo4j"
    neo4j: Neo4jConfig
    graph_libraries: Optional[dict] = None


class GraphStats(BaseModel):
    library: str
    entity_count: int
    relation_count: int


class EntityCreate(BaseModel):
    entity_id: str
    name: str
    entity_type: str
    properties: Optional[dict] = None
    memory_ids: Optional[list] = None


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    properties: Optional[dict] = None
    memory_ids: Optional[list] = None


class RelationCreate(BaseModel):
    from_entity: str
    to_entity: str
    relation_type: str
    strength: Optional[float] = 1.0
    evidence_memory_ids: Optional[list] = None


class RelationUpdate(BaseModel):
    strength: Optional[float] = None
    evidence_memory_ids: Optional[list] = None


def get_graph_store():
    from server.api.app import get_memory_manager

    mm = get_memory_manager()
    if hasattr(mm, "_graph_store") and mm._graph_store:
        return mm._graph_store
    return None


def get_library_enum(library: str):
    from server.core.memory.graph_store import GraphLibrary

    library_map = {lib.value: lib for lib in GraphLibrary}
    if library not in library_map:
        raise HTTPException(
            status_code=400,
            detail=f"无效的图库名称: {library}，有效值: {list(library_map.keys())}",
        )
    return library_map[library]


@router.get("/graph/config")
async def get_graph_config():
    from server.config import settings

    try:
        memory_config = settings.config.memory

        neo4j_config = {}
        if hasattr(memory_config, "neo4j"):
            neo4j_cfg = memory_config.neo4j
            neo4j_config = {
                "uri": getattr(neo4j_cfg, "uri", "bolt://localhost:7687"),
                "user": getattr(neo4j_cfg, "user", "neo4j"),
                "password": getattr(neo4j_cfg, "password", "password"),
                "database": getattr(neo4j_cfg, "database", "neo4j"),
                "max_connection_pool_size": getattr(neo4j_cfg, "max_connection_pool_size", 50),
            }

        graph_libraries = {}
        if hasattr(memory_config, "graph_libraries"):
            gl = memory_config.graph_libraries
            graph_libraries = {
                "user": {
                    "enabled": getattr(gl.user, "enabled", True) if hasattr(gl, "user") else True,
                    "label_prefix": getattr(gl.user, "label_prefix", "User") if hasattr(gl, "user") else "User",
                },
                "thing": {
                    "enabled": getattr(gl.thing, "enabled", True) if hasattr(gl, "thing") else True,
                    "label_prefix": getattr(gl.thing, "label_prefix", "Thing") if hasattr(gl, "thing") else "Thing",
                },
                "concept": {
                    "enabled": getattr(gl.concept, "enabled", True) if hasattr(gl, "concept") else True,
                    "label_prefix": getattr(gl.concept, "label_prefix", "Concept") if hasattr(gl, "concept") else "Concept",
                },
                "event": {
                    "enabled": getattr(gl.event, "enabled", True) if hasattr(gl, "event") else True,
                    "label_prefix": getattr(gl.event, "label_prefix", "Event") if hasattr(gl, "event") else "Event",
                },
            }

        return {
            "status": "success",
            "config": {
                "graph_enabled": getattr(memory_config, "graph_enabled", False),
                "graph_backend": getattr(memory_config, "graph_backend", "neo4j"),
                "neo4j": neo4j_config,
                "graph_libraries": graph_libraries,
            },
        }
    except Exception as e:
        logger.error(f"获取图数据库配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图数据库配置失败: {str(e)}")


@router.post("/graph/config")
async def update_graph_config(config: dict):
    import yaml

    from server.config import settings

    try:
        config_path = "config/default.yaml"

        with open(config_path, "r", encoding="utf-8") as f:
            current_config = yaml.safe_load(f) or {}

        if "memory" not in current_config:
            current_config["memory"] = {}

        if "graph_enabled" in config:
            current_config["memory"]["graph_enabled"] = config["graph_enabled"]

        if "graph_backend" in config:
            current_config["memory"]["graph_backend"] = config["graph_backend"]

        if "neo4j" in config:
            if "neo4j" not in current_config["memory"]:
                current_config["memory"]["neo4j"] = {}
            neo4j_cfg = config["neo4j"]
            for key in ["uri", "user", "password", "database", "max_connection_pool_size"]:
                if key in neo4j_cfg:
                    current_config["memory"]["neo4j"][key] = neo4j_cfg[key]

        if "graph_libraries" in config:
            if "graph_libraries" not in current_config["memory"]:
                current_config["memory"]["graph_libraries"] = {}
            for lib_name, lib_cfg in config["graph_libraries"].items():
                if lib_name not in current_config["memory"]["graph_libraries"]:
                    current_config["memory"]["graph_libraries"][lib_name] = {}
                if isinstance(lib_cfg, dict):
                    for key, value in lib_cfg.items():
                        current_config["memory"]["graph_libraries"][lib_name][key] = value

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(current_config, f, allow_unicode=True, sort_keys=False)

        logger.info("图数据库配置已更新")

        return {
            "status": "success",
            "message": "图数据库配置已更新，重启服务后生效",
        }
    except Exception as e:
        logger.error(f"更新图数据库配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新图数据库配置失败: {str(e)}")


@router.get("/graph/status")
async def get_graph_status():
    from server.api.app import get_memory_manager

    try:
        mm = get_memory_manager()
        graph_enabled = hasattr(mm, "_graph_store") and mm._graph_store is not None

        stats = {
            "graph_enabled": graph_enabled,
            "graph_backend": "neo4j",
            "connected": False,
            "libraries": {},
        }

        if graph_enabled and mm._graph_store:
            try:
                from server.core.memory.graph_store import GraphLibrary

                stats["connected"] = True
                for lib in GraphLibrary:
                    try:
                        lib_stats = mm._graph_store.get_stats(lib)
                        stats["libraries"][lib.value] = lib_stats
                    except Exception as e:
                        stats["libraries"][lib.value] = {
                            "library": lib.value,
                            "entity_count": 0,
                            "relation_count": 0,
                            "error": str(e),
                        }
            except Exception as e:
                stats["error"] = str(e)

        return {"status": "success", "graph_status": stats}
    except Exception as e:
        logger.error(f"获取图数据库状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图数据库状态失败: {str(e)}")


@router.get("/graph/health")
async def graph_health_check():
    from server.api.app import get_memory_manager

    health = {
        "status": "unknown",
        "graph_enabled": False,
        "connected": False,
        "message": "",
    }

    try:
        mm = get_memory_manager()
        health["graph_enabled"] = hasattr(mm, "_graph_store") and mm._graph_store is not None

        if health["graph_enabled"] and mm._graph_store:
            try:
                from server.core.memory.graph_store import GraphLibrary

                mm._graph_store.get_stats(GraphLibrary.USER)
                health["connected"] = True
                health["status"] = "healthy"
                health["message"] = "Neo4j 连接正常"
            except Exception as e:
                health["status"] = "unhealthy"
                health["message"] = f"Neo4j 连接失败: {str(e)}"
        else:
            health["status"] = "disabled"
            health["message"] = "图数据库未启用"

    except Exception as e:
        health["status"] = "error"
        health["message"] = str(e)

    return health


@router.get("/graph/stats/{library}")
async def get_library_stats(library: str):
    from server.api.app import get_memory_manager
    from server.core.memory.graph_store import GraphLibrary

    try:
        valid_libraries = [lib.value for lib in GraphLibrary]
        if library not in valid_libraries:
            raise HTTPException(
                status_code=400,
                detail=f"无效的图库名称: {library}，有效值: {valid_libraries}",
            )

        mm = get_memory_manager()
        if not hasattr(mm, "_graph_store") or not mm._graph_store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        lib_enum = GraphLibrary(library)
        stats = mm._graph_store.get_stats(lib_enum)

        return {"status": "success", "stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图库统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图库统计失败: {str(e)}")


@router.post("/graph/test-connection")
async def test_graph_connection(config: Optional[Neo4jConfig] = None):
    try:
        from server.core.memory.graph_store import Neo4jGraphStore

        if config is None:
            from server.config import settings

            memory_config = settings.config.memory
            neo4j_cfg = memory_config.neo4j
            uri = getattr(neo4j_cfg, "uri", "bolt://localhost:7687")
            user = getattr(neo4j_cfg, "user", "neo4j")
            password = getattr(neo4j_cfg, "password", "password")
        else:
            uri = config.uri
            user = config.user
            password = config.password

        store = Neo4jGraphStore(uri=uri, username=user, password=password)

        from server.core.memory.graph_store import GraphLibrary

        store.get_stats(GraphLibrary.USER)
        store.close()

        return {
            "status": "success",
            "message": "Neo4j 连接测试成功",
            "connection": {
                "uri": uri,
                "user": user,
                "connected": True,
            },
        }
    except Exception as e:
        logger.error(f"Neo4j 连接测试失败: {e}")
        return {
            "status": "error",
            "message": f"Neo4j 连接测试失败: {str(e)}",
            "connected": False,
        }


@router.post("/graph/export/{library}")
async def export_library(library: str):
    from server.api.app import get_memory_manager
    from server.core.memory.graph_store import GraphLibrary

    try:
        valid_libraries = [lib.value for lib in GraphLibrary]
        if library not in valid_libraries:
            raise HTTPException(
                status_code=400,
                detail=f"无效的图库名称: {library}，有效值: {valid_libraries}",
            )

        mm = get_memory_manager()
        if not hasattr(mm, "_graph_store") or not mm._graph_store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        lib_enum = GraphLibrary(library)
        data = mm._graph_store.export(lib_enum)

        return {"status": "success", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出图库失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出图库失败: {str(e)}")


@router.get("/graph/{library}/entities")
async def list_entities(
    library: str,
    entity_type: Optional[str] = Query(None, description="按实体类型过滤"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from server.core.memory.graph_store import Entity

    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        with store._ensure_session() as session:
            label = store._get_label(lib_enum)
            id_field = store._get_id_field(lib_enum)

            where_clauses = ["e.deleted = false"]
            params = {}

            if entity_type:
                where_clauses.append("e.entity_type = $entity_type")
                params["entity_type"] = entity_type

            if search:
                where_clauses.append("e.name CONTAINS $search")
                params["search"] = search

            where_clause = " AND ".join(where_clauses)

            count_query = f"MATCH (e:{label}) WHERE {where_clause} RETURN count(e) as total"
            total = session.run(count_query, **params).single()["total"]

            query = f"""
            MATCH (e:{label}) WHERE {where_clause}
            RETURN e
            ORDER BY e.updated_at DESC
            SKIP $offset LIMIT $limit
            """
            params["offset"] = offset
            params["limit"] = limit

            result = session.run(query, **params)
            entities = [store._record_to_entity(record["e"], lib_enum) for record in result]

            return {
                "status": "success",
                "entities": [vars(e) for e in entities],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实体列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取实体列表失败: {str(e)}")


@router.get("/graph/{library}/entities/{entity_id}")
async def get_entity(library: str, entity_id: str):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        entity = store.get_entity(entity_id, lib_enum)
        if not entity:
            raise HTTPException(status_code=404, detail=f"实体不存在: {entity_id}")

        return {"status": "success", "entity": vars(entity)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实体失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取实体失败: {str(e)}")


@router.post("/graph/{library}/entities")
async def create_entity(library: str, entity: EntityCreate):
    from server.core.memory.graph_store import Entity
    from datetime import datetime

    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        new_entity = Entity(
            entity_id=entity.entity_id,
            name=entity.name,
            entity_type=entity.entity_type,
            properties=entity.properties or {},
            memory_ids=entity.memory_ids or [],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        created = store.create_entity(new_entity, lib_enum)
        return {"status": "success", "entity": vars(created), "message": "实体创建成功"}
    except Exception as e:
        logger.error(f"创建实体失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建实体失败: {str(e)}")


@router.put("/graph/{library}/entities/{entity_id}")
async def update_entity(library: str, entity_id: str, updates: EntityUpdate):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        update_dict = {}
        if updates.name is not None:
            update_dict["name"] = updates.name
        if updates.properties is not None:
            update_dict["properties"] = updates.properties
        if updates.memory_ids is not None:
            update_dict["memory_ids"] = updates.memory_ids

        if not update_dict:
            raise HTTPException(status_code=400, detail="没有要更新的字段")

        updated = store.update_entity(entity_id, update_dict, lib_enum)
        if not updated:
            raise HTTPException(status_code=404, detail=f"实体不存在: {entity_id}")

        return {"status": "success", "entity": vars(updated), "message": "实体更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新实体失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新实体失败: {str(e)}")


@router.delete("/graph/{library}/entities/{entity_id}")
async def delete_entity(library: str, entity_id: str, hard: bool = Query(False, description="是否硬删除")):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        success = store.delete_entity(entity_id, lib_enum, hard=hard)
        if not success:
            raise HTTPException(status_code=404, detail=f"实体不存在: {entity_id}")

        return {"status": "success", "message": "实体删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除实体失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除实体失败: {str(e)}")


@router.get("/graph/{library}/entities/{entity_id}/relations")
async def get_entity_relations(
    library: str,
    entity_id: str,
    relation_type: Optional[str] = Query(None, description="关系类型过滤"),
    depth: int = Query(1, ge=1, le=5, description="查询深度"),
):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        related = store.find_related_entities(entity_id, relation_type, lib_enum, depth)

        return {
            "status": "success",
            "entity_id": entity_id,
            "relations": [vars(e) for e in related],
            "depth": depth,
        }
    except Exception as e:
        logger.error(f"获取实体关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取实体关系失败: {str(e)}")


@router.get("/graph/{library}/relations")
async def list_relations(
    library: str,
    relation_type: Optional[str] = Query(None, description="关系类型过滤"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        with store._ensure_session() as session:
            label = store._get_label(lib_enum)

            if relation_type:
                rel_type = f"{library.capitalize()}_{relation_type}"
                count_query = f"MATCH ()-[r:{rel_type}]->() WHERE r.deleted = false RETURN count(r) as total"
                query = f"""
                MATCH (e1:{label})-[r:{rel_type}]->(e2:{label})
                WHERE r.deleted = false
                RETURN r, e1, e2
                ORDER BY r.created_at DESC
                SKIP $offset LIMIT $limit
                """
            else:
                count_query = f"MATCH ()-[r]->() WHERE r.deleted = false AND type(r) STARTS WITH '{library.capitalize()}' RETURN count(r) as total"
                query = f"""
                MATCH (e1:{label})-[r]->(e2:{label})
                WHERE r.deleted = false AND type(r) STARTS WITH '{library.capitalize()}'
                RETURN r, e1, e2
                ORDER BY r.created_at DESC
                SKIP $offset LIMIT $limit
                """

            total = session.run(count_query).single()["total"]
            result = session.run(query, offset=offset, limit=limit)

            relations = []
            for record in result:
                rel = store._record_to_relation(record["r"])
                relations.append({
                    **vars(rel),
                    "from_entity_name": record["e1"].get("name", ""),
                    "to_entity_name": record["e2"].get("name", ""),
                })

            return {
                "status": "success",
                "relations": relations,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
    except Exception as e:
        logger.error(f"获取关系列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取关系列表失败: {str(e)}")


@router.post("/graph/{library}/relations")
async def create_relation(library: str, relation: RelationCreate):
    from server.core.memory.graph_store import Relation
    from datetime import datetime

    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        new_relation = Relation(
            from_entity=relation.from_entity,
            to_entity=relation.to_entity,
            relation_type=relation.relation_type,
            strength=relation.strength or 1.0,
            evidence_memory_ids=relation.evidence_memory_ids or [],
            created_at=datetime.now(),
        )

        created = store.create_relation(new_relation, lib_enum)
        return {"status": "success", "relation": vars(created), "message": "关系创建成功"}
    except Exception as e:
        logger.error(f"创建关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建关系失败: {str(e)}")


@router.put("/graph/{library}/relations")
async def update_relation(library: str, from_entity: str, to_entity: str, relation_type: str, updates: RelationUpdate):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        update_dict = {}
        if updates.strength is not None:
            update_dict["strength"] = updates.strength
        if updates.evidence_memory_ids is not None:
            update_dict["evidence_memory_ids"] = updates.evidence_memory_ids

        if not update_dict:
            raise HTTPException(status_code=400, detail="没有要更新的字段")

        updated = store.update_relation(from_entity, to_entity, relation_type, update_dict, lib_enum)
        if not updated:
            raise HTTPException(status_code=404, detail="关系不存在")

        return {"status": "success", "relation": vars(updated), "message": "关系更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新关系失败: {str(e)}")


@router.delete("/graph/{library}/relations")
async def delete_relation(
    library: str,
    from_entity: str,
    to_entity: str,
    relation_type: str,
    hard: bool = Query(False, description="是否硬删除"),
):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        success = store.delete_relation(from_entity, to_entity, relation_type, lib_enum, hard=hard)
        if not success:
            raise HTTPException(status_code=404, detail="关系不存在")

        return {"status": "success", "message": "关系删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除关系失败: {str(e)}")


@router.get("/graph/{library}/entity-types")
async def get_entity_types(library: str):
    from server.core.memory.graph_store import (
        UserEntityType,
        ThingEntityType,
        ConceptEntityType,
        EventEntityType,
    )

    type_map = {
        "user": [(t.value, t.name) for t in UserEntityType],
        "thing": [(t.value, t.name) for t in ThingEntityType],
        "concept": [(t.value, t.name) for t in ConceptEntityType],
        "event": [(t.value, t.name) for t in EventEntityType],
    }

    if library not in type_map:
        raise HTTPException(status_code=400, detail=f"无效的图库: {library}")

    return {
        "status": "success",
        "library": library,
        "entity_types": [{"value": v, "label": n} for v, n in type_map[library]],
    }


@router.get("/graph/{library}/relation-types")
async def get_relation_types(library: str):
    from server.core.memory.graph_store import (
        UserRelationType,
        ThingRelationType,
        ConceptRelationType,
        EventRelationType,
    )

    type_map = {
        "user": [(t.value, t.name) for t in UserRelationType],
        "thing": [(t.value, t.name) for t in ThingRelationType],
        "concept": [(t.value, t.name) for t in ConceptRelationType],
        "event": [(t.value, t.name) for t in EventRelationType],
    }

    if library not in type_map:
        raise HTTPException(status_code=400, detail=f"无效的图库: {library}")

    return {
        "status": "success",
        "library": library,
        "relation_types": [{"value": v, "label": n} for v, n in type_map[library]],
    }


@router.get("/graph/{library}/path")
async def find_path(
    library: str,
    start_entity: str = Query(..., description="起始实体ID"),
    end_entity: str = Query(..., description="目标实体ID"),
    max_depth: int = Query(3, ge=1, le=6, description="最大搜索深度"),
):
    try:
        lib_enum = get_library_enum(library)
        store = get_graph_store()
        if not store:
            raise HTTPException(status_code=503, detail="图数据库未启用")

        paths = store.find_paths(start_entity, end_entity, lib_enum, max_depth)

        return {
            "status": "success",
            "paths": [[vars(e) for e in path] for path in paths],
            "path_count": len(paths),
        }
    except Exception as e:
        logger.error(f"路径查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"路径查询失败: {str(e)}")
