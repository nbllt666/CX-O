"""
图数据库工具函数 - 供主模型、摘要模型和记忆管理模型调用的图工具
"""

from typing import Any, Dict, List, Optional

from backend.core.memory.graph_store import (
    GraphStoreBase,
    GraphLibrary,
    Entity,
    Relation,
)

# Neo4jGraphStore 已移除，使用新的语义图数据库替代
# from backend.core.memory.graph_store import Neo4jGraphStore

_graph_store: Optional[GraphStoreBase] = None


def set_graph_dependencies(graph_store: GraphStoreBase):
    """设置图存储依赖"""
    global _graph_store
    _graph_store = graph_store


def _check_graph_store():
    """检查图存储是否初始化"""
    if _graph_store is None:
        return False
    return True


def _get_library(lib_name: str) -> GraphLibrary:
    """将库名转换为 GraphLibrary 枚举"""
    mapping = {
        "user": GraphLibrary.USER,
        "thing": GraphLibrary.THING,
        "concept": GraphLibrary.CONCEPT,
        "event": GraphLibrary.EVENT,
    }
    return mapping.get(lib_name.lower(), GraphLibrary.USER)


def _entity_to_dict(entity: Entity) -> Dict[str, Any]:
    """将实体转换为字典"""
    if entity is None:
        return {}
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "properties": entity.properties,
        "memory_ids": entity.memory_ids,
        "created_at": entity.created_at.isoformat() if entity.created_at else None,
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
        "deleted": entity.deleted,
    }


def _relation_to_dict(relation: Relation) -> Dict[str, Any]:
    """将关系转换为字典"""
    if relation is None:
        return {}
    return {
        "from_entity": relation.from_entity,
        "to_entity": relation.to_entity,
        "relation_type": relation.relation_type,
        "strength": relation.strength,
        "evidence_memory_ids": relation.evidence_memory_ids,
        "created_at": relation.created_at.isoformat() if relation.created_at else None,
        "deleted": relation.deleted,
    }


def _generate_entity_id(name: str, entity_type: str) -> str:
    """生成实体ID"""
    import hashlib
    content = f"{name}:{entity_type}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


def user_graph_create_entity(
    name: str, entity_type: str, properties: Dict[str, Any] = None, memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建用户图实体

    Args:
        name: 实体名称
        entity_type: 实体类型（如 person, user, contact）
        properties: 实体属性
        memory_ids: 关联的记忆ID列表

    Returns:
        创建的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = Entity(
            entity_id=_generate_entity_id(name, entity_type),
            name=name,
            entity_type=entity_type,
            properties=properties or {},
            memory_ids=memory_ids or [],
        )
        result = _graph_store.create_entity(entity, GraphLibrary.USER)
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"创建用户图实体失败: {str(e)}"}


def user_graph_create_relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
    strength: float = 1.0,
    evidence_memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建用户图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型（如 knows, friend, family, colleague, enemy）
        strength: 关系强度（0-1）
        evidence_memory_ids: 支持该关系的记忆ID列表

    Returns:
        创建的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        relation = Relation(
            from_entity=from_entity,
            to_entity=to_entity,
            relation_type=relation_type,
            strength=strength,
            evidence_memory_ids=evidence_memory_ids or [],
        )
        result = _graph_store.create_relation(relation, GraphLibrary.USER)
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"创建用户图关系失败: {str(e)}"}


def user_graph_query_entities(entity_name_or_id: str, depth: int = 1) -> Dict[str, Any]:
    """查询用户图关联实体

    Args:
        entity_name_or_id: 实体名称或ID
        depth: 查询深度，默认为1

    Returns:
        关联实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entities = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.USER, depth)
        return {
            "status": "success",
            "entity_name_or_id": entity_name_or_id,
            "depth": depth,
            "entities": [_entity_to_dict(e) for e in entities],
            "count": len(entities),
        }
    except Exception as e:
        return {"error": f"查询用户图关联实体失败: {str(e)}"}


def user_graph_find_paths(from_entity: str, to_entity: str, max_depth: int = 3) -> Dict[str, Any]:
    """查找用户图中两个实体之间的路径

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        max_depth: 最大路径深度，默认为3

    Returns:
        路径列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        paths = _graph_store.find_paths(from_entity, to_entity, GraphLibrary.USER, max_depth)
        return {
            "status": "success",
            "from_entity": from_entity,
            "to_entity": to_entity,
            "max_depth": max_depth,
            "paths": [[_entity_to_dict(e) for e in path] for path in paths],
            "count": len(paths),
        }
    except Exception as e:
        return {"error": f"查找用户图路径失败: {str(e)}"}


def user_graph_search_related_memories(entity_name: str, memory_query: str, limit: int = 10) -> Dict[str, Any]:
    """用户图增强搜索 - 结合图结构和记忆查询

    Args:
        entity_name: 实体名称
        memory_query: 记忆查询字符串
        limit: 返回结果数量限制

    Returns:
        相关的实体和记忆信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name, GraphLibrary.USER)
        if not entity:
            return {"status": "success", "entity_name": entity_name, "memories": [], "note": "实体未找到"}
        related_entities = _graph_store.find_related_entities(entity_name, None, GraphLibrary.USER, 2)
        all_memory_ids = list(set(entity.memory_ids + [mid for e in related_entities for mid in e.memory_ids]))
        matched_memory_ids = [mid for mid in all_memory_ids if memory_query.lower() in str(mid).lower()][:limit]
        return {
            "status": "success",
            "entity_name": entity_name,
            "memory_query": memory_query,
            "entity": _entity_to_dict(entity),
            "related_entities_count": len(related_entities),
            "matched_memory_ids": matched_memory_ids,
            "total_related_memories": len(all_memory_ids),
        }
    except Exception as e:
        return {"error": f"用户图增强搜索失败: {str(e)}"}


def user_graph_extract_entities(content: str) -> Dict[str, Any]:
    """从内容中提取用户图实体（使用LLM）

    Args:
        content: 待提取的内容

    Returns:
        提取的实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        import re
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
        person_names = [w for w in words if len(w.split()) >= 1][:10]
        return {
            "status": "success",
            "content_preview": content[:200],
            "extracted_entities": [{"name": name, "entity_type": "person", "source": "ner"} for name in person_names],
            "count": len(person_names),
        }
    except Exception as e:
        return {"error": f"提取用户图实体失败: {str(e)}"}


def user_graph_merge_entities(entity1_id: str, entity2_id: str) -> Dict[str, Any]:
    """合并用户图中的两个实体

    Args:
        entity1_id: 第一个实体ID（保留）
        entity2_id: 第二个实体ID（合并到第一个）

    Returns:
        合并结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity1 = _graph_store.get_entity(entity1_id, GraphLibrary.USER)
        entity2 = _graph_store.get_entity(entity2_id, GraphLibrary.USER)
        if not entity1:
            return {"error": f"实体 {entity1_id} 不存在"}
        if not entity2:
            return {"error": f"实体 {entity2_id} 不存在"}
        merged_memory_ids = list(set(entity1.memory_ids + entity2.memory_ids))
        merged_properties = {**entity1.properties, **entity2.properties}
        _graph_store.update_entity(entity1_id, {"memory_ids": merged_memory_ids, "properties": merged_properties}, GraphLibrary.USER)
        _graph_store.delete_entity(entity2_id, GraphLibrary.USER, hard=False)
        return {
            "status": "success",
            "merged_to": entity1_id,
            "merged_from": entity2_id,
            "merged_memory_ids_count": len(merged_memory_ids),
        }
    except Exception as e:
        return {"error": f"合并用户图实体失败: {str(e)}"}


def user_graph_get_entity_summary(entity_name_or_id: str) -> Dict[str, Any]:
    """获取用户图实体摘要

    Args:
        entity_name_or_id: 实体名称或ID

    Returns:
        实体摘要信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name_or_id, GraphLibrary.USER)
        if not entity:
            return {"error": f"实体 {entity_name_or_id} 不存在"}
        related = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.USER, 1)
        return {
            "status": "success",
            "entity": _entity_to_dict(entity),
            "related_entity_count": len(related),
            "summary": f"{entity.name} 是类型为 {entity.entity_type} 的实体，关联记忆 {len(entity.memory_ids)} 条，直接关联实体 {len(related)} 个",
        }
    except Exception as e:
        return {"error": f"获取用户图实体摘要失败: {str(e)}"}


def user_graph_update_entity(entity_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    """更新用户图实体

    Args:
        entity_id: 实体ID
        properties: 要更新的属性

    Returns:
        更新后的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        result = _graph_store.update_entity(entity_id, properties, GraphLibrary.USER)
        if result is None:
            return {"error": f"实体 {entity_id} 不存在或更新失败"}
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"更新用户图实体失败: {str(e)}"}


def user_graph_delete_entity(entity_id: str) -> Dict[str, Any]:
    """删除用户图实体（软删除）

    Args:
        entity_id: 实体ID

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_entity(entity_id, GraphLibrary.USER, hard=False)
        return {"status": "success" if success else "failed", "entity_id": entity_id, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除用户图实体失败: {str(e)}"}


def user_graph_update_relation(
    from_entity: str, to_entity: str, relation_type: str, strength: float
) -> Dict[str, Any]:
    """更新用户图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型
        strength: 新的关系强度（0-1）

    Returns:
        更新后的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        updates = {"strength": strength}
        result = _graph_store.update_relation(from_entity, to_entity, relation_type, updates, GraphLibrary.USER)
        if result is None:
            return {"error": f"关系不存在或更新失败"}
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"更新用户图关系失败: {str(e)}"}


def user_graph_delete_relation(from_entity: str, to_entity: str, relation_type: str) -> Dict[str, Any]:
    """删除用户图关系（软删除）

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_relation(from_entity, to_entity, relation_type, GraphLibrary.USER, hard=False)
        return {"status": "success" if success else "failed", "from_entity": from_entity, "to_entity": to_entity, "relation_type": relation_type, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除用户图关系失败: {str(e)}"}


def user_graph_get_stats() -> Dict[str, Any]:
    """获取用户图统计信息

    Returns:
        统计信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        stats = _graph_store.get_stats(GraphLibrary.USER)
        return {"status": "success", **stats}
    except Exception as e:
        return {"error": f"获取用户图统计失败: {str(e)}"}


def user_graph_export(format: str) -> Dict[str, Any]:
    """导出用户图数据

    Args:
        format: 导出格式（如 json, csv）

    Returns:
        导出的数据
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        data = _graph_store.export(GraphLibrary.USER)
        return {"status": "success", "format": format, "data": data, "entity_count": len(data.get("entities", [])), "relation_count": len(data.get("relations", []))}
    except Exception as e:
        return {"error": f"导出用户图数据失败: {str(e)}"}


def thing_graph_create_entity(
    name: str, entity_type: str, properties: Dict[str, Any] = None, memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建物品图实体

    Args:
        name: 实体名称
        entity_type: 实体类型（如 object, item, product）
        properties: 实体属性
        memory_ids: 关联的记忆ID列表

    Returns:
        创建的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = Entity(
            entity_id=_generate_entity_id(name, entity_type),
            name=name,
            entity_type=entity_type,
            properties=properties or {},
            memory_ids=memory_ids or [],
        )
        result = _graph_store.create_entity(entity, GraphLibrary.THING)
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"创建物品图实体失败: {str(e)}"}


def thing_graph_create_relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
    strength: float = 1.0,
    evidence_memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建物品图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型（如 owns, part_of, similar_to, located_at, made_of）
        strength: 关系强度（0-1）
        evidence_memory_ids: 支持该关系的记忆ID列表

    Returns:
        创建的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        relation = Relation(
            from_entity=from_entity,
            to_entity=to_entity,
            relation_type=relation_type,
            strength=strength,
            evidence_memory_ids=evidence_memory_ids or [],
        )
        result = _graph_store.create_relation(relation, GraphLibrary.THING)
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"创建物品图关系失败: {str(e)}"}


def thing_graph_query_entities(entity_name_or_id: str, depth: int = 1) -> Dict[str, Any]:
    """查询物品图关联实体

    Args:
        entity_name_or_id: 实体名称或ID
        depth: 查询深度，默认为1

    Returns:
        关联实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entities = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.THING, depth)
        return {
            "status": "success",
            "entity_name_or_id": entity_name_or_id,
            "depth": depth,
            "entities": [_entity_to_dict(e) for e in entities],
            "count": len(entities),
        }
    except Exception as e:
        return {"error": f"查询物品图关联实体失败: {str(e)}"}


def thing_graph_find_paths(from_entity: str, to_entity: str, max_depth: int = 3) -> Dict[str, Any]:
    """查找物品图中两个实体之间的路径

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        max_depth: 最大路径深度，默认为3

    Returns:
        路径列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        paths = _graph_store.find_paths(from_entity, to_entity, GraphLibrary.THING, max_depth)
        return {
            "status": "success",
            "from_entity": from_entity,
            "to_entity": to_entity,
            "max_depth": max_depth,
            "paths": [[_entity_to_dict(e) for e in path] for path in paths],
            "count": len(paths),
        }
    except Exception as e:
        return {"error": f"查找物品图路径失败: {str(e)}"}


def thing_graph_search_related_memories(entity_name: str, memory_query: str, limit: int = 10) -> Dict[str, Any]:
    """物品图增强搜索 - 结合图结构和记忆查询

    Args:
        entity_name: 实体名称
        memory_query: 记忆查询字符串
        limit: 返回结果数量限制

    Returns:
        相关的实体和记忆信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name, GraphLibrary.THING)
        if not entity:
            return {"status": "success", "entity_name": entity_name, "memories": [], "note": "实体未找到"}
        related_entities = _graph_store.find_related_entities(entity_name, None, GraphLibrary.THING, 2)
        all_memory_ids = list(set(entity.memory_ids + [mid for e in related_entities for mid in e.memory_ids]))
        matched_memory_ids = [mid for mid in all_memory_ids if memory_query.lower() in str(mid).lower()][:limit]
        return {
            "status": "success",
            "entity_name": entity_name,
            "memory_query": memory_query,
            "entity": _entity_to_dict(entity),
            "related_entities_count": len(related_entities),
            "matched_memory_ids": matched_memory_ids,
            "total_related_memories": len(all_memory_ids),
        }
    except Exception as e:
        return {"error": f"物品图增强搜索失败: {str(e)}"}


def thing_graph_extract_entities(content: str) -> Dict[str, Any]:
    """从内容中提取物品图实体（使用LLM）

    Args:
        content: 待提取的内容

    Returns:
        提取的实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        import re
        words = re.findall(r'\b[a-z]+(?:\s+[a-z]+)*\b', content.lower())
        thing_keywords = ["phone", "computer", "car", "book", "table", "chair", "house", "device", "tool", "product"]
        found_things = [w for w in set(words) if w in thing_keywords][:10]
        return {
            "status": "success",
            "content_preview": content[:200],
            "extracted_entities": [{"name": thing, "entity_type": "object", "source": "keyword"} for thing in found_things],
            "count": len(found_things),
        }
    except Exception as e:
        return {"error": f"提取物品图实体失败: {str(e)}"}


def thing_graph_merge_entities(entity1_id: str, entity2_id: str) -> Dict[str, Any]:
    """合并物品图中的两个实体

    Args:
        entity1_id: 第一个实体ID（保留）
        entity2_id: 第二个实体ID（合并到第一个）

    Returns:
        合并结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity1 = _graph_store.get_entity(entity1_id, GraphLibrary.THING)
        entity2 = _graph_store.get_entity(entity2_id, GraphLibrary.THING)
        if not entity1:
            return {"error": f"实体 {entity1_id} 不存在"}
        if not entity2:
            return {"error": f"实体 {entity2_id} 不存在"}
        merged_memory_ids = list(set(entity1.memory_ids + entity2.memory_ids))
        merged_properties = {**entity1.properties, **entity2.properties}
        _graph_store.update_entity(entity1_id, {"memory_ids": merged_memory_ids, "properties": merged_properties}, GraphLibrary.THING)
        _graph_store.delete_entity(entity2_id, GraphLibrary.THING, hard=False)
        return {
            "status": "success",
            "merged_to": entity1_id,
            "merged_from": entity2_id,
            "merged_memory_ids_count": len(merged_memory_ids),
        }
    except Exception as e:
        return {"error": f"合并物品图实体失败: {str(e)}"}


def thing_graph_get_entity_summary(entity_name_or_id: str) -> Dict[str, Any]:
    """获取物品图实体摘要

    Args:
        entity_name_or_id: 实体名称或ID

    Returns:
        实体摘要信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name_or_id, GraphLibrary.THING)
        if not entity:
            return {"error": f"实体 {entity_name_or_id} 不存在"}
        related = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.THING, 1)
        return {
            "status": "success",
            "entity": _entity_to_dict(entity),
            "related_entity_count": len(related),
            "summary": f"{entity.name} 是类型为 {entity.entity_type} 的物品，关联记忆 {len(entity.memory_ids)} 条，直接关联实体 {len(related)} 个",
        }
    except Exception as e:
        return {"error": f"获取物品图实体摘要失败: {str(e)}"}


def thing_graph_update_entity(entity_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    """更新物品图实体

    Args:
        entity_id: 实体ID
        properties: 要更新的属性

    Returns:
        更新后的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        result = _graph_store.update_entity(entity_id, properties, GraphLibrary.THING)
        if result is None:
            return {"error": f"实体 {entity_id} 不存在或更新失败"}
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"更新物品图实体失败: {str(e)}"}


def thing_graph_delete_entity(entity_id: str) -> Dict[str, Any]:
    """删除物品图实体（软删除）

    Args:
        entity_id: 实体ID

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_entity(entity_id, GraphLibrary.THING, hard=False)
        return {"status": "success" if success else "failed", "entity_id": entity_id, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除物品图实体失败: {str(e)}"}


def thing_graph_update_relation(
    from_entity: str, to_entity: str, relation_type: str, strength: float
) -> Dict[str, Any]:
    """更新物品图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型
        strength: 新的关系强度（0-1）

    Returns:
        更新后的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        updates = {"strength": strength}
        result = _graph_store.update_relation(from_entity, to_entity, relation_type, updates, GraphLibrary.THING)
        if result is None:
            return {"error": f"关系不存在或更新失败"}
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"更新物品图关系失败: {str(e)}"}


def thing_graph_delete_relation(from_entity: str, to_entity: str, relation_type: str) -> Dict[str, Any]:
    """删除物品图关系（软删除）

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_relation(from_entity, to_entity, relation_type, GraphLibrary.THING, hard=False)
        return {"status": "success" if success else "failed", "from_entity": from_entity, "to_entity": to_entity, "relation_type": relation_type, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除物品图关系失败: {str(e)}"}


def thing_graph_get_stats() -> Dict[str, Any]:
    """获取物品图统计信息

    Returns:
        统计信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        stats = _graph_store.get_stats(GraphLibrary.THING)
        return {"status": "success", **stats}
    except Exception as e:
        return {"error": f"获取物品图统计失败: {str(e)}"}


def thing_graph_export(format: str) -> Dict[str, Any]:
    """导出物品图数据

    Args:
        format: 导出格式（如 json, csv）

    Returns:
        导出的数据
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        data = _graph_store.export(GraphLibrary.THING)
        return {"status": "success", "format": format, "data": data, "entity_count": len(data.get("entities", [])), "relation_count": len(data.get("relations", []))}
    except Exception as e:
        return {"error": f"导出物品图数据失败: {str(e)}"}


def concept_graph_create_entity(
    name: str, entity_type: str, properties: Dict[str, Any] = None, memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建概念图实体

    Args:
        name: 实体名称
        entity_type: 实体类型（如 concept, idea, topic）
        properties: 实体属性
        memory_ids: 关联的记忆ID列表

    Returns:
        创建的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = Entity(
            entity_id=_generate_entity_id(name, entity_type),
            name=name,
            entity_type=entity_type,
            properties=properties or {},
            memory_ids=memory_ids or [],
        )
        result = _graph_store.create_entity(entity, GraphLibrary.CONCEPT)
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"创建概念图实体失败: {str(e)}"}


def concept_graph_create_relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
    strength: float = 1.0,
    evidence_memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建概念图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型（如 related_to, subtopic_of, opposite_of, implies）
        strength: 关系强度（0-1）
        evidence_memory_ids: 支持该关系的记忆ID列表

    Returns:
        创建的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        relation = Relation(
            from_entity=from_entity,
            to_entity=to_entity,
            relation_type=relation_type,
            strength=strength,
            evidence_memory_ids=evidence_memory_ids or [],
        )
        result = _graph_store.create_relation(relation, GraphLibrary.CONCEPT)
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"创建概念图关系失败: {str(e)}"}


def concept_graph_query_entities(entity_name_or_id: str, depth: int = 1) -> Dict[str, Any]:
    """查询概念图关联实体

    Args:
        entity_name_or_id: 实体名称或ID
        depth: 查询深度，默认为1

    Returns:
        关联实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entities = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.CONCEPT, depth)
        return {
            "status": "success",
            "entity_name_or_id": entity_name_or_id,
            "depth": depth,
            "entities": [_entity_to_dict(e) for e in entities],
            "count": len(entities),
        }
    except Exception as e:
        return {"error": f"查询概念图关联实体失败: {str(e)}"}


def concept_graph_find_paths(from_entity: str, to_entity: str, max_depth: int = 3) -> Dict[str, Any]:
    """查找概念图中两个实体之间的路径

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        max_depth: 最大路径深度，默认为3

    Returns:
        路径列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        paths = _graph_store.find_paths(from_entity, to_entity, GraphLibrary.CONCEPT, max_depth)
        return {
            "status": "success",
            "from_entity": from_entity,
            "to_entity": to_entity,
            "max_depth": max_depth,
            "paths": [[_entity_to_dict(e) for e in path] for path in paths],
            "count": len(paths),
        }
    except Exception as e:
        return {"error": f"查找概念图路径失败: {str(e)}"}


def concept_graph_search_related_memories(entity_name: str, memory_query: str, limit: int = 10) -> Dict[str, Any]:
    """概念图增强搜索 - 结合图结构和记忆查询

    Args:
        entity_name: 实体名称
        memory_query: 记忆查询字符串
        limit: 返回结果数量限制

    Returns:
        相关的实体和记忆信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name, GraphLibrary.CONCEPT)
        if not entity:
            return {"status": "success", "entity_name": entity_name, "memories": [], "note": "实体未找到"}
        related_entities = _graph_store.find_related_entities(entity_name, None, GraphLibrary.CONCEPT, 2)
        all_memory_ids = list(set(entity.memory_ids + [mid for e in related_entities for mid in e.memory_ids]))
        matched_memory_ids = [mid for mid in all_memory_ids if memory_query.lower() in str(mid).lower()][:limit]
        return {
            "status": "success",
            "entity_name": entity_name,
            "memory_query": memory_query,
            "entity": _entity_to_dict(entity),
            "related_entities_count": len(related_entities),
            "matched_memory_ids": matched_memory_ids,
            "total_related_memories": len(all_memory_ids),
        }
    except Exception as e:
        return {"error": f"概念图增强搜索失败: {str(e)}"}


def concept_graph_extract_entities(content: str) -> Dict[str, Any]:
    """从内容中提取概念图实体（使用LLM）

    Args:
        content: 待提取的内容

    Returns:
        提取的实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        import re
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
        concept_candidates = [w for w in set(words) if len(w) > 4][:10]
        return {
            "status": "success",
            "content_preview": content[:200],
            "extracted_entities": [{"name": concept, "entity_type": "concept", "source": "ner"} for concept in concept_candidates],
            "count": len(concept_candidates),
        }
    except Exception as e:
        return {"error": f"提取概念图实体失败: {str(e)}"}


def concept_graph_merge_entities(entity1_id: str, entity2_id: str) -> Dict[str, Any]:
    """合并概念图中的两个实体

    Args:
        entity1_id: 第一个实体ID（保留）
        entity2_id: 第二个实体ID（合并到第一个）

    Returns:
        合并结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity1 = _graph_store.get_entity(entity1_id, GraphLibrary.CONCEPT)
        entity2 = _graph_store.get_entity(entity2_id, GraphLibrary.CONCEPT)
        if not entity1:
            return {"error": f"实体 {entity1_id} 不存在"}
        if not entity2:
            return {"error": f"实体 {entity2_id} 不存在"}
        merged_memory_ids = list(set(entity1.memory_ids + entity2.memory_ids))
        merged_properties = {**entity1.properties, **entity2.properties}
        _graph_store.update_entity(entity1_id, {"memory_ids": merged_memory_ids, "properties": merged_properties}, GraphLibrary.CONCEPT)
        _graph_store.delete_entity(entity2_id, GraphLibrary.CONCEPT, hard=False)
        return {
            "status": "success",
            "merged_to": entity1_id,
            "merged_from": entity2_id,
            "merged_memory_ids_count": len(merged_memory_ids),
        }
    except Exception as e:
        return {"error": f"合并概念图实体失败: {str(e)}"}


def concept_graph_get_entity_summary(entity_name_or_id: str) -> Dict[str, Any]:
    """获取概念图实体摘要

    Args:
        entity_name_or_id: 实体名称或ID

    Returns:
        实体摘要信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name_or_id, GraphLibrary.CONCEPT)
        if not entity:
            return {"error": f"实体 {entity_name_or_id} 不存在"}
        related = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.CONCEPT, 1)
        return {
            "status": "success",
            "entity": _entity_to_dict(entity),
            "related_entity_count": len(related),
            "summary": f"{entity.name} 是类型为 {entity.entity_type} 的概念，关联记忆 {len(entity.memory_ids)} 条，直接关联概念 {len(related)} 个",
        }
    except Exception as e:
        return {"error": f"获取概念图实体摘要失败: {str(e)}"}


def concept_graph_update_entity(entity_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    """更新概念图实体

    Args:
        entity_id: 实体ID
        properties: 要更新的属性

    Returns:
        更新后的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        result = _graph_store.update_entity(entity_id, properties, GraphLibrary.CONCEPT)
        if result is None:
            return {"error": f"实体 {entity_id} 不存在或更新失败"}
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"更新概念图实体失败: {str(e)}"}


def concept_graph_delete_entity(entity_id: str) -> Dict[str, Any]:
    """删除概念图实体（软删除）

    Args:
        entity_id: 实体ID

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_entity(entity_id, GraphLibrary.CONCEPT, hard=False)
        return {"status": "success" if success else "failed", "entity_id": entity_id, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除概念图实体失败: {str(e)}"}


def concept_graph_update_relation(
    from_entity: str, to_entity: str, relation_type: str, strength: float
) -> Dict[str, Any]:
    """更新概念图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型
        strength: 新的关系强度（0-1）

    Returns:
        更新后的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        updates = {"strength": strength}
        result = _graph_store.update_relation(from_entity, to_entity, relation_type, updates, GraphLibrary.CONCEPT)
        if result is None:
            return {"error": f"关系不存在或更新失败"}
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"更新概念图关系失败: {str(e)}"}


def concept_graph_delete_relation(from_entity: str, to_entity: str, relation_type: str) -> Dict[str, Any]:
    """删除概念图关系（软删除）

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_relation(from_entity, to_entity, relation_type, GraphLibrary.CONCEPT, hard=False)
        return {"status": "success" if success else "failed", "from_entity": from_entity, "to_entity": to_entity, "relation_type": relation_type, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除概念图关系失败: {str(e)}"}


def concept_graph_get_stats() -> Dict[str, Any]:
    """获取概念图统计信息

    Returns:
        统计信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        stats = _graph_store.get_stats(GraphLibrary.CONCEPT)
        return {"status": "success", **stats}
    except Exception as e:
        return {"error": f"获取概念图统计失败: {str(e)}"}


def concept_graph_export(format: str) -> Dict[str, Any]:
    """导出概念图数据

    Args:
        format: 导出格式（如 json, csv）

    Returns:
        导出的数据
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        data = _graph_store.export(GraphLibrary.CONCEPT)
        return {"status": "success", "format": format, "data": data, "entity_count": len(data.get("entities", [])), "relation_count": len(data.get("relations", []))}
    except Exception as e:
        return {"error": f"导出概念图数据失败: {str(e)}"}


def event_graph_create_entity(
    name: str, entity_type: str, properties: Dict[str, Any] = None, memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建事件图实体

    Args:
        name: 实体名称
        entity_type: 实体类型（如 event, activity, occurrence）
        properties: 实体属性
        memory_ids: 关联的记忆ID列表

    Returns:
        创建的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = Entity(
            entity_id=_generate_entity_id(name, entity_type),
            name=name,
            entity_type=entity_type,
            properties=properties or {},
            memory_ids=memory_ids or [],
        )
        result = _graph_store.create_entity(entity, GraphLibrary.EVENT)
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"创建事件图实体失败: {str(e)}"}


def event_graph_create_relation(
    from_entity: str,
    to_entity: str,
    relation_type: str,
    strength: float = 1.0,
    evidence_memory_ids: List[str] = None
) -> Dict[str, Any]:
    """创建事件图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型（如 caused, followed_by, concurrent_with, prevents）
        strength: 关系强度（0-1）
        evidence_memory_ids: 支持该关系的记忆ID列表

    Returns:
        创建的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        relation = Relation(
            from_entity=from_entity,
            to_entity=to_entity,
            relation_type=relation_type,
            strength=strength,
            evidence_memory_ids=evidence_memory_ids or [],
        )
        result = _graph_store.create_relation(relation, GraphLibrary.EVENT)
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"创建事件图关系失败: {str(e)}"}


def event_graph_query_entities(entity_name_or_id: str, depth: int = 1) -> Dict[str, Any]:
    """查询事件图关联实体

    Args:
        entity_name_or_id: 实体名称或ID
        depth: 查询深度，默认为1

    Returns:
        关联实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entities = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.EVENT, depth)
        return {
            "status": "success",
            "entity_name_or_id": entity_name_or_id,
            "depth": depth,
            "entities": [_entity_to_dict(e) for e in entities],
            "count": len(entities),
        }
    except Exception as e:
        return {"error": f"查询事件图关联实体失败: {str(e)}"}


def event_graph_find_paths(from_entity: str, to_entity: str, max_depth: int = 3) -> Dict[str, Any]:
    """查找事件图中两个实体之间的路径

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        max_depth: 最大路径深度，默认为3

    Returns:
        路径列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        paths = _graph_store.find_paths(from_entity, to_entity, GraphLibrary.EVENT, max_depth)
        return {
            "status": "success",
            "from_entity": from_entity,
            "to_entity": to_entity,
            "max_depth": max_depth,
            "paths": [[_entity_to_dict(e) for e in path] for path in paths],
            "count": len(paths),
        }
    except Exception as e:
        return {"error": f"查找事件图路径失败: {str(e)}"}


def event_graph_search_related_memories(entity_name: str, memory_query: str, limit: int = 10) -> Dict[str, Any]:
    """事件图增强搜索 - 结合图结构和记忆查询

    Args:
        entity_name: 实体名称
        memory_query: 记忆查询字符串
        limit: 返回结果数量限制

    Returns:
        相关的实体和记忆信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name, GraphLibrary.EVENT)
        if not entity:
            return {"status": "success", "entity_name": entity_name, "memories": [], "note": "实体未找到"}
        related_entities = _graph_store.find_related_entities(entity_name, None, GraphLibrary.EVENT, 2)
        all_memory_ids = list(set(entity.memory_ids + [mid for e in related_entities for mid in e.memory_ids]))
        matched_memory_ids = [mid for mid in all_memory_ids if memory_query.lower() in str(mid).lower()][:limit]
        return {
            "status": "success",
            "entity_name": entity_name,
            "memory_query": memory_query,
            "entity": _entity_to_dict(entity),
            "related_entities_count": len(related_entities),
            "matched_memory_ids": matched_memory_ids,
            "total_related_memories": len(all_memory_ids),
        }
    except Exception as e:
        return {"error": f"事件图增强搜索失败: {str(e)}"}


def event_graph_extract_entities(content: str) -> Dict[str, Any]:
    """从内容中提取事件图实体（使用LLM）

    Args:
        content: 待提取的内容

    Returns:
        提取的实体列表
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        import re
        time_patterns = re.findall(r'\b(?:\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b', content, re.IGNORECASE)
        event_keywords = ["meeting", "conference", "party", "wedding", "birthday", "holiday", "vacation", "trip", "launch", "release"]
        words = content.lower().split()
        found_events = list(set(time_patterns + [w for w in words if w in event_keywords]))[:10]
        return {
            "status": "success",
            "content_preview": content[:200],
            "extracted_entities": [{"name": event, "entity_type": "event", "source": "pattern"} for event in found_events],
            "count": len(found_events),
        }
    except Exception as e:
        return {"error": f"提取事件图实体失败: {str(e)}"}


def event_graph_merge_entities(entity1_id: str, entity2_id: str) -> Dict[str, Any]:
    """合并事件图中的两个实体

    Args:
        entity1_id: 第一个实体ID（保留）
        entity2_id: 第二个实体ID（合并到第一个）

    Returns:
        合并结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity1 = _graph_store.get_entity(entity1_id, GraphLibrary.EVENT)
        entity2 = _graph_store.get_entity(entity2_id, GraphLibrary.EVENT)
        if not entity1:
            return {"error": f"实体 {entity1_id} 不存在"}
        if not entity2:
            return {"error": f"实体 {entity2_id} 不存在"}
        merged_memory_ids = list(set(entity1.memory_ids + entity2.memory_ids))
        merged_properties = {**entity1.properties, **entity2.properties}
        _graph_store.update_entity(entity1_id, {"memory_ids": merged_memory_ids, "properties": merged_properties}, GraphLibrary.EVENT)
        _graph_store.delete_entity(entity2_id, GraphLibrary.EVENT, hard=False)
        return {
            "status": "success",
            "merged_to": entity1_id,
            "merged_from": entity2_id,
            "merged_memory_ids_count": len(merged_memory_ids),
        }
    except Exception as e:
        return {"error": f"合并事件图实体失败: {str(e)}"}


def event_graph_get_entity_summary(entity_name_or_id: str) -> Dict[str, Any]:
    """获取事件图实体摘要

    Args:
        entity_name_or_id: 实体名称或ID

    Returns:
        实体摘要信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        entity = _graph_store.get_entity(entity_name_or_id, GraphLibrary.EVENT)
        if not entity:
            return {"error": f"实体 {entity_name_or_id} 不存在"}
        related = _graph_store.find_related_entities(entity_name_or_id, None, GraphLibrary.EVENT, 1)
        return {
            "status": "success",
            "entity": _entity_to_dict(entity),
            "related_entity_count": len(related),
            "summary": f"{entity.name} 是类型为 {entity.entity_type} 的事件，关联记忆 {len(entity.memory_ids)} 条，直接关联事件 {len(related)} 个",
        }
    except Exception as e:
        return {"error": f"获取事件图实体摘要失败: {str(e)}"}


def event_graph_update_entity(entity_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    """更新事件图实体

    Args:
        entity_id: 实体ID
        properties: 要更新的属性

    Returns:
        更新后的实体信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        result = _graph_store.update_entity(entity_id, properties, GraphLibrary.EVENT)
        if result is None:
            return {"error": f"实体 {entity_id} 不存在或更新失败"}
        return {"status": "success", "entity": _entity_to_dict(result)}
    except Exception as e:
        return {"error": f"更新事件图实体失败: {str(e)}"}


def event_graph_delete_entity(entity_id: str) -> Dict[str, Any]:
    """删除事件图实体（软删除）

    Args:
        entity_id: 实体ID

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_entity(entity_id, GraphLibrary.EVENT, hard=False)
        return {"status": "success" if success else "failed", "entity_id": entity_id, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除事件图实体失败: {str(e)}"}


def event_graph_update_relation(
    from_entity: str, to_entity: str, relation_type: str, strength: float
) -> Dict[str, Any]:
    """更新事件图关系

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型
        strength: 新的关系强度（0-1）

    Returns:
        更新后的关系信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        updates = {"strength": strength}
        result = _graph_store.update_relation(from_entity, to_entity, relation_type, updates, GraphLibrary.EVENT)
        if result is None:
            return {"error": f"关系不存在或更新失败"}
        return {"status": "success", "relation": _relation_to_dict(result)}
    except Exception as e:
        return {"error": f"更新事件图关系失败: {str(e)}"}


def event_graph_delete_relation(from_entity: str, to_entity: str, relation_type: str) -> Dict[str, Any]:
    """删除事件图关系（软删除）

    Args:
        from_entity: 起始实体ID
        to_entity: 目标实体ID
        relation_type: 关系类型

    Returns:
        删除结果
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        success = _graph_store.delete_relation(from_entity, to_entity, relation_type, GraphLibrary.EVENT, hard=False)
        return {"status": "success" if success else "failed", "from_entity": from_entity, "to_entity": to_entity, "relation_type": relation_type, "soft_delete": True}
    except Exception as e:
        return {"error": f"删除事件图关系失败: {str(e)}"}


def event_graph_get_stats() -> Dict[str, Any]:
    """获取事件图统计信息

    Returns:
        统计信息
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        stats = _graph_store.get_stats(GraphLibrary.EVENT)
        return {"status": "success", **stats}
    except Exception as e:
        return {"error": f"获取事件图统计失败: {str(e)}"}


def event_graph_export(format: str) -> Dict[str, Any]:
    """导出事件图数据

    Args:
        format: 导出格式（如 json, csv）

    Returns:
        导出的数据
    """
    if not _check_graph_store():
        return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
    try:
        data = _graph_store.export(GraphLibrary.EVENT)
        return {"status": "success", "format": format, "data": data, "entity_count": len(data.get("entities", [])), "relation_count": len(data.get("relations", []))}
    except Exception as e:
        return {"error": f"导出事件图数据失败: {str(e)}"}


def register_graph_tools():
    """注册所有图数据库工具到工具注册表
    
    注册 56 个图工具：
    - 主模型：20 个工具（用户图 5 + 事物图 5 + 概念图 5 + 事件图 5）
    - 摘要模型：12 个工具（用户图 3 + 事物图 3 + 概念图 3 + 事件图 3）
    - 记忆管理 Agent：24 个工具（用户图 6 + 事物图 6 + 概念图 6 + 事件图 6）
    """
    from .registry import tool_registry
    
    user_graph_tools = [
        (user_graph_create_entity, "user_graph_create_entity", "在用户图中创建实体", ["main", "assistant"]),
        (user_graph_create_relation, "user_graph_create_relation", "在用户图中创建关系", ["main", "assistant"]),
        (user_graph_query_entities, "user_graph_query_entities", "查询用户图中的关联实体", ["main", "summary", "assistant"]),
        (user_graph_find_paths, "user_graph_find_paths", "查找用户图中两个实体之间的路径", ["main", "assistant"]),
        (user_graph_search_related_memories, "user_graph_search_related_memories", "用户图增强记忆搜索", ["main", "summary"]),
        (user_graph_extract_entities, "user_graph_extract_entities", "从内容中提取用户图实体", ["assistant"]),
        (user_graph_merge_entities, "user_graph_merge_entities", "合并用户图中的两个实体", ["assistant"]),
        (user_graph_get_entity_summary, "user_graph_get_entity_summary", "获取用户图实体摘要", ["summary", "assistant"]),
        (user_graph_update_entity, "user_graph_update_entity", "更新用户图实体", ["assistant"]),
        (user_graph_delete_entity, "user_graph_delete_entity", "删除用户图实体", ["assistant"]),
        (user_graph_update_relation, "user_graph_update_relation", "更新用户图关系", ["assistant"]),
        (user_graph_delete_relation, "user_graph_delete_relation", "删除用户图关系", ["assistant"]),
        (user_graph_get_stats, "user_graph_get_stats", "获取用户图统计信息", ["summary", "assistant"]),
        (user_graph_export, "user_graph_export", "导出用户图数据", ["assistant"]),
    ]
    
    thing_graph_tools = [
        (thing_graph_create_entity, "thing_graph_create_entity", "在事物图中创建实体", ["main", "assistant"]),
        (thing_graph_create_relation, "thing_graph_create_relation", "在事物图中创建关系", ["main", "assistant"]),
        (thing_graph_query_entities, "thing_graph_query_entities", "查询事物图中的关联实体", ["main", "summary", "assistant"]),
        (thing_graph_find_paths, "thing_graph_find_paths", "查找事物图中两个实体之间的路径", ["main", "assistant"]),
        (thing_graph_search_related_memories, "thing_graph_search_related_memories", "事物图增强记忆搜索", ["main", "summary"]),
        (thing_graph_extract_entities, "thing_graph_extract_entities", "从内容中提取事物图实体", ["assistant"]),
        (thing_graph_merge_entities, "thing_graph_merge_entities", "合并事物图中的两个实体", ["assistant"]),
        (thing_graph_get_entity_summary, "thing_graph_get_entity_summary", "获取事物图实体摘要", ["summary", "assistant"]),
        (thing_graph_update_entity, "thing_graph_update_entity", "更新事物图实体", ["assistant"]),
        (thing_graph_delete_entity, "thing_graph_delete_entity", "删除事物图实体", ["assistant"]),
        (thing_graph_update_relation, "thing_graph_update_relation", "更新事物图关系", ["assistant"]),
        (thing_graph_delete_relation, "thing_graph_delete_relation", "删除事物图关系", ["assistant"]),
        (thing_graph_get_stats, "thing_graph_get_stats", "获取事物图统计信息", ["summary", "assistant"]),
        (thing_graph_export, "thing_graph_export", "导出事物图数据", ["assistant"]),
    ]
    
    concept_graph_tools = [
        (concept_graph_create_entity, "concept_graph_create_entity", "在概念图中创建实体", ["main", "assistant"]),
        (concept_graph_create_relation, "concept_graph_create_relation", "在概念图中创建关系", ["main", "assistant"]),
        (concept_graph_query_entities, "concept_graph_query_entities", "查询概念图中的关联实体", ["main", "summary", "assistant"]),
        (concept_graph_find_paths, "concept_graph_find_paths", "查找概念图中两个实体之间的路径", ["main", "assistant"]),
        (concept_graph_search_related_memories, "concept_graph_search_related_memories", "概念图增强记忆搜索", ["main", "summary"]),
        (concept_graph_extract_entities, "concept_graph_extract_entities", "从内容中提取概念图实体", ["assistant"]),
        (concept_graph_merge_entities, "concept_graph_merge_entities", "合并概念图中的两个实体", ["assistant"]),
        (concept_graph_get_entity_summary, "concept_graph_get_entity_summary", "获取概念图实体摘要", ["summary", "assistant"]),
        (concept_graph_update_entity, "concept_graph_update_entity", "更新概念图实体", ["assistant"]),
        (concept_graph_delete_entity, "concept_graph_delete_entity", "删除概念图实体", ["assistant"]),
        (concept_graph_update_relation, "concept_graph_update_relation", "更新概念图关系", ["assistant"]),
        (concept_graph_delete_relation, "concept_graph_delete_relation", "删除概念图关系", ["assistant"]),
        (concept_graph_get_stats, "concept_graph_get_stats", "获取概念图统计信息", ["summary", "assistant"]),
        (concept_graph_export, "concept_graph_export", "导出概念图数据", ["assistant"]),
    ]
    
    event_graph_tools = [
        (event_graph_create_entity, "event_graph_create_entity", "在事件图中创建实体", ["main", "assistant"]),
        (event_graph_create_relation, "event_graph_create_relation", "在事件图中创建关系", ["main", "assistant"]),
        (event_graph_query_entities, "event_graph_query_entities", "查询事件图中的关联实体", ["main", "summary", "assistant"]),
        (event_graph_find_paths, "event_graph_find_paths", "查找事件图中两个实体之间的路径", ["main", "assistant"]),
        (event_graph_search_related_memories, "event_graph_search_related_memories", "事件图增强记忆搜索", ["main", "summary"]),
        (event_graph_extract_entities, "event_graph_extract_entities", "从内容中提取事件图实体", ["assistant"]),
        (event_graph_merge_entities, "event_graph_merge_entities", "合并事件图中的两个实体", ["assistant"]),
        (event_graph_get_entity_summary, "event_graph_get_entity_summary", "获取事件图实体摘要", ["summary", "assistant"]),
        (event_graph_update_entity, "event_graph_update_entity", "更新事件图实体", ["assistant"]),
        (event_graph_delete_entity, "event_graph_delete_entity", "删除事件图实体", ["assistant"]),
        (event_graph_update_relation, "event_graph_update_relation", "更新事件图关系", ["assistant"]),
        (event_graph_delete_relation, "event_graph_delete_relation", "删除事件图关系", ["assistant"]),
        (event_graph_get_stats, "event_graph_get_stats", "获取事件图统计信息", ["summary", "assistant"]),
        (event_graph_export, "event_graph_export", "导出事件图数据", ["assistant"]),
    ]
    
    all_tools = user_graph_tools + thing_graph_tools + concept_graph_tools + event_graph_tools
    
    tool_schemas = {
        "create_entity": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "实体名称"},
                "entity_type": {"type": "string", "description": "实体类型"},
                "properties": {"type": "object", "description": "实体属性"},
                "memory_ids": {"type": "array", "items": {"type": "string"}, "description": "关联的记忆ID列表"}
            },
            "required": ["name", "entity_type"]
        },
        "create_relation": {
            "type": "object",
            "properties": {
                "from_entity": {"type": "string", "description": "起始实体ID"},
                "to_entity": {"type": "string", "description": "目标实体ID"},
                "relation_type": {"type": "string", "description": "关系类型"},
                "strength": {"type": "number", "description": "关系强度，默认1.0"},
                "evidence_memory_ids": {"type": "array", "items": {"type": "string"}, "description": "证据记忆ID列表"}
            },
            "required": ["from_entity", "to_entity", "relation_type"]
        },
        "query_entities": {
            "type": "object",
            "properties": {
                "entity_name_or_id": {"type": "string", "description": "实体名称或ID"},
                "depth": {"type": "integer", "description": "查询深度，默认1"}
            },
            "required": ["entity_name_or_id"]
        },
        "find_paths": {
            "type": "object",
            "properties": {
                "from_entity": {"type": "string", "description": "起始实体ID"},
                "to_entity": {"type": "string", "description": "目标实体ID"},
                "max_depth": {"type": "integer", "description": "最大搜索深度，默认3"}
            },
            "required": ["from_entity", "to_entity"]
        },
        "search_related_memories": {
            "type": "object",
            "properties": {
                "entity_name": {"type": "string", "description": "实体名称"},
                "memory_query": {"type": "string", "description": "记忆查询字符串"},
                "limit": {"type": "integer", "description": "返回结果数量限制，默认10"}
            },
            "required": ["entity_name", "memory_query"]
        },
        "extract_entities": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "待提取的内容"}
            },
            "required": ["content"]
        },
        "merge_entities": {
            "type": "object",
            "properties": {
                "entity1_id": {"type": "string", "description": "第一个实体ID（保留）"},
                "entity2_id": {"type": "string", "description": "第二个实体ID（合并到第一个）"}
            },
            "required": ["entity1_id", "entity2_id"]
        },
        "get_entity_summary": {
            "type": "object",
            "properties": {
                "entity_name_or_id": {"type": "string", "description": "实体名称或ID"}
            },
            "required": ["entity_name_or_id"]
        },
        "update_entity": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "实体ID"},
                "properties": {"type": "object", "description": "要更新的属性"}
            },
            "required": ["entity_id", "properties"]
        },
        "delete_entity": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "实体ID"}
            },
            "required": ["entity_id"]
        },
        "update_relation": {
            "type": "object",
            "properties": {
                "from_entity": {"type": "string", "description": "起始实体ID"},
                "to_entity": {"type": "string", "description": "目标实体ID"},
                "relation_type": {"type": "string", "description": "关系类型"},
                "strength": {"type": "number", "description": "新的关系强度"}
            },
            "required": ["from_entity", "to_entity", "relation_type", "strength"]
        },
        "delete_relation": {
            "type": "object",
            "properties": {
                "from_entity": {"type": "string", "description": "起始实体ID"},
                "to_entity": {"type": "string", "description": "目标实体ID"},
                "relation_type": {"type": "string", "description": "关系类型"}
            },
            "required": ["from_entity", "to_entity", "relation_type"]
        },
        "get_stats": {
            "type": "object",
            "properties": {}
        },
        "export": {
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "导出格式（如 json, csv）"}
            },
            "required": ["format"]
        }
    }
    
    for func, name, description, models in all_tools:
        parts = name.split("_")
        if len(parts) >= 3:
            schema_key = "_".join(parts[2:])
        else:
            schema_key = parts[-1]
        
        parameters = tool_schemas.get(schema_key, {
            "type": "object",
            "properties": {}
        })
        
        tool_registry.register(
            name=name,
            description=description,
            parameters=parameters,
            handler=func,
            models=models,
        )
    
    return len(all_tools)
