from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
