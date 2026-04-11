from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from neo4j import GraphDatabase


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


class Neo4jGraphStore(GraphStoreBase):
    def __init__(self, uri: str, username: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(username, password))

    def close(self):
        self._driver.close()

    def _get_label(self, library: GraphLibrary) -> str:
        return library.value.capitalize()

    def _get_id_field(self, library: GraphLibrary) -> str:
        return self._get_label(library).lower()

    def _ensure_session(self):
        return self._driver.session()

    def create_entity(self, entity: Entity, library: GraphLibrary) -> Entity:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            query = f"MATCH (e:{label} {{{id_field}: $entity_id}}) RETURN e"
            existing = session.run(query, entity_id=entity.entity_id).single()
            if existing:
                return self.update_entity(entity.entity_id, entity.properties, library) or entity

            query = f"""
            CREATE (e:{label} {{
                {id_field}: $entity_id,
                name: $name,
                entity_type: $entity_type,
                properties: $properties,
                memory_ids: $memory_ids,
                created_at: $created_at,
                updated_at: $updated_at,
                deleted: $deleted
            }})
            RETURN e
            """
            result = session.run(
                query,
                entity_id=entity.entity_id,
                name=entity.name,
                entity_type=entity.entity_type,
                properties=entity.properties,
                memory_ids=entity.memory_ids,
                created_at=entity.created_at.isoformat(),
                updated_at=entity.updated_at.isoformat(),
                deleted=entity.deleted,
            )
            record = result.single()
            if record:
                return self._record_to_entity(record["e"], library)
            return entity

    def create_relation(self, relation: Relation, library: GraphLibrary) -> Relation:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            rel_type = f"{library.value.capitalize()}_{relation.relation_type}"
            query = f"""
            MATCH (e1:{label} {{{id_field}: $from_entity}}), (e2:{label} {{{id_field}: $to_entity}})
            CREATE (e1)-[r:{rel_type} {{
                from_entity: $from_entity,
                to_entity: $to_entity,
                relation_type: $relation_type,
                strength: $strength,
                evidence_memory_ids: $evidence_memory_ids,
                created_at: $created_at,
                deleted: $deleted
            }}]->(e2)
            RETURN r
            """
            result = session.run(
                query,
                from_entity=relation.from_entity,
                to_entity=relation.to_entity,
                relation_type=relation.relation_type,
                strength=relation.strength,
                evidence_memory_ids=relation.evidence_memory_ids,
                created_at=relation.created_at.isoformat(),
                deleted=relation.deleted,
            )
            record = result.single()
            if record:
                return self._record_to_relation(record["r"])
            return relation

    def get_entity(self, entity_id: str, library: GraphLibrary) -> Entity | None:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            query = f"MATCH (e:{label} {{{id_field}: $entity_id}}) RETURN e"
            result = session.run(query, entity_id=entity_id)
            record = result.single()
            if record:
                return self._record_to_entity(record["e"], library)
            return None

    def find_related_entities(
        self, entity_id: str, relation_type: str | None, library: GraphLibrary, depth: int = 1
    ) -> list[Entity]:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            if relation_type:
                rel_pattern = f"[r:{library.value.capitalize()}_{relation_type}*1..{depth}]"
            else:
                rel_pattern = f"[r:*1..{depth}]"
            query = f"MATCH (e1:{label} {{{id_field}: $entity_id}})-{rel_pattern}-(e2:{label}) WHERE e1 <> e2 AND e2.deleted = false RETURN DISTINCT e2"
            result = session.run(query, entity_id=entity_id)
            return [self._record_to_entity(record["e2"], library) for record in result]

    def find_paths(
        self, start_entity_id: str, end_entity_id: str, library: GraphLibrary, max_depth: int = 3
    ) -> list[list[Entity]]:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            query = f"MATCH path = (e1:{label} {{{id_field}: $start_entity_id}})-[:{library.value.capitalize()}*1..{max_depth}]-(e2:{label}) WHERE e2.{id_field} = $end_entity_id AND e2.deleted = false RETURN path"
            result = session.run(query, start_entity_id=start_entity_id, end_entity_id=end_entity_id)
            paths = []
            for record in result:
                path = record["path"]
                entities = []
                for node in path.nodes:
                    entities.append(self._record_to_entity(node, library))
                paths.append(entities)
            return paths

    def delete_entity(self, entity_id: str, library: GraphLibrary, hard: bool = False) -> bool:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            if hard:
                query = f"MATCH (e:{label} {{{id_field}: $entity_id}}) DETACH DELETE e"
                session.run(query, entity_id=entity_id)
                return True
            else:
                query = f"MATCH (e:{label} {{{id_field}: $entity_id}}) SET e.deleted = true, e.updated_at = $updated_at"
                session.run(query, entity_id=entity_id, updated_at=datetime.now().isoformat())
                return True

    def delete_relation(self, from_entity: str, to_entity: str, relation_type: str, library: GraphLibrary, hard: bool = False) -> bool:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            rel_type = f"{library.value.capitalize()}_{relation_type}"
            if hard:
                query = f"MATCH (e1:{label} {{{id_field}: $from_entity}})-[r:{rel_type}]->(e2:{label} {{{id_field}: $to_entity}}) DELETE r"
                session.run(query, from_entity=from_entity, to_entity=to_entity)
                return True
            else:
                query = f"MATCH (e1:{label} {{{id_field}: $from_entity}})-[r:{rel_type}]->(e2:{label} {{{id_field}: $to_entity}}) SET r.deleted = true"
                session.run(query, from_entity=from_entity, to_entity=to_entity)
                return True

    def update_entity(self, entity_id: str, updates: dict, library: GraphLibrary) -> Entity | None:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            updates["updated_at"] = datetime.now().isoformat()
            set_clause = ", ".join([f"e.{k} = ${k}" for k in updates.keys()])
            query = f"MATCH (e:{label} {{{id_field}: $entity_id}}) SET {set_clause} RETURN e"
            params = {"entity_id": entity_id, **updates}
            result = session.run(query, **params)
            record = result.single()
            if record:
                return self._record_to_entity(record["e"], library)
            return None

    def update_relation(self, from_entity: str, to_entity: str, relation_type: str, updates: dict, library: GraphLibrary) -> Relation | None:
        with self._ensure_session() as session:
            label = self._get_label(library)
            id_field = self._get_id_field(library)
            rel_type = f"{library.value.capitalize()}_{relation_type}"
            set_clause = ", ".join([f"r.{k} = ${k}" for k in updates.keys()])
            query = f"MATCH (e1:{label} {{{id_field}: $from_entity}})-[r:{rel_type}]->(e2:{label} {{{id_field}: $to_entity}}) SET {set_clause} RETURN r"
            params = {"from_entity": from_entity, "to_entity": to_entity, **updates}
            result = session.run(query, **params)
            record = result.single()
            if record:
                return self._record_to_relation(record["r"])
            return None

    def get_stats(self, library: GraphLibrary) -> dict:
        with self._ensure_session() as session:
            label = self._get_label(library)
            query = f"MATCH (e:{label}) WHERE e.deleted = false RETURN count(e) as entity_count"
            entity_count = session.run(query).single()["entity_count"]

            query = f"MATCH ()-[r:{library.value.capitalize()}]->() WHERE r.deleted = false RETURN count(r) as relation_count"
            relation_count = session.run(query).single()["relation_count"]

            return {
                "library": library.value,
                "entity_count": entity_count,
                "relation_count": relation_count,
            }

    def export(self, library: GraphLibrary) -> dict:
        with self._ensure_session() as session:
            label = self._get_label(library)
            query = f"MATCH (e:{label}) WHERE e.deleted = false RETURN collect(e) as entities"
            entities_result = session.run(query).single()
            entities = [self._record_to_entity(e, library) for e in entities_result["entities"]] if entities_result else []

            query = f"MATCH ()-[r:{library.value.capitalize()}]->() WHERE r.deleted = false RETURN collect(r) as relations"
            relations_result = session.run(query).single()
            relations = [self._record_to_relation(r) for r in relations_result["relations"]] if relations_result else []

            return {
                "library": library.value,
                "entities": [vars(e) for e in entities],
                "relations": [vars(r) for r in relations],
            }

    def _record_to_entity(self, record: Any, library: GraphLibrary) -> Entity:
        props = dict(record)
        for key in ["created_at", "updated_at"]:
            if key in props and isinstance(props[key], str):
                props[key] = datetime.fromisoformat(props[key])
        id_field = self._get_id_field(library)
        return Entity(
            entity_id=props.pop(id_field),
            name=props.pop("name"),
            entity_type=props.pop("entity_type"),
            properties=props.pop("properties", {}),
            memory_ids=props.pop("memory_ids", []),
            created_at=props.pop("created_at"),
            updated_at=props.pop("updated_at"),
            deleted=props.pop("deleted", False),
        )

    def _record_to_relation(self, record: Any) -> Relation:
        props = dict(record)
        for key in ["created_at"]:
            if key in props and isinstance(props[key], str):
                props[key] = datetime.fromisoformat(props[key])
        return Relation(
            from_entity=props.pop("from_entity"),
            to_entity=props.pop("to_entity"),
            relation_type=props.pop("relation_type"),
            strength=props.pop("strength", 1.0),
            evidence_memory_ids=props.pop("evidence_memory_ids", []),
            created_at=props.pop("created_at"),
            deleted=props.pop("deleted", False),
        )