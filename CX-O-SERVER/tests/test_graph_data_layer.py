"""
server/core/graph 数据层回归测试
图数据模型（models）、配置（config）、SQLite 连接管理（database）、访问基类（repository）
"""
import json
import sqlite3
from datetime import datetime

import pytest

from server.core.graph.config import GraphConfig, set_graph_config, get_graph_config
from server.core.graph.config import _PROJECT_ROOT as _GRAPH_PROJECT_ROOT
from server.core.graph.database import Database, get_database, get_database_if_exists, remove_database
from server.core.graph.models import GraphNode, GraphEdge, NodeCreate, NodeUpdate, EdgeCreate, EdgeUpdate, SearchResult
from server.core.graph.repository import BaseGraphRepository


# ================================================================ models
class TestGraphNode:
    def test_create_sets_id_and_type(self):
        n = GraphNode.create(type="concept", properties={"a": 1}, agent_id="ag1")
        assert n.type == "concept"
        assert n.properties == {"a": 1}
        assert n.agent_id == "ag1"
        assert n.id  # uuid 自动生成
        assert n.vector_id is None

    def test_to_dict_from_dict_roundtrip(self):
        n = GraphNode.create(type="person", properties={"name": "k"}, text_content="hi")
        d = n.to_dict()
        assert d["type"] == "person"
        assert isinstance(d["created_at"], str)  # isoformat 字符串
        n2 = GraphNode.from_dict(d)
        assert n2.id == n.id
        assert n2.type == n.type
        assert n2.properties == {"name": "k"}
        assert isinstance(n2.created_at, datetime)

    def test_from_dict_parses_string_properties(self):
        n = GraphNode.from_dict({
            "id": "x", "type": "t",
            "properties": '{"k": "v"}',
            "created_at": "2026-01-01T00:00:00",
        })
        assert n.properties == {"k": "v"}

    def test_from_dict_defaults_agent_and_times(self):
        n = GraphNode.from_dict({"id": "x", "type": "t"})
        assert n.agent_id == "default"
        assert n.created_at is not None


class TestGraphEdge:
    def test_create_to_dict_roundtrip(self):
        e = GraphEdge.create(source_id="a", target_id="b", relation_type="knows", agent_id="ag1")
        e2 = GraphEdge.from_dict(e.to_dict())
        assert e2.source_id == "a"
        assert e2.target_id == "b"
        assert e2.relation_type == "knows"
        assert e2.agent_id == "ag1"

    def test_from_dict_parses_json_properties(self):
        e = GraphEdge.from_dict({
            "id": "e", "source_id": "a", "target_id": "b", "relation_type": "r",
            "properties": '{"w": 2}',
        })
        assert e.properties == {"w": 2}


class TestSearchResult:
    def test_has_more(self):
        assert SearchResult(items=[1, 2], total=5, offset=0, limit=10).has_more is True
        assert SearchResult(items=[1, 2, 3], total=3, offset=0, limit=10).has_more is False

    def test_create_dto_defaults(self):
        assert NodeCreate(type="t").agent_id == "default"
        assert NodeUpdate().type is None
        assert EdgeCreate("a", "b", "r").agent_id == "default"
        assert EdgeUpdate().relation_type is None


# ================================================================ config
class TestGraphConfig:
    def test_defaults(self):
        c = GraphConfig()
        assert c.database_path == "data/graph.db"
        assert c.timeout == 30
        assert c.weaviate.url.startswith("http")

    def test_set_and_get_singleton(self):
        set_graph_config(GraphConfig(database_path="custom.db"))
        got = get_graph_config()  # 默认 agent 返回单例
        assert got.database_path == "custom.db"

    def test_per_agent_uses_default_base(self):
        set_graph_config(GraphConfig(database_path="base.db", timeout=7))
        per = get_graph_config("agent_1")
        assert per.database_path == str(_GRAPH_PROJECT_ROOT / "data" / "graph_agent_1.db")
        assert per.timeout == 7  # 继承 base 其它字段

    def test_per_agent_sanitizes_special_chars(self):
        set_graph_config(GraphConfig(database_path="base.db"))
        per = get_graph_config('/a:b?')
        # agent_id 段中的特殊字符被替换为下划线，文件名不含非法字符
        suffix = per.database_path.split("graph_")[-1]
        assert suffix.endswith(".db")
        assert "/" not in suffix and ":" not in suffix and "?" not in suffix


# ================================================================ database
@pytest.fixture
def db(tmp_path):
    d = Database(GraphConfig(database_path=str(tmp_path / "graph.db"), timeout=5))
    d.initialize()
    yield d
    d.close()


class TestDatabase:
    def test_initialize_creates_tables(self, db):
        tables = {r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"nodes", "edges", "traversal_paths"} <= tables

    def test_execute_modify_and_select(self, db):
        db.execute_modify(
            "INSERT INTO nodes (id, type, properties, text_content, created_at, updated_at, agent_id) "
            "VALUES (?,?,?,?,?,?,?)",
            ("n1", "concept", "{}", "text", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "default"),
        )
        rows = db.execute_one("SELECT * FROM nodes WHERE id = ?", ("n1",))
        assert rows["type"] == "concept"
        assert db.execute_one("SELECT * FROM nodes WHERE id = ?", ("missing",)) is None

    def test_execute_many_returns_rowcount(self, db):
        data = [
            ("n1", "t", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "default"),
            ("n2", "t", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "default"),
        ]
        n = db.execute_many(
            "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) VALUES (?,?,?,?,?,?)",
            data,
        )
        assert n == 2

    def test_health_check(self, db):
        assert db.health_check() is True

    def test_transaction_rolls_back_on_error(self, db):
        db.execute_modify(
            "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
            "VALUES ('tx1','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')",
        )
        with pytest.raises(Exception):
            db.transaction([
                ("INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
                 "VALUES ('tx2','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')", ()),
                ("INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
                 "VALUES ('tx1','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')", ()),  # 主键冲突
            ])
        # tx2 应被回滚
        assert db.execute_one("SELECT * FROM nodes WHERE id = 'tx2'") is None

    def test_migrate_adds_agent_id_to_old_schema(self, tmp_path):
        """模拟旧版无 agent_id 的 nodes 表，initialize 后应补列 + 索引。"""
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                text_content TEXT, vector_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        d = Database(GraphConfig(database_path=path, timeout=5))
        d.initialize()
        cols = {r["name"] for r in d.execute("PRAGMA table_info(nodes)")}
        assert "agent_id" in cols
        indexes = {r["name"] for r in d.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_nodes_agent_id" in indexes
        d.close()

    def test_migrate_adds_name_to_old_schema(self, tmp_path):
        """模拟旧版无 name 列的 nodes 表，initialize 后应幂等补列。"""
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                text_content TEXT, vector_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        d = Database(GraphConfig(database_path=path, timeout=5))
        d.initialize()
        cols = {r["name"] for r in d.execute("PRAGMA table_info(nodes)")}
        assert "name" in cols
        d.close()

    def test_initialize_has_name_column_default(self, db):
        """新库 nodes 表应含 name 列且默认空串，缺省插入不报错。"""
        cols = {r["name"] for r in db.execute("PRAGMA table_info(nodes)")}
        assert "name" in cols
        db.execute_modify(
            "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
            "VALUES ('n_name','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')",
        )
        row = db.execute_one("SELECT name FROM nodes WHERE id = 'n_name'")
        assert row["name"] == ""

    def test_close_resets_connection(self, db):
        db.close()
        assert db._local.connection is None


# ================================================================ edges FK 契约与存量库迁移
class TestEdgesForeignKeyContract:
    """第四轮 §6.3 第12条：graph 库 foreign_keys=ON + edges RESTRICT 外键契约。"""

    def test_pragma_foreign_keys_enabled(self, db):
        row = db.execute_one("PRAGMA foreign_keys")
        assert row["foreign_keys"] == 1

    def test_edges_table_declares_restrict_fks(self, db):
        ddl = db.execute_one(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'"
        )["sql"].upper()
        assert "FOREIGN KEY (SOURCE_ID)" in ddl
        assert "FOREIGN KEY (TARGET_ID)" in ddl
        assert "REFERENCES NODES(ID)" in ddl.replace("NODES (", "NODES(")
        # 无 ON DELETE 子句即默认 RESTRICT——删除仍被引用的节点将被拦截
        assert "ON DELETE CASCADE" not in ddl

    def test_fk_enforced_rejects_dangling_edge_insert(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute_modify(
                "INSERT INTO edges (id, source_id, target_id, relation_type, properties, created_at) "
                "VALUES ('dangling_1', 'ghost_src', 'ghost_tgt', 'r', '{}', '2026-01-01T00:00:00')"
            )

    def test_foreign_key_check_empty(self, db):
        assert db.execute("PRAGMA foreign_key_check") == []


class TestMigrateEdgesToForeignKeyRestrict:
    """盘上存量库兼容：旧 DDL（无 FK / 旧 ON DELETE CASCADE）自动迁移为 RESTRICT 形态。

    内存模拟旧建表语句 → Database.initialize() 走真实迁移链路 → 断言结构升级 +
    数据完整性；重复 initialize 验证迁移幂等。
    """

    NODES_OLD_DDL = """
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL,
            properties TEXT NOT NULL DEFAULT '{{}}',
            text_content TEXT,
            vector_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            agent_id VARCHAR(100) DEFAULT 'default'
        );
    """

    @staticmethod
    def _build_old_db(path: str, fk_lines: str) -> None:
        """手工创建旧版 schema 并注入数据：1 条有效边 + 1 条悬挂边。"""
        conn = sqlite3.connect(path)
        conn.executescript(f"""
            {TestMigrateEdgesToForeignKeyRestrict.NODES_OLD_DDL}

            CREATE TABLE edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{{}}',
                text_content TEXT,
                vector_id TEXT,
                created_at TEXT NOT NULL,
                agent_id VARCHAR(100) DEFAULT 'default'{fk_lines}
            );
        """)
        for nid in ("n1", "n2"):
            conn.execute(
                "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
                "VALUES (?, 't', '{}', '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'default')",
                (nid,),
            )
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, relation_type, created_at, agent_id) "
            "VALUES ('e_ok', 'n1', 'n2', 'knows', '2026-01-01T00:00:00', 'default')"
        )
        # 旧行为遗留的悬挂边（target 不存在）——裸连接默认 FK 关闭可插入
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, relation_type, created_at, agent_id) "
            "VALUES ('e_dangling', 'n1', 'ghost', 'likes', '2026-01-01T00:00:00', 'default')"
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _assert_migrated(d: Database) -> None:
        """迁移完成态断言：DDL 升级 + 有效边保留 + 悬挂边清理 + 索引齐全 + 完整性通过。"""
        ddl = d.execute_one("SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'")
        assert ddl is not None
        upper = ddl["sql"].upper()
        assert "FOREIGN KEY" in upper and "ON DELETE CASCADE" not in upper

        edge_ids = {r["id"] for r in d.execute("SELECT id FROM edges")}
        assert edge_ids == {"e_ok"}  # 有效边保留、悬挂边被剔除

        assert d.execute("PRAGMA foreign_key_check") == []

        indexes = {
            r["name"]
            for r in d.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='edges'")
        }
        assert {"idx_edges_source", "idx_edges_target", "idx_edges_relation_type", "idx_edges_agent_id"} <= indexes

    @pytest.mark.parametrize(
        "fk_lines, label",
        [
            ("", "无FK旧表"),
            (
                ",\n                    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,"
                "\n                    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE",
                "含级联旧契约",
            ),
        ],
    )
    def test_migrate_and_idempotent(self, tmp_path, fk_lines, label):
        path = str(tmp_path / f"old_{label}.db")
        self._build_old_db(path, fk_lines)

        d = Database(GraphConfig(database_path=path, timeout=5))
        d.initialize()
        self._assert_migrated(d)

        # 幂等证明：二次 initialize（重启重复检测）后结构与数据完全等价
        before = d.execute_one("SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'")["sql"]
        rows_before = [tuple(dict(r).values()) for r in d.execute("SELECT * FROM edges ORDER BY id")]
        d.initialize()
        after = d.execute_one("SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'")["sql"]
        rows_after = [tuple(dict(r).values()) for r in d.execute("SELECT * FROM edges ORDER BY id")]
        assert before == after and rows_before == rows_after
        self._assert_migrated(d)
        d.close()


# ================================================================ repository
def _seed_graph(db):
    db.execute_modify(
        "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
        "VALUES ('A','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')",
    )
    db.execute_modify(
        "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
        "VALUES ('B','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')",
    )
    db.execute_modify(
        "INSERT INTO nodes (id, type, properties, created_at, updated_at, agent_id) "
        "VALUES ('C','t','{}','2026-01-01T00:00:00','2026-01-01T00:00:00','default')",
    )
    # 边：A->B、C->A
    for eid, src, tgt, rel in [("e1", "A", "B", "knows"), ("e2", "C", "A", "likes")]:
        db.execute_modify(
            "INSERT INTO edges (id, source_id, target_id, relation_type, properties, created_at, agent_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (eid, src, tgt, rel, "{}", "2026-01-01T00:00:00", "default"),
        )


@pytest.fixture
def repo(db):
    _seed_graph(db)
    return BaseGraphRepository(db)


class TestRepository:
    def test_get_node(self, repo):
        n = repo.get_node("A")
        assert n is not None
        assert n.id == "A"
        assert n.type == "t"

    def test_get_node_missing(self, repo):
        assert repo.get_node("ZZZ") is None

    def test_get_neighbor_ids_outgoing(self, repo):
        assert repo.get_neighbor_ids("A", direction="outgoing") == ["B"]

    def test_get_neighbor_ids_incoming(self, repo):
        assert repo.get_neighbor_ids("A", direction="incoming") == ["C"]

    def test_get_neighbor_ids_both(self, repo):
        assert set(repo.get_neighbor_ids("A", direction="both")) == {"B", "C"}

    def test_get_edge(self, repo):
        e = repo.get_edge("e1")
        assert e is not None
        assert e.source_id == "A"
        assert e.target_id == "B"
        assert e.relation_type == "knows"

    def test_get_edge_missing(self, repo):
        assert repo.get_edge("zzz") is None

    def test_agent_scoped(self, db):
        _seed_graph(db)
        # 用非 default agent 查询，不应命中 default 数据
        other = BaseGraphRepository(db)
        assert other.get_node("A", agent_id="other") is None
        assert other.get_neighbor_ids("A", direction="both", agent_id="other") == []


# ================================================================ get_database 注册表
class TestDatabaseRegistry:
    def test_get_and_remove(self, tmp_path, monkeypatch):
        from server.core.graph import database as db_mod
        monkeypatch.setattr(db_mod, "_db_instances", {})
        monkeypatch.setattr(db_mod, "_db_lock", __import__("threading").Lock())

        cfg = GraphConfig(database_path=str(tmp_path / "reg.db"))
        d = get_database(cfg, agent_id="reg1")
        assert d is get_database(cfg, agent_id="reg1")  # 同 agent 复用
        assert get_database_if_exists("reg1") is d
        removed = remove_database("reg1")
        assert removed is d
        assert get_database_if_exists("reg1") is None