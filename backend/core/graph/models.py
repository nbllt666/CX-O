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

    @classmethod
    def create(
        cls,
        type: str,
        properties: Dict[str, Any] = None,
        text_content: Optional[str] = None,
    ) -> "GraphNode":
        """创建新节点（自动生成 ID）"""
        now = datetime.now()
        return cls(
            id=str(uuid.uuid4()),
            type=type,
            properties=properties or {},
            text_content=text_content,
            vector_id=None,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type,
            "properties": self.properties,
            "text_content": self.text_content,
            "vector_id": self.vector_id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        """从字典创建"""
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

    @classmethod
    def create(
        cls,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Dict[str, Any] = None,
        text_content: Optional[str] = None,
    ) -> "GraphEdge":
        """创建新边（自动生成 ID）"""
        return cls(
            id=str(uuid.uuid4()),
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            properties=properties or {},
            text_content=text_content,
            vector_id=None,
            created_at=datetime.now(),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "properties": self.properties,
            "text_content": self.text_content,
            "vector_id": self.vector_id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        """从字典创建"""
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
        )


@dataclass
class NodeCreate:
    """创建节点的输入"""
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    text_content: Optional[str] = None


@dataclass
class NodeUpdate:
    """更新节点的输入"""
    type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None


@dataclass
class EdgeCreate:
    """创建边的输入"""
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    text_content: Optional[str] = None


@dataclass
class EdgeUpdate:
    """更新边的输入"""
    relation_type: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    text_content: Optional[str] = None


@dataclass
class SearchResult:
    """搜索结果"""
    items: List[Any]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass
class SemanticSearchResult:
    """语义搜索结果"""
    node: GraphNode
    score: float


@dataclass
class PathResult:
    """路径查询结果"""
    path: List[str]
    edges: List[GraphEdge]
    length: int
