"""
图数据库数据模型
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class GraphNode:
    """图节点"""
    id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    text_content: Optional[str] = None
    vector_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    agent_id: str = "default"

    @classmethod
    def create(
        cls,
        type: str,
        properties: Dict[str, Any] = None,
        text_content: Optional[str] = None,
        agent_id: str = "default",
    ) -> "GraphNode":
        now = datetime.now()
        return cls(
            id=str(uuid.uuid4()),
            type=type,
            properties=properties or {},
            text_content=text_content,
            vector_id=None,
            created_at=now,
            updated_at=now,
            agent_id=agent_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "properties": self.properties,
            "text_content": self.text_content,
            "vector_id": self.vector_id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        properties = data.get("properties", {})
        if isinstance(properties, str):
            properties = json.loads(properties)

        return cls(
            id=data["id"],
            type=data["type"],
            properties=properties,
            text_content=data.get("text_content"),
            vector_id=data.get("vector_id"),
            created_at=created_at or datetime.now(),
            updated_at=updated_at or datetime.now(),
            agent_id=data.get("agent_id", "default"),
        )


@dataclass
class GraphEdge:
    """图边（关系）"""
    id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    text_content: Optional[str] = None
    vector_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    agent_id: str = "default"

    @classmethod
    def create(
        cls,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Dict[str, Any] = None,
        text_content: Optional[str] = None,
        agent_id: str = "default",
    ) -> "GraphEdge":
        return cls(
            id=str(uuid.uuid4()),
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=properties or {},
            text_content=text_content,
            vector_id=None,
            created_at=datetime.now(),
            agent_id=agent_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "properties": self.properties,
            "text_content": self.text_content,
            "vector_id": self.vector_id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        properties = data.get("properties", {})
        if isinstance(properties, str):
            properties = json.loads(properties)

        return cls(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation_type=data["relation_type"],
            properties=properties,
            text_content=data.get("text_content"),
            vector_id=data.get("vector_id"),
            created_at=created_at or datetime.now(),
            agent_id=data.get("agent_id", "default"),
        )


@dataclass
class NodeCreate:
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    text_content: Optional[str] = None
    agent_id: str = "default"


@dataclass
class NodeUpdate:
    type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None


@dataclass
class EdgeCreate:
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    text_content: Optional[str] = None
    agent_id: str = "default"


@dataclass
class EdgeUpdate:
    relation_type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None


@dataclass
class SearchResult:
    items: List[Any]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass
class SemanticSearchResult:
    node: GraphNode
    score: float


@dataclass
class PathResult:
    path: List[str]
    edges: List[GraphEdge]
    length: int
