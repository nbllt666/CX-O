"""MemoryManager mixin: Graph store integration (sync, entity extraction).

Extracted from manager.py as part of H5 mixin split.
"""
import asyncio
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from server.config import Settings
from server.core.exceptions import DatabaseError, MemoryOperationError, VectorStoreError

from ._common import json_dumps, json_loads, logger

if TYPE_CHECKING:
    from server.core.memory.graph_store import GraphStoreBase


class _GraphIntegrationMixin:
    """Graph integration mixin: graph store sync and entity extraction."""

    def _init_graph_stores(self) -> None:
        self._graph_enabled = False
        self._graph_stores = {}
        logger.info("图数据库已移至独立模块（server/core/graph），MemoryManager 不再管理图存储")

    def _sync_to_graph(
        self,
        memory_id: int,
        content: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        if not self._graph_enabled or not self._graph_stores:
            logger.debug("图同步功能当前未启用，跳过同步")
            return

        try:
            from server.core.memory.graph_store import (
                Entity,
                GraphLibrary,
                ENTITY_TYPE_TO_LIBRARY,
            )

            extracted_entities = self._extract_entities_from_content(content)

            for entity_info in extracted_entities:
                entity_type = entity_info.get("type", "concept")
                entity_name = entity_info.get("name", "")

                if not entity_name:
                    continue

                library = ENTITY_TYPE_TO_LIBRARY.get(entity_type, GraphLibrary.CONCEPT)
                library_key = library.value

                if library_key not in self._graph_stores:
                    continue

                import hashlib
                entity_id = hashlib.md5(f"{entity_name}:{entity_type}".encode()).hexdigest()[:16]

                entity = Entity(
                    entity_id=entity_id,
                    name=entity_name,
                    entity_type=entity_type,
                    properties={"memory_id": memory_id},
                    memory_ids=[str(memory_id)],
                )

                try:
                    self._graph_stores[library_key].create_entity(entity, library)
                except Exception as e:
                    logger.warning(f"创建图实体失败: {entity_name}, error={e}")

            for i, entity_a in enumerate(extracted_entities):
                for entity_b in extracted_entities[i + 1:]:
                    entity_type_a = entity_a.get("type", "concept")
                    entity_type_b = entity_b.get("type", "concept")

                    library_a = ENTITY_TYPE_TO_LIBRARY.get(entity_type_a, GraphLibrary.CONCEPT)
                    library_b = ENTITY_TYPE_TO_LIBRARY.get(entity_type_b, GraphLibrary.CONCEPT)

                    if library_a != library_b:
                        continue

                    library_key = library_a.value

                    if library_key not in self._graph_stores:
                        continue

                    import hashlib
                    from server.core.memory.graph_store import Relation

                    entity_id_a = hashlib.md5(f"{entity_a['name']}:{entity_type_a}".encode()).hexdigest()[:16]
                    entity_id_b = hashlib.md5(f"{entity_b['name']}:{entity_type_b}".encode()).hexdigest()[:16]

                    relation = Relation(
                        from_entity=entity_id_a,
                        to_entity=entity_id_b,
                        relation_type="related_to",
                        strength=0.5,
                        evidence_memory_ids=[str(memory_id)],
                    )

                    try:
                        self._graph_stores[library_key].create_relation(relation, library_a)
                    except Exception as e:
                        logger.warning(f"创建图关系失败: {entity_a['name']} -> {entity_b['name']}, error={e}")

        except ImportError:
            logger.warning("图数据库模块未安装")
        except Exception as e:
            logger.warning(f"图同步失败: memory_id={memory_id}, error={e}")

    def _extract_entities_from_content(self, content: str) -> List[Dict]:
        """从内容中提取实体

        优先使用 LLM 进行实体识别，准确率更高
        如果 LLM 不可用，则使用改进的正则表达式方法作为后备

        Args:
            content: 输入文本内容

        Returns:
            实体列表，每项包含 name, type
        """
        if self._llm_client:
            return self._extract_entities_with_llm(content)
        return self._extract_entities_with_regex(content)

    def _extract_entities_with_llm(self, content: str) -> List[Dict]:
        """使用 LLM 进行实体识别"""
        import json

        try:
            prompt = f"""从以下文本中提取实体，并以JSON数组格式返回。
实体类型包括：person(人物), organization(组织), location(地点), thing(物品), concept(概念), event(事件)。

只返回JSON数组，每项包含name和type字段。
格式示例：[{{"name": "张三", "type": "person"}}, {{"name": "北京", "type": "location"}}]

文本：
{content[:Settings().config.limits.memory.entity_extract_max_content]}

JSON响应："""

            response = self._llm_client.chat([{"role": "user", "content": prompt}])
            if response and isinstance(response, str):
                json_start = response.find('[')
                json_end = response.rfind(']') + 1
                if json_start != -1 and json_end > json_start:
                    entities = json.loads(response[json_start:json_end])
                    valid_types = {"person", "organization", "location", "thing", "concept", "event"}
                    return [
                        e for e in entities
                        if isinstance(e, dict) and "name" in e and "type" in e
                        and e.get("type", "").lower() in valid_types
                        and len(e.get("name", "")) > 1
                    ]
        except Exception as e:
            logger.debug(f"LLM实体识别失败，使用正则后备: {e}")

        return self._extract_entities_with_regex(content)

    def _extract_entities_with_regex(self, content: str) -> List[Dict]:
        """使用正则表达式提取实体（改进版）"""
        import re

        entities = []
        content_lower = content.lower()

        person_patterns = [
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b',
        ]
        for pattern in person_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if len(match) > 2:
                    entities.append({"name": match.strip(), "type": "person"})

        chinese_names = re.findall(r'[\u4e00-\u9fa5]{2,4}(?:同学|先生|女士|老师|老板|经理|工程师|设计师|医生|律师)', content)
        for name in chinese_names:
            entities.append({"name": name, "type": "person"})

        thing_keywords = {
            "product": ["产品", "商品", "物品", "东西"],
            "document": ["文件", "文档", "报告", "合同", "协议", "书", "文章"],
            "device": ["手机", "电脑", "电脑", "服务器", "路由器", "相机"],
            "location": ["房间", "办公室", "桌子", "椅子", "房子", "建筑", "医院", "学校", "公司"],
            "vehicle": ["车", "汽车", "自行车", "摩托车", "飞机", "火车"],
        }
        for category, keywords in thing_keywords.items():
            for keyword in keywords:
                if keyword in content_lower:
                    pattern = rf'{re.escape(keyword)}[是为]*(.{{0,10}}?)(?:的|[,，.]|$)'
                    matches = re.findall(pattern, content)
                    for match in matches:
                        cleaned = match.strip().rstrip('的，,。')
                        if cleaned and 1 < len(cleaned) < 30:
                            entities.append({"name": cleaned, "type": "thing"})

        concept_keywords = ["概念", "思想", "理论", "观点", "想法", "理念", "原则", "方法", "方案", "策略", "计划"]
        for keyword in concept_keywords:
            if keyword in content_lower:
                pattern = rf'{re.escape(keyword)}[是为]*(.{{0,20}}?)(?:[，,。]|$)'
                matches = re.findall(pattern, content)
                for match in matches:
                    cleaned = match.strip().rstrip('的，,。')
                    if cleaned and 2 < len(cleaned) < 40:
                        entities.append({"name": cleaned, "type": "concept"})

        event_keywords = ["会议", "活动", "事件", "发生", "举办", "参加", "完成", "开始", "结束", "发布", "庆祝", "讨论", "学习", "培训"]
        for keyword in event_keywords:
            if keyword in content_lower:
                pattern = rf'(.{{0,8}}{re.escape(keyword)}.{0,8})(?:[，,。]|$)'
                matches = re.findall(pattern, content)
                for match in matches:
                    cleaned = match.strip().rstrip('，,。')
                    if cleaned and 4 < len(cleaned) < 50:
                        entities.append({"name": cleaned, "type": "event"})

        seen = set()
        unique_entities = []
        for entity in entities:
            key = (entity["name"].lower(), entity["type"])
            if key not in seen and not any(
                e["name"].lower() in entity["name"].lower() and e["type"] == entity["type"]
                for e in unique_entities
            ):
                seen.add(key)
                unique_entities.append(entity)

        return unique_entities[:Settings().config.limits.memory.max_entities]

    def _update_graph_on_delete(self, memory_id: int) -> None:
        if not self._graph_enabled or not self._graph_stores:
            logger.debug("图同步功能当前未启用，跳过删除同步")
            return

        try:
            from server.core.memory.graph_store import GraphLibrary

            for library_key, store in self._graph_stores.items():
                try:
                    library = GraphLibrary[library_key.upper()]
                except KeyError:
                    continue

                try:
                    entities = store.find_related_entities(
                        entity_id=str(memory_id),
                        relation_type=None,
                        library=library,
                        depth=1,
                    )
                except Exception:
                    continue

                for entity in entities:
                    if str(memory_id) in entity.memory_ids:
                        new_memory_ids = [mid for mid in entity.memory_ids if mid != str(memory_id)]
                        if new_memory_ids != entity.memory_ids:
                            store.update_entity(
                                entity.entity_id,
                                {"memory_ids": new_memory_ids},
                                library,
                            )

        except ImportError:
            logger.warning("图数据库模块未安装")
        except Exception as e:
            logger.warning(f"更新图数据库失败: memory_id={memory_id}, error={e}")
