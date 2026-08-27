"""server.core.graph.migration (Neo4jImporter/Neo4jExporter) 单元测试。

Neo4jExporter 用 FakeDriver 注入隔离；Neo4jImporter 用真实内存 SQLite + mock 语义。
覆盖节点/关系导入、批量分页、文本内容提取、映射清理、导出分批与统计。
运行：python -m pytest tests/test_graph_migration.py -v
"""
import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.database import Database
from server.core.graph.migration import Neo4jImporter, Neo4jExporter
from server.core.graph.nodes import NodeManager
from server.core.graph.edges import EdgeManager


class FakeNode:
    def __init__(self, nid, labels, props):
        self.id = nid
        self.labels = labels
        self.properties = props

    def labels(self):
        return self.labels

    def items(self):
        return self.properties.items()

    def __iter__(self):
        return iter(self.properties.items())


class FakeRel:
    def __init__(self, rid, rtype, start, end, props):
        self.id = rid
        self.type = rtype
        self.start = start
        self.end = end
        self.properties = props

    def items(self):
        return self.properties.items()

    def __iter__(self):
        return iter(self.properties.items())


class FakeSession:
    def __init__(self, nodes, rels):
        self.nodes = nodes
        self.rels = rels

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **kw):
        class FakeResult:
            def __init__(self, data):
                self._data = data
                self._i = 0

            def __iter__(self):
                return iter(self._data)

            def single(self):
                return self._data[0] if self._data else None

        if "RETURN n" in query:
            return FakeResult([{"n": n} for n in self.nodes])
        if "RETURN a, r, b" in query:
            return FakeResult([{"a": r.start, "r": r, "b": r.end} for r in self.rels])
        if "count(n)" in query:
            return FakeResult([{"cnt": len(self.nodes)}])
        return FakeResult([{"cnt": len(self.rels)}])


class FakeDriver:
    def __init__(self, nodes, rels):
        self._session = FakeSession(nodes, rels)
        self.closed = False

    def session(self):
        return self._session

    def close(self):
        self.closed = True


class FakeSemantic:
    def __init__(self):
        self.added = []

    def add_vector(self, node_id, text_content, node_type):
        self.added.append((node_id, text_content, node_type))


@pytest.fixture
def db():
    config = GraphConfig(database_path=":memory:")
    database = Database(config)
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def importer(db):
    return Neo4jImporter(db, FakeSemantic(), None, GraphConfig(database_path=":memory:"))


def _nodes():
    return [
        FakeNode(1, ["Concept"], {"name": "alpha", "lang": "en"}),
        FakeNode(2, ["Concept"], {"title": "beta"}),
        FakeNode(3, ["Person"], {"description": "gamma"}),
    ]


def _rels():
    return [
        FakeRel(10, "related", _nodes()[0], _nodes()[1], {"weight": 1}),
    ]


class TestNeo4jImporterNodes:
    def test_migrate_nodes_count(self, importer):
        count = importer.migrate_nodes([nd.__dict__ | {"id": nd.id, "labels": nd.labels, "properties": dict(nd.properties)} for nd in _nodes()])
        assert count == 3
        assert importer.node_manager.count() == 3

    def test_migrate_nodes_type_and_text(self, importer):
        data = [{"id": 1, "labels": ["Concept"], "properties": {"name": "alpha", "lang": "en"}}]
        importer.migrate_nodes(data)
        node = importer.node_manager.list(node_type="Concept").items[0]
        assert node.text_content == "alpha"  # name 优先作为文本
        assert node.properties["lang"] == "en"

    def test_migrate_nodes_fallback_text(self, importer):
        data = [{"id": 1, "labels": ["Concept"], "properties": {"no_text_field": 1}}]
        importer.migrate_nodes(data)
        node = importer.node_manager.list().items[0]
        assert node.text_content == '{"no_text_field": 1}'

    def test_migrate_nodes_batch_mapping(self, importer):
        maps = {nd.id: None for nd in _nodes()}
        importer._node_id_mapping.update(maps)
        importer.migrate_nodes([{"id": nd.id, "labels": nd.labels, "properties": dict(nd.properties)} for nd in _nodes()], batch_size=2)
        # 分批后映射应被填充为真实新 id
        for old_id in maps:
            assert importer._node_id_mapping[old_id] is not None

    def test_migrate_nodes_mapping_order_with_missing_id(self, importer):
        # 批内某节点无 id 时，映射仍按 index 与输入一一对应，不被无 id 节点错位
        data = [
            {"id": 100, "labels": ["Concept"], "properties": {"a": "1"}},
            {"id": None, "labels": ["Concept"], "properties": {"no": 1}},
            {"id": 200, "labels": ["Concept"], "properties": {"b": "2"}},
        ]
        importer._node_id_mapping.update({100: None, 200: None})
        importer.migrate_nodes(data)
        items = importer.node_manager.list().items
        new100 = importer._node_id_mapping[100]
        new200 = importer._node_id_mapping[200]
        assert new100 is not None and new200 is not None
        props100 = next(nd.properties for nd in items if nd.id == new100)
        props200 = next(nd.properties for nd in items if nd.id == new200)
        assert props100.get("a") == "1"
        assert props200.get("b") == "2"

    def test_migrate_nodes_adds_vector(self, importer):
        importer.migrate_nodes([{"id": 1, "labels": ["Concept"], "properties": {"name": "hello"}}])
        assert len(importer.semantic.added) == 1
        assert importer.semantic.added[0][1] == "hello"


class TestNeo4jImporterRels:
    def test_migrate_relationships_uses_mapping(self, importer):
        importer.migrate_nodes([{"id": nd.id, "labels": nd.labels, "properties": dict(nd.properties)} for nd in _nodes()])
        count = importer.migrate_relationships([{"id": 10, "start_node_id": 1, "end_node_id": 2, "type": "related", "properties": {"weight": 1}}])
        assert count == 1
        assert importer.edge_manager.count() == 1

    def test_migrate_relationships_skip_unmapped(self, importer):
        count = importer.migrate_relationships([{"id": 10, "start_node_id": 1, "end_node_id": 2, "type": "related"}])
        assert count == 0
        assert importer.edge_manager.count() == 0

    def test_clear_mapping(self, importer):
        importer._node_id_mapping["x"] = "y"
        importer.clear_mapping()
        assert importer._node_id_mapping == {}


class TestNeo4jExporter:
    def test_export_nodes_batch(self):
        exporter = Neo4jExporter()
        exporter._driver = FakeDriver(_nodes(), _rels())
        batches = list(exporter.export_nodes(batch_size=2))
        assert sum(len(b) for b in batches) == 3
        assert batches[0][0]["id"] == _nodes()[0].id

    def test_export_relationships(self):
        exporter = Neo4jExporter()
        exporter._driver = FakeDriver(_nodes(), _rels())
        batches = list(exporter.export_relationships())
        assert sum(len(b) for b in batches) == 1
        assert batches[0][0]["type"] == "related"

    def test_get_stats(self):
        exporter = Neo4jExporter()
        exporter._driver = FakeDriver(_nodes(), _rels())
        stats = exporter.get_stats()
        assert stats["nodes"] == 3
        assert stats["relationships"] == 1

    def test_close(self):
        exporter = Neo4jExporter()
        exporter._driver = FakeDriver(_nodes(), _rels())
        exporter.close()
        assert exporter._driver.closed is True

    def test_connect_import_error(self, monkeypatch):
        monkeypatch.setattr("builtins.__import__", lambda name, *a, **k: (_ for _ in ()).throw(ImportError()) if name == "neo4j" else __import__(name, *a, **k))
        exporter = Neo4jExporter()
        assert exporter.connect() is False