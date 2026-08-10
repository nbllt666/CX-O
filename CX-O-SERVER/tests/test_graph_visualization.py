"""server.core.graph.visualization (GraphExporter) 单元测试。

用假 db.execute 返回节点/边行 dict，隔离 SQLite，覆盖 JSON / GraphML / DOT
三种导出格式的结构正确性与文件落盘。

运行：python -m pytest tests/test_graph_visualization.py -v
"""
import json
import xml.etree.ElementTree as ET

from server.core.graph.visualization import GraphExporter

NODES = [
    {
        "id": "n1", "name": "Alice", "type": "person",
        "properties": '{"age": 30}', "created_at": "t", "updated_at": "t",
    },
    {
        "id": "n2", "name": "Python", "type": "concept",
        "properties": "{}", "created_at": "t", "updated_at": "t",
    },
]

EDGES = [
    {
        "id": "e1", "source_id": "n1", "target_id": "n2",
        "relation_type": "loves", "properties": "{}",
        "weight": 0.9, "created_at": "t",
    },
]


class FakeDB:
    """最小假 DB：execute 返回可被 dict() 转换的行列表。"""

    def __init__(self, nodes, edges):
        self._nodes = nodes
        self._edges = edges

    def execute(self, sql):
        if "FROM nodes" in sql:
            return self._nodes
        return self._edges


def _exporter(nodes=NODES, edges=EDGES):
    return GraphExporter(FakeDB(nodes, edges))


class TestExportJson:
    def test_json_structure(self):
        out = _exporter().export_json()
        data = json.loads(out)
        assert data["metadata"]["node_count"] == 2
        assert data["metadata"]["edge_count"] == 1
        assert data["nodes"][0]["id"] == "n1"
        assert data["nodes"][0]["properties"] == {"age": 30}
        assert data["edges"][0]["weight"] == 0.9
        assert data["edges"][0]["type"] == "loves"

    def test_json_writes_file(self, tmp_path):
        p = tmp_path / "g.json"
        out = _exporter().export_json(str(p))
        assert p.exists()
        assert json.loads(p.read_text(encoding="utf-8"))["metadata"]["node_count"] == 2
        assert out  # 返回值同内容

    def test_json_empty(self):
        data = json.loads(_exporter(nodes=[], edges=[]).export_json())
        assert data["nodes"] == []
        assert data["edges"] == []


class TestExportGraphML:
    def test_graphml_structure(self):
        out = _exporter().export_graphml(None)
        root = ET.fromstring(out)
        # root 带命名空间，用局部名断言
        assert root.tag.split("}")[-1] == "graphml"
        # 命名空间内元素，用 iter + 局部名过滤（更稳健）
        nodes = [e for e in root.iter() if e.tag.split("}")[-1] == "node"]
        edges = [e for e in root.iter() if e.tag.split("}")[-1] == "edge"]
        assert len(nodes) == 2
        assert len(edges) == 1
        # 节点属性 data 键
        node1 = nodes[0]
        texts = {d.attrib["key"]: d.text for d in node1 if d.tag.split("}")[-1] == "data"}
        assert texts["d0"] == "Alice"
        assert texts["d1"] == "person"
        # 边
        edge = edges[0]
        assert edge.attrib["source"] == "n1"
        assert edge.attrib["target"] == "n2"

    def test_graphml_writes_file(self, tmp_path):
        p = tmp_path / "g.graphml"
        out = _exporter().export_graphml(str(p))
        assert p.exists()
        assert "graphml" in p.read_text(encoding="utf-8")


class TestExportDot:
    def test_dot_structure(self):
        out = _exporter().export_dot(None)
        assert 'digraph graph_name {' in out
        assert '"n1" -> "n2"' in out
        assert 'label="loves"' in out
        assert 'weight=0.9' in out
        assert 'label="Alice"' in out

    def test_dot_skips_edges_to_missing_nodes(self):
        # 边引用不存在节点 → 跳过
        edges = [dict(EDGES[0], source_id="missing")]
        out = _exporter(edges=edges).export_dot(None)
        assert '"missing" -> "n2"' not in out

    def test_dot_escapes_quotes(self):
        nodes = [dict(NODES[0], name='say "hi"')]
        out = _exporter(nodes=nodes).export_dot(None)
        assert 'label="say \\"hi\\""' in out

    def test_dot_writes_file(self, tmp_path):
        p = tmp_path / "g.dot"
        out = _exporter().export_dot(str(p))
        assert p.exists()
        assert "digraph" in p.read_text(encoding="utf-8")
