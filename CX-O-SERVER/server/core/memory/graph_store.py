from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class GraphLibrary(Enum):
    USER = "user"
    THING = "thing"
    CONCEPT = "concept"
    EVENT = "event"


class UserEntityType(Enum):
    person = "person"
    user = "user"
    contact = "contact"


class ThingEntityType(Enum):
    object = "object"
    item = "item"
    product = "product"


class ConceptEntityType(Enum):
    concept = "concept"
    idea = "idea"
    topic = "topic"


class EventEntityType(Enum):
    event = "event"
    activity = "activity"
    occurrence = "occurrence"


class UserRelationType(Enum):
    knows = "knows"
    friend = "friend"
    family = "family"
    colleague = "colleague"
    enemy = "enemy"


class ThingRelationType(Enum):
    owns = "owns"
    part_of = "part_of"
    similar_to = "similar_to"
    located_at = "located_at"
    made_of = "made_of"


class ConceptRelationType(Enum):
    related_to = "related_to"
    subtopic_of = "subtopic_of"
    opposite_of = "opposite_of"
    implies = "implies"


class EventRelationType(Enum):
    caused = "caused"
    followed_by = "followed_by"
    concurrent_with = "concurrent_with"
    prevents = "prevents"


ENTITY_TYPE_TO_LIBRARY = {
    **{t.value: GraphLibrary.USER for t in UserEntityType},
    **{t.value: GraphLibrary.THING for t in ThingEntityType},
    **{t.value: GraphLibrary.CONCEPT for t in ConceptEntityType},
    **{t.value: GraphLibrary.EVENT for t in EventEntityType},
}


@dataclass
class Entity:
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
    from_entity: str
    to_entity: str
    relation_type: str
    strength: float = 1.0
    evidence_memory_ids: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    deleted: bool = False


class GraphStoreBase(ABC):

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
