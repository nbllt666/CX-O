"""
图可视化导出
"""

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.core.graph.database import Database
from server.core.graph.models import GraphNode, GraphEdge

logger = logging.getLogger(__name__)


class GraphExporter:
    """图数据导出器"""

    def __init__(self, db: Database):
        self.db = db

    def export_json(self, file_path: Optional[str] = None) -> str:
        """导出为 JSON 格式

        Args:
            file_path: 可选，导出文件路径

        Returns:
            JSON 字符串
        """
        nodes = self.db.execute("SELECT * FROM nodes")
        edges = self.db.execute("SELECT * FROM edges")

        graph_data = {
            "metadata": {
                "exported_at": datetime.now().isoformat(),
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
            "nodes": [self._node_to_dict(dict(row)) for row in nodes],
            "edges": [self._edge_to_dict(dict(row)) for row in edges],
        }

        json_str = json.dumps(graph_data, ensure_ascii=False, indent=2)

        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            logger.info(f"Graph exported to {file_path}")

        return json_str

    def export_graphml(self, file_path: str) -> str:
        """导出为 GraphML 格式

        Args:
            file_path: 导出文件路径

        Returns:
            GraphML 字符串
        """
        nodes = self.db.execute("SELECT * FROM nodes")
        edges = self.db.execute("SELECT * FROM edges")

        root = ET.Element("graphml")
        root.set("xmlns", "http://graphml.graphdrawing.org/xmlns")
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        root.set("xsi:schemaLocation", "http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd")

        key_attrs = ET.SubElement(root, "key")
        key_attrs.set("id", "d0")
        key_attrs.set("for", "node")
        key_attrs.set("attr.name", "label")
        key_attrs.set("attr.type", "string")

        key_type = ET.SubElement(root, "key")
        key_type.set("id", "d1")
        key_type.set("for", "node")
        key_type.set("attr.name", "type")
        key_type.set("attr.type", "string")

        key_props = ET.SubElement(root, "key")
        key_props.set("id", "d2")
        key_props.set("for", "node")
        key_props.set("attr.name", "properties")
        key_props.set("attr.type", "string")

        key_weight = ET.SubElement(root, "key")
        key_weight.set("id", "d3")
        key_weight.set("for", "edge")
        key_weight.set("attr.name", "weight")
        key_weight.set("attr.type", "double")

        key_label = ET.SubElement(root, "key")
        key_label.set("id", "d4")
        key_label.set("for", "edge")
        key_label.set("attr.name", "label")
        key_label.set("attr.type", "string")

        graph = ET.SubElement(root, "graph")
        graph.set("edgedefault", "undirected")

        for row in nodes:
            node_data = dict(row)
            node_id = node_data["id"]

            node_elem = ET.SubElement(graph, "node")
            node_elem.set("id", node_id)

            data_label = ET.SubElement(node_elem, "data")
            data_label.set("key", "d0")
            data_label.text = node_data.get("name", node_id)

            data_type = ET.SubElement(node_elem, "data")
            data_type.set("key", "d1")
            data_type.text = node_data.get("type", "")

            properties = json.dumps(node_data.get("properties", {}), ensure_ascii=False)
            data_props = ET.SubElement(node_elem, "data")
            data_props.set("key", "d2")
            data_props.text = properties

        for row in edges:
            edge_data = dict(row)
            edge_id = edge_data["id"]
            source = edge_data["source_id"]
            target = edge_data["target_id"]

            edge_elem = ET.SubElement(graph, "edge")
            edge_elem.set("id", edge_id)
            edge_elem.set("source", source)
            edge_elem.set("target", target)

            weight = edge_data.get("weight", 1.0)
            data_weight = ET.SubElement(edge_elem, "data")
            data_weight.set("key", "d3")
            data_weight.text = str(weight)

            label = edge_data.get("type", "")
            data_label = ET.SubElement(edge_elem, "data")
            data_label.set("key", "d4")
            data_label.text = label

        graphml_str = ET.tostring(root, encoding="unicode")

        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(graphml_str)
            logger.info(f"Graph exported to {file_path}")

        return graphml_str

    def export_dot(self, file_path: str) -> str:
        """导出为 DOT 格式（用于 GraphViz）

        Args:
            file_path: 导出文件路径

        Returns:
            DOT 字符串
        """
        nodes = self.db.execute("SELECT * FROM nodes")
        edges = self.db.execute("SELECT * FROM edges")

        lines = [
            "/* Generated by Semantic Graph Database */",
            f"/* Exported at: {datetime.now().isoformat()} */",
            "",
            "digraph graph_name {",
            "    rankdir=LR;",
            "    node [shape=box, style=filled, fillcolor=lightblue];",
            "    edge [color=gray];",
            "",
        ]

        node_ids_seen = set()
        for row in nodes:
            node_data = dict(row)
            node_id = node_data["id"]
            node_ids_seen.add(node_id)

            label = node_data.get("name", node_id)
            node_type = node_data.get("type", "")
            properties = node_data.get("properties", {})

            escaped_label = label.replace('"', '\\"').replace("\n", "\\n")
            props_str = ", ".join(f'{k}="{v}"' for k, v in properties.items()) if properties else ""

            lines.append(f'    "{node_id}" [label="{escaped_label}"')
            if node_type:
                lines.append(f'        node_type="{node_type}"')
            if props_str:
                lines.append(f'        {props_str}')
            lines.append("    ];")

        lines.append("")

        for row in edges:
            edge_data = dict(row)
            source = edge_data["source_id"]
            target = edge_data["target_id"]
            edge_type = edge_data.get("type", "")
            weight = edge_data.get("weight", 1.0)

            if source not in node_ids_seen or target not in node_ids_seen:
                continue

            escaped_type = edge_type.replace('"', '\\"') if edge_type else ""

            lines.append(f'    "{source}" -> "{target}" [')
            lines.append(f'        label="{escaped_type}",')
            lines.append(f'        weight={weight}')
            lines.append("    ];")

        lines.append("}")

        dot_str = "\n".join(lines)

        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(dot_str)
            logger.info(f"Graph exported to {file_path}")

        return dot_str

    def _node_to_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """将节点行转换为字典"""
        return {
            "id": row["id"],
            "name": row.get("name", ""),
            "type": row.get("type", ""),
            "properties": json.loads(row["properties"]) if row.get("properties") else {},
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
        }

    def _edge_to_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """将边行转换为字典"""
        return {
            "id": row["id"],
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "type": row.get("type", ""),
            "weight": row.get("weight", 1.0),
            "properties": json.loads(row["properties"]) if row.get("properties") else {},
            "created_at": row.get("created_at", ""),
        }
