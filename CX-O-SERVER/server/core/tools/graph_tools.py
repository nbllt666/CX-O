"""
图数据库工具函数 - 供主模型、摘要模型和记忆管理模型调用的图工具

参数化设计：14 个操作通过工厂函数 _make_graph_tools 生成，
为 4 个图库（user/thing/concept/event）各自生成闭包实例。
"""

import contextvars
import re
from typing import Any, Dict, List, Optional

from server.config import Settings
from server.core.memory.graph_store import (
    GraphStoreBase,
    GraphLibrary,
    Entity,
    Relation,
)

_graph_store: Optional[GraphStoreBase] = None

# 当前请求上下文的 agent_id（迁移自 CXHMS graph_tools.py）
# 由 chat 路由在每次请求开始时 set_current_agent_id(agent_id)，
# 工具函数通过 get_current_agent_id() 读取，用于 per-agent 资源访问。
_current_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_agent_id", default="default"
)


def set_current_agent_id(agent_id: str) -> None:
    """设置当前请求上下文的 agent_id。

    迁移自 CXHMS: backend/core/tools/graph_tools.py

    在 chat 路由（主聊天/摘要助手/记忆管理助手）开始时调用，
    工具函数通过 get_current_agent_id() 读取，实现 per-agent 资源隔离。
    """
    _current_agent_id.set(agent_id or "default")


def get_current_agent_id() -> str:
    """获取当前请求上下文的 agent_id。"""
    return _current_agent_id.get()


def set_graph_dependencies(graph_store: GraphStoreBase):
    """设置图存储依赖"""
    global _graph_store
    _graph_store = graph_store


def _check_graph_store():
    """检查图存储是否初始化，未初始化时按需创建 default 实例。

    迁移自 CXHMS per-agent 注册表：复用 dependencies._get_or_create_graph_store
    避免 default agent 的图数据库被重复构造。
    详见 .trae/documents/20260720_模块0_从CXHMS迁移图数据库.md
    """
    global _graph_store
    if _graph_store is not None:
        return True
    try:
        from server.dependencies import _get_or_create_graph_store

        _graph_store = _get_or_create_graph_store("default")
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"按需创建图存储失败: {e}", exc_info=True)
        return False


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


def _make_graph_tools(library: GraphLibrary, label: str) -> Dict[str, Any]:
    """为指定图库生成 14 个工具函数闭包

    Args:
        library: GraphLibrary 枚举值
        label: 中文标签（如"用户图"），用于错误消息

    Returns:
        操作名 → 闭包函数 的字典
    """

    def create_entity(
        name: str, entity_type: str, properties: Dict[str, Any] = None, memory_ids: List[str] = None
    ) -> Dict[str, Any]:
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
            result = _graph_store.create_entity(entity, library)
            return {"status": "success", "entity": _entity_to_dict(result)}
        except Exception as e:
            return {"error": f"创建{label}实体失败: {str(e)}"}

    def create_relation(
        from_entity: str,
        to_entity: str,
        relation_type: str,
        strength: float = 1.0,
        evidence_memory_ids: List[str] = None
    ) -> Dict[str, Any]:
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
            result = _graph_store.create_relation(relation, library)
            return {"status": "success", "relation": _relation_to_dict(result)}
        except Exception as e:
            return {"error": f"创建{label}关系失败: {str(e)}"}

    def query_entities(entity_name_or_id: str, depth: int = 1) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            entities = _graph_store.find_related_entities(entity_name_or_id, None, library, depth)
            return {
                "status": "success",
                "entity_name_or_id": entity_name_or_id,
                "depth": depth,
                "entities": [_entity_to_dict(e) for e in entities],
                "count": len(entities),
            }
        except Exception as e:
            return {"error": f"查询{label}关联实体失败: {str(e)}"}

    def find_paths(from_entity: str, to_entity: str, max_depth: int = 3) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            paths = _graph_store.find_paths(from_entity, to_entity, library, max_depth)
            return {
                "status": "success",
                "from_entity": from_entity,
                "to_entity": to_entity,
                "max_depth": max_depth,
                "paths": [[_entity_to_dict(e) for e in path] for path in paths],
                "count": len(paths),
            }
        except Exception as e:
            return {"error": f"查找{label}路径失败: {str(e)}"}

    def search_related_memories(entity_name: str, memory_query: str, limit: int = None) -> Dict[str, Any]:
        if limit is None:
            limit = Settings().config.limits.memory.search_memories_limit
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            entity = _graph_store.get_entity(entity_name, library)
            if not entity:
                return {"status": "success", "entity_name": entity_name, "memories": [], "note": "实体未找到"}
            related_entities = _graph_store.find_related_entities(entity_name, None, library, 2)
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
            return {"error": f"{label}增强搜索失败: {str(e)}"}

    def extract_entities(content: str) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            entity_candidates = Settings().config.limits.memory.entity_candidates
            words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
            person_names = [w for w in words if len(w.split()) >= 1][:entity_candidates]
            return {
                "status": "success",
                "content_preview": content[:200],
                "extracted_entities": [{"name": name, "entity_type": "person", "source": "ner"} for name in person_names],
                "count": len(person_names),
            }
        except Exception as e:
            return {"error": f"提取{label}实体失败: {str(e)}"}

    def merge_entities(entity1_id: str, entity2_id: str) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            entity1 = _graph_store.get_entity(entity1_id, library)
            entity2 = _graph_store.get_entity(entity2_id, library)
            if not entity1:
                return {"error": f"实体 {entity1_id} 不存在"}
            if not entity2:
                return {"error": f"实体 {entity2_id} 不存在"}
            merged_memory_ids = list(set(entity1.memory_ids + entity2.memory_ids))
            merged_properties = {**entity1.properties, **entity2.properties}
            _graph_store.update_entity(entity1_id, {"memory_ids": merged_memory_ids, "properties": merged_properties}, library)
            _graph_store.delete_entity(entity2_id, library, hard=False)
            return {
                "status": "success",
                "merged_to": entity1_id,
                "merged_from": entity2_id,
                "merged_memory_ids_count": len(merged_memory_ids),
            }
        except Exception as e:
            return {"error": f"合并{label}实体失败: {str(e)}"}

    def get_entity_summary(entity_name_or_id: str) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            entity = _graph_store.get_entity(entity_name_or_id, library)
            if not entity:
                return {"error": f"实体 {entity_name_or_id} 不存在"}
            related = _graph_store.find_related_entities(entity_name_or_id, None, library, 1)
            return {
                "status": "success",
                "entity": _entity_to_dict(entity),
                "related_entity_count": len(related),
                "summary": f"{entity.name} 是类型为 {entity.entity_type} 的实体，关联记忆 {len(entity.memory_ids)} 条，直接关联实体 {len(related)} 个",
            }
        except Exception as e:
            return {"error": f"获取{label}实体摘要失败: {str(e)}"}

    def update_entity(entity_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            result = _graph_store.update_entity(entity_id, properties, library)
            if result is None:
                return {"error": f"实体 {entity_id} 不存在或更新失败"}
            return {"status": "success", "entity": _entity_to_dict(result)}
        except Exception as e:
            return {"error": f"更新{label}实体失败: {str(e)}"}

    def delete_entity(entity_id: str) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            success = _graph_store.delete_entity(entity_id, library, hard=False)
            return {"status": "success" if success else "failed", "entity_id": entity_id, "soft_delete": True}
        except Exception as e:
            return {"error": f"删除{label}实体失败: {str(e)}"}

    def update_relation(
        from_entity: str, to_entity: str, relation_type: str, strength: float
    ) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            updates = {"strength": strength}
            result = _graph_store.update_relation(from_entity, to_entity, relation_type, updates, library)
            if result is None:
                return {"error": "关系不存在或更新失败"}
            return {"status": "success", "relation": _relation_to_dict(result)}
        except Exception as e:
            return {"error": f"更新{label}关系失败: {str(e)}"}

    def delete_relation(from_entity: str, to_entity: str, relation_type: str) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            success = _graph_store.delete_relation(from_entity, to_entity, relation_type, library, hard=False)
            return {"status": "success" if success else "failed", "from_entity": from_entity, "to_entity": to_entity, "relation_type": relation_type, "soft_delete": True}
        except Exception as e:
            return {"error": f"删除{label}关系失败: {str(e)}"}

    def get_stats() -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            stats = _graph_store.get_stats(library)
            return {"status": "success", **stats}
        except Exception as e:
            return {"error": f"获取{label}统计失败: {str(e)}"}

    def export(format: str) -> Dict[str, Any]:
        if not _check_graph_store():
            return {"error": "图存储未初始化，请先调用 set_graph_dependencies()"}
        try:
            data = _graph_store.export(library)
            return {"status": "success", "format": format, "data": data, "entity_count": len(data.get("entities", [])), "relation_count": len(data.get("relations", []))}
        except Exception as e:
            return {"error": f"导出{label}数据失败: {str(e)}"}

    return {
        "create_entity": create_entity,
        "create_relation": create_relation,
        "query_entities": query_entities,
        "find_paths": find_paths,
        "search_related_memories": search_related_memories,
        "extract_entities": extract_entities,
        "merge_entities": merge_entities,
        "get_entity_summary": get_entity_summary,
        "update_entity": update_entity,
        "delete_entity": delete_entity,
        "update_relation": update_relation,
        "delete_relation": delete_relation,
        "get_stats": get_stats,
        "export": export,
    }


_GRAPH_LIBRARIES = [
    ("user", GraphLibrary.USER, "用户图"),
    ("thing", GraphLibrary.THING, "事物图"),
    ("concept", GraphLibrary.CONCEPT, "概念图"),
    ("event", GraphLibrary.EVENT, "事件图"),
]

for _prefix, _lib, _label in _GRAPH_LIBRARIES:
    _tools = _make_graph_tools(_lib, _label)
    for _op_name, _func in _tools.items():
        globals()[f"{_prefix}_graph_{_op_name}"] = _func
del _prefix, _lib, _label, _tools, _op_name, _func


_GRAPH_TOOL_SCHEMAS = {
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

_GRAPH_OPERATIONS = [
    ("create_entity", "在{label}中创建实体", ["main", "assistant"]),
    ("create_relation", "在{label}中创建关系", ["main", "assistant"]),
    ("query_entities", "查询{label}中的关联实体", ["main", "summary", "assistant"]),
    ("find_paths", "查找{label}中两个实体之间的路径", ["main", "assistant"]),
    ("search_related_memories", "{label}增强记忆搜索", ["main", "summary"]),
    ("extract_entities", "从内容中提取{label}实体", ["assistant"]),
    ("merge_entities", "合并{label}中的两个实体", ["assistant"]),
    ("get_entity_summary", "获取{label}实体摘要", ["summary", "assistant"]),
    ("update_entity", "更新{label}实体", ["assistant"]),
    ("delete_entity", "删除{label}实体", ["assistant"]),
    ("update_relation", "更新{label}关系", ["assistant"]),
    ("delete_relation", "删除{label}关系", ["assistant"]),
    ("get_stats", "获取{label}统计信息", ["summary", "assistant"]),
    ("export", "导出{label}数据", ["assistant"]),
]


def register_graph_tools():
    """注册所有图数据库工具到工具注册表

    注册 56 个图工具：
    - 主模型：20 个工具（用户图 5 + 事物图 5 + 概念图 5 + 事件图 5）
    - 摘要模型：12 个工具（用户图 3 + 事物图 3 + 概念图 3 + 事件图 3）
    - 记忆管理 Agent：24 个工具（用户图 6 + 事物图 6 + 概念图 6 + 事件图 6）
    """
    from .registry import tool_registry

    count = 0
    for prefix, lib, label in _GRAPH_LIBRARIES:
        for op_name, desc_template, tags in _GRAPH_OPERATIONS:
            name = f"{prefix}_graph_{op_name}"
            description = desc_template.format(label=label)
            parameters = _GRAPH_TOOL_SCHEMAS.get(op_name, {
                "type": "object",
                "properties": {}
            })
            tool_registry.register(
                name=name,
                description=description,
                parameters=parameters,
                function=globals()[name],
                tags=tags,
            )
            count += 1

    return count
