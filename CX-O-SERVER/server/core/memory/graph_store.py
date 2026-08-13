"""图存储抽象——记忆图数据的节点/边读写接口定义。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class GraphLibrary(Enum):
    """图库枚举，区分用户/事物/概念/事件四类记忆图，用于隔离各实体类型的存储命名空间。"""
    USER = "user"
    THING = "thing"
    CONCEPT = "concept"
    EVENT = "event"


class UserEntityType(Enum):
    """用户类实体类型枚举，其取值统一映射到 GraphLibrary.USER 图库。"""
    person = "person"
    user = "user"
    contact = "contact"


class ThingEntityType(Enum):
    """事物类实体类型枚举，其取值统一映射到 GraphLibrary.THING 图库。"""
    object = "object"
    item = "item"
    product = "product"


class ConceptEntityType(Enum):
    """概念类实体类型枚举，其取值统一映射到 GraphLibrary.CONCEPT 图库。"""
    concept = "concept"
    idea = "idea"
    topic = "topic"


class EventEntityType(Enum):
    """事件类实体类型枚举，其取值统一映射到 GraphLibrary.EVENT 图库。"""
    event = "event"
    activity = "activity"
    occurrence = "occurrence"


ENTITY_TYPE_TO_LIBRARY = {
    **{t.value: GraphLibrary.USER for t in UserEntityType},
    **{t.value: GraphLibrary.THING for t in ThingEntityType},
    **{t.value: GraphLibrary.CONCEPT for t in ConceptEntityType},
    **{t.value: GraphLibrary.EVENT for t in EventEntityType},
}


@dataclass
class Entity:
    """图实体数据类，承载实体 ID、名称、类型、属性字典与其关联的记忆 ID 列表。"""
    entity_id: str
    name: str
    entity_type: str
    properties: dict = field(default_factory=dict)
    memory_ids: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    deleted: bool = False


@dataclass
class Relation:
    """图关系数据类，描述两实体间的有向连接，含关系类型、强度与佐证记忆 ID 列表。"""
    from_entity: str
    to_entity: str
    relation_type: str
    strength: float = 1.0
    evidence_memory_ids: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    deleted: bool = False


class GraphStoreBase(ABC):
    """图存储抽象基类，定义实体/关系的增删改查、路径查找、统计与导出接口，供各后端实现。"""

    @abstractmethod
    def create_entity(self, entity: Entity, library: GraphLibrary) -> Entity:
        pass

    @abstractmethod
    def create_relation(self, relation: Relation, library: GraphLibrary) -> Relation:
        pass

    @abstractmethod
    def get_entity(self, entity_id: str, library: GraphLibrary) -> Entity | None:
        pass

    @abstractmethod
    def find_related_entities(
        self, entity_id: str, relation_type: str | None, library: GraphLibrary, depth: int = 1
    ) -> list[Entity]:
        pass

    @abstractmethod
    def find_paths(
        self, start_entity_id: str, end_entity_id: str, library: GraphLibrary, max_depth: int = 3
    ) -> list[list[Entity]]:
        pass

    @abstractmethod
    def delete_entity(self, entity_id: str, library: GraphLibrary, hard: bool = False) -> bool:
        pass

    @abstractmethod
    def delete_relation(self, from_entity: str, to_entity: str, relation_type: str, library: GraphLibrary, hard: bool = False) -> bool:
        pass

    @abstractmethod
    def update_entity(self, entity_id: str, updates: dict, library: GraphLibrary) -> Entity | None:
        pass

    @abstractmethod
    def update_relation(self, from_entity: str, to_entity: str, relation_type: str, updates: dict, library: GraphLibrary) -> Relation | None:
        pass

    @abstractmethod
    def get_stats(self, library: GraphLibrary) -> dict:
        pass

    @abstractmethod
    def export(self, library: GraphLibrary) -> dict:
        pass


class SQLiteGraphStore(GraphStoreBase):
    """基于 SQLite 图数据库实现的图存储，通过 GraphDatabase 的节点/边/遍历接口完成实体与关系的持久化。"""

    def __init__(self, graph_database):
        from server.core.graph import GraphDatabase
        self._db: GraphDatabase = graph_database

    def _node_type(self, library: GraphLibrary, entity_type: str) -> str:
        return f"{library.value}_{entity_type}"

    def _resolve_entity_id(self, entity_name_or_id: str, library: GraphLibrary) -> Optional[str]:
        """解析实体名称或ID为实体ID。

        先按 ID 查找；找不到时按 properties.name 在该 library 的节点中查找。
        返回解析后的 entity_id，找不到时返回 None。
        """
        if not entity_name_or_id:
            return None
        agent_id = self._db.agent_id
        # 先按 ID 查找
        node = self._db.nodes.get(entity_name_or_id, agent_id=agent_id)
        if node is not None:
            return node.id
        # 按名称查找：限定 library 对应的 node_type 前缀
        # node_type 格式为 "{library}_{entity_type}"，用 LIKE 匹配前缀
        try:
            rows = self._db.db.execute(
                "SELECT id FROM nodes WHERE json_extract(properties, '$.name') = ? AND type LIKE ? AND agent_id = ? LIMIT 1",
                (entity_name_or_id, f"{library.value}_%", agent_id),
            )
            if rows:
                return rows[0]["id"]
        except Exception:
            pass
        return None

    def _edge_type(self, library: GraphLibrary, relation_type: str) -> str:
        return f"{library.value}_{relation_type}"

    def _entity_from_node(self, node, library: GraphLibrary) -> Entity:
        # 将底层节点对象转换为 Entity 数据类
        props = node.properties or {}
        return Entity(
            entity_id=node.id,
            name=props.get("name", ""),
            entity_type=props.get("entity_type", ""),
            properties={k: v for k, v in props.items() if k not in ("name", "entity_type", "library", "memory_ids")},
            memory_ids=props.get("memory_ids", []),
            created_at=node.created_at if hasattr(node, "created_at") else datetime.now(),
            updated_at=node.updated_at if hasattr(node, "updated_at") else datetime.now(),
        )

    def _relation_from_edge(self, edge) -> Relation:
        props = edge.properties or {}
        return Relation(
            from_entity=edge.source_id,
            to_entity=edge.target_id,
            relation_type=props.get("original_relation_type", edge.relation_type.split("_", 1)[-1] if "_" in edge.relation_type else edge.relation_type),
            strength=props.get("strength", 1.0),
            evidence_memory_ids=props.get("evidence_memory_ids", []),
            created_at=edge.created_at if hasattr(edge, "created_at") else datetime.now(),
        )

    def create_entity(self, entity: Entity, library: GraphLibrary) -> Entity:
        """在指定库中创建实体节点并返回持久化结果。"""
        from server.core.graph.models import NodeCreate
        node_type = self._node_type(library, entity.entity_type)
        properties = {
            "name": entity.name,
            "entity_type": entity.entity_type,
            "library": library.value,
            "memory_ids": entity.memory_ids,
            **entity.properties,
        }
        node_create = NodeCreate(
            type=node_type,
            properties=properties,
            text_content=entity.name,
        )
        node = self._db.nodes.create(node_create)
        return self._entity_from_node(node, library)

    def create_relation(self, relation: Relation, library: GraphLibrary) -> Relation:
        """在指定库中创建关系边并返回持久化结果。"""
        from server.core.graph.models import EdgeCreate
        # 解析实体名称到 ID
        from_id = self._resolve_entity_id(relation.from_entity, library)
        to_id = self._resolve_entity_id(relation.to_entity, library)
        if from_id is None:
            raise ValueError(f"源实体不存在: {relation.from_entity}")
        if to_id is None:
            raise ValueError(f"目标实体不存在: {relation.to_entity}")
        edge_type = self._edge_type(library, relation.relation_type)
        properties = {
            "original_relation_type": relation.relation_type,
            "strength": relation.strength,
            "evidence_memory_ids": relation.evidence_memory_ids,
        }
        edge_create = EdgeCreate(
            source_id=from_id,
            target_id=to_id,
            relation_type=edge_type,
            properties=properties,
            text_content=f"{relation.from_entity} {relation.relation_type} {relation.to_entity}",
        )
        edge = self._db.edges.create(edge_create)
        return self._relation_from_edge(edge)

    def get_entity(self, entity_id: str, library: GraphLibrary) -> Entity | None:
        """按 ID（或名称）获取实体，不存在返回 None。"""
        resolved_id = self._resolve_entity_id(entity_id, library)
        if resolved_id is None:
            return None
        node = self._db.nodes.get(resolved_id)
        if node is None:
            return None
        return self._entity_from_node(node, library)

    def find_related_entities(
        self, entity_id: str, relation_type: str | None, library: GraphLibrary, depth: int = 1
    ) -> list[Entity]:
        """查找与指定实体关联的实体列表（可按关系类型过滤）。"""
        resolved_id = self._resolve_entity_id(entity_id, library)
        if resolved_id is None:
            return []
        direction = "both"
        neighbors = self._db.traversal.get_neighbors(resolved_id, max_depth=depth, direction=direction)
        entities = []
        for node, edges in neighbors:
            if relation_type is not None:
                matched = any(
                    self._edge_type(library, relation_type) == e.relation_type for e in edges
                )
                if not matched:
                    continue
            entities.append(self._entity_from_node(node, library))
        return entities

    def find_paths(
        self, start_entity_id: str, end_entity_id: str, library: GraphLibrary, max_depth: int = 3
    ) -> list[list[Entity]]:
        """查找两个实体间所有可达路径的实体列表。"""
        start_id = self._resolve_entity_id(start_entity_id, library)
        end_id = self._resolve_entity_id(end_entity_id, library)
        if start_id is None or end_id is None:
            return []
        paths = self._db.traversal.all_paths(start_id, end_id, max_length=max_depth)
        result = []
        for path in paths:
            path_entities = []
            for nid in path.path:
                entity = self.get_entity(nid, library)
                if entity:
                    path_entities.append(entity)
            if path_entities:
                result.append(path_entities)
        return result

    def delete_entity(self, entity_id: str, library: GraphLibrary, hard: bool = False) -> bool:
        """删除实体（hard=True 物理删除，否则软删除）。"""
        resolved_id = self._resolve_entity_id(entity_id, library)
        if resolved_id is None:
            return False
        if hard:
            self._db.nodes.delete(resolved_id, cascade=True)
        else:
            from server.core.graph.models import NodeUpdate
            node = self._db.nodes.get(resolved_id)
            if node:
                existing_props = dict(node.properties or {})
                existing_props["deleted"] = True
                self._db.nodes.update(resolved_id, NodeUpdate(properties=existing_props))
        return True

    def delete_relation(self, from_entity: str, to_entity: str, relation_type: str, library: GraphLibrary, hard: bool = False) -> bool:
        """删除两个实体间的指定关系（hard=True 物理删除）。"""
        from_id = self._resolve_entity_id(from_entity, library)
        to_id = self._resolve_entity_id(to_entity, library)
        if from_id is None or to_id is None:
            return False
        edge_type = self._edge_type(library, relation_type)
        edges = self._db.edges.search(relation_type=edge_type, source_id=from_id, limit=100)
        for edge in edges.items:
            if edge.target_id == to_id:
                if hard:
                    self._db.edges.delete(edge.id)
                else:
                    from server.core.graph.models import EdgeUpdate
                    existing_props = dict(edge.properties or {})
                    existing_props["deleted"] = True
                    self._db.edges.update(edge.id, EdgeUpdate(properties=existing_props))
                return True
        return False

    def update_entity(self, entity_id: str, updates: dict, library: GraphLibrary) -> Entity | None:
        """更新实体属性并返回更新后的实体。"""
        resolved_id = self._resolve_entity_id(entity_id, library)
        if resolved_id is None:
            return None
        from server.core.graph.models import NodeUpdate
        node = self._db.nodes.get(resolved_id)
        if node is None:
            return None
        existing_props = dict(node.properties or {})
        existing_props.update(updates)
        node = self._db.nodes.update(resolved_id, NodeUpdate(properties=existing_props))
        if node is None:
            return None
        return self._entity_from_node(node, library)

    def update_relation(self, from_entity: str, to_entity: str, relation_type: str, updates: dict, library: GraphLibrary) -> Relation | None:
        """更新两个实体间指定关系的属性并返回更新后的关系。"""
        from_id = self._resolve_entity_id(from_entity, library)
        to_id = self._resolve_entity_id(to_entity, library)
        if from_id is None or to_id is None:
            return None
        edge_type = self._edge_type(library, relation_type)
        edges = self._db.edges.search(relation_type=edge_type, source_id=from_id, limit=100)
        for edge in edges.items:
            if edge.target_id == to_id:
                from server.core.graph.models import EdgeUpdate
                existing_props = dict(edge.properties or {})
                existing_props.update(updates)
                updated = self._db.edges.update(edge.id, EdgeUpdate(properties=existing_props))
                if updated:
                    return self._relation_from_edge(updated)
        return None

    def get_stats(self, library: GraphLibrary) -> dict:
        """统计指定图库的实体节点数与关系边数，返回含 library 标识的计数字典。"""
        node_type_prefix = f"{library.value}_"
        result = self._db.nodes.search(node_type=None, limit=10000)
        node_count = sum(1 for n in result.items if n.type.startswith(node_type_prefix))
        edge_type_prefix = f"{library.value}_"
        edge_result = self._db.edges.search(relation_type=None, limit=10000)
        edge_count = sum(1 for e in edge_result.items if e.relation_type.startswith(edge_type_prefix))
        return {
            "library": library.value,
            "entity_count": node_count,
            "relation_count": edge_count,
        }

    def export(self, library: GraphLibrary) -> dict:
        """导出指定图库的全部实体与关系，返回含 library、entities 与 relations 列表的字典。"""
        node_type_prefix = f"{library.value}_"
        result = self._db.nodes.search(node_type=None, limit=10000)
        entities = []
        for node in result.items:
            if not node.type.startswith(node_type_prefix):
                continue
            entities.append(self._entity_from_node(node, library))
        edge_type_prefix = f"{library.value}_"
        edge_result = self._db.edges.search(relation_type=None, limit=10000)
        relations = []
        for edge in edge_result.items:
            if not edge.relation_type.startswith(edge_type_prefix):
                continue
            relations.append(self._relation_from_edge(edge))
        return {
            "library": library.value,
            "entities": [{"id": e.entity_id, "name": e.name, "type": e.entity_type, "properties": e.properties} for e in entities],
            "relations": [{"from": r.from_entity, "to": r.to_entity, "type": r.relation_type, "strength": r.strength} for r in relations],
        }
