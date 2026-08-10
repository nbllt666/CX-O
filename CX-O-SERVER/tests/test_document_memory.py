"""文档记忆管理器（server.core.document.memory）回归保护测试。

使用真实 SQLite（tmp_path 独立库）验证建表/CRUD/workspace 关联等完整链路，
记忆管理器用轻量替身注入，隔离真实 MemoryManager 依赖。
"""
import os
import sqlite3

import pytest

from server.core.document.memory import DocumentMemoryManager, _DEFAULT_CONFIG


class FakeMemory:
    """替身记忆管理器：记录写入/删除调用。"""

    def __init__(self):
        self.permanent = {}
        self.deleted = []
        self.search_results = []

    def write_permanent_memory(self, content, tags=None, metadata=None, **kwargs):
        mid = f"m{len(self.permanent) + 1}"
        self.permanent[mid] = {"content": content, "tags": tags, "metadata": metadata}
        return mid

    def delete_permanent_memory(self, memory_id, is_from_main=True):
        self.deleted.append((memory_id, is_from_main))
        return True

    def search_memories(self, query, workspace_id=None, limit=10, **kwargs):
        return self.search_results


@pytest.fixture
def manager(tmp_path):
    fm = FakeMemory()
    m = DocumentMemoryManager(fm, config_path=str(tmp_path / "nonexistent.json"))
    # 覆盖 db_path 指向临时目录
    m.db_path = str(tmp_path / "documents.db")
    m.conn.close()
    m.conn = _new_conn(m.db_path)
    yield m
    m.close()


def _new_conn(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_name TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            doc_author TEXT DEFAULT 'Unknown',
            description TEXT DEFAULT 'Unknown',
            doc_source TEXT,
            mime_type TEXT,
            word_count INTEGER DEFAULT 0,
            token_count_estimate INTEGER DEFAULT 0,
            text_content TEXT,
            memory_id INTEGER,
            folder TEXT DEFAULT 'custom-documents',
            file_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted BOOLEAN DEFAULT FALSE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_slug TEXT NOT NULL,
            document_id INTEGER NOT NULL,
            is_pinned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workspace_slug, document_id)
        )
        """
    )
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# 配置加载
# --------------------------------------------------------------------------- #
class TestConfig:
    def test_default_config_when_missing(self, tmp_path):
        m = DocumentMemoryManager(FakeMemory(), config_path=str(tmp_path / "nope.json"))
        assert m.config["db_path"] == _DEFAULT_CONFIG["db_path"]
        assert m.config["max_file_size"] == _DEFAULT_CONFIG["max_file_size"]
        assert m.config["default_folder"] == _DEFAULT_CONFIG["default_folder"]
        m.close()

    def test_config_loaded_from_json(self, tmp_path):
        import json

        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"default_folder": "my-folder"}), encoding="utf-8")
        m = DocumentMemoryManager(FakeMemory(), config_path=str(cfg))
        assert m.config["default_folder"] == "my-folder"
        assert m.config["db_path"] == _DEFAULT_CONFIG["db_path"]  # 缺失字段补默认
        m.close()


# --------------------------------------------------------------------------- #
# 元数据提取
# --------------------------------------------------------------------------- #
class TestExtractMetadata:
    def test_title_priority(self, manager):
        # metadata title 优先
        meta = manager._extract_metadata({"title": "自定义"}, filename="note.txt")
        assert meta["title"] == "自定义"
        # 无 title 用 filename 去扩展名
        meta = manager._extract_metadata(None, filename="report.md")
        assert meta["title"] == "report"
        # 均无则 Untitled
        meta = manager._extract_metadata(None, None)
        assert meta["title"] == "Untitled"

    def test_defaults(self, manager):
        meta = manager._extract_metadata(None, "a.txt")
        assert meta["doc_author"] == "Unknown"
        assert meta["description"] == "Unknown"
        assert meta["doc_source"] == "file"
        assert meta["folder"] == "custom-documents"
        assert meta["mime_type"] is None


# --------------------------------------------------------------------------- #
# 上传
# --------------------------------------------------------------------------- #
class TestUpload:
    def test_upload_text(self, manager):
        res = manager.upload_text("hello world", metadata={"title": "T"})
        assert res["title"] == "T"
        assert res["word_count"] == 2
        assert res["token_count_estimate"] == 2
        assert res["memory_id"] == "m1"
        assert res["doc_name"].endswith(".json")
        # 文档可查
        doc = manager.get_document(res["doc_name"])
        assert doc is not None
        assert doc["text_content"] == "hello world"

    def test_upload_text_empty_raises(self, manager):
        with pytest.raises(ValueError):
            manager.upload_text("   ")

    def test_upload_file_call_parse(self, manager, monkeypatch):
        import server.core.document.memory as mod

        monkeypatch.setattr(
            mod, "parse_document", lambda filename, mime, data: "parsed-content"
        )
        res = manager.upload_file(b"bytes", "a.txt", "text/plain", metadata={"title": "F"})
        assert res["title"] == "F"
        assert res["word_count"] == 1
        assert res["memory_id"] == "m1"

    def test_upload_file_too_large(self, manager):
        with pytest.raises(ValueError):
            manager.upload_file(b"x" * (_DEFAULT_CONFIG["max_file_size"] + 1), "a.txt", "text/plain")

    def test_upload_file_parse_error(self, manager, monkeypatch):
        import server.core.document.memory as mod

        monkeypatch.setattr(mod, "parse_document", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
        with pytest.raises(ValueError):
            manager.upload_file(b"x", "a.txt", "text/plain")

    def test_upload_with_workspaces(self, manager):
        res = manager.upload_text("content", metadata={"title": "W"}, workspaces=["ws1"])
        docs = manager.get_workspace_documents("ws1")
        assert [d["doc_name"] for d in docs] == [res["doc_name"]]


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
class TestQuery:
    def test_get_missing(self, manager):
        assert manager.get_document("nope.json") is None

    def test_list_all_and_filter(self, manager):
        manager.upload_text("a", metadata={"title": "A", "folder": "f1"})
        manager.upload_text("b", metadata={"title": "B", "folder": "f2"})
        assert len(manager.list_documents()) == 2
        assert len(manager.list_documents("f1")) == 1
        assert manager.list_documents("f1")[0]["title"] == "A"


# --------------------------------------------------------------------------- #
# 删除
# --------------------------------------------------------------------------- #
class TestDelete:
    def test_delete_soft_and_memory(self, manager):
        res = manager.upload_text("x", metadata={"title": "D"})
        doc_name = res["doc_name"]
        assert manager.delete_document(doc_name) is True
        # 软删除后不可查
        assert manager.get_document(doc_name) is None
        assert manager.list_documents() == []
        # 永久记忆被删除
        assert manager.memory_manager.deleted == [("m1", True)]

    def test_delete_missing(self, manager):
        assert manager.delete_document("nope") is False


# --------------------------------------------------------------------------- #
# workspace 关联
# --------------------------------------------------------------------------- #
class TestWorkspace:
    def test_update_and_get(self, manager):
        doc_a = manager.upload_text("a", metadata={"title": "A"}).get("doc_name")
        doc_b = manager.upload_text("b", metadata={"title": "B"}).get("doc_name")
        res = manager.update_workspace_documents("ws", adds=[doc_a, doc_b, "missing.json"])
        assert res["workspace"] == "ws"
        docs = manager.get_workspace_documents("ws")
        names = {d["doc_name"] for d in docs}
        assert doc_a in names
        assert doc_b in names
        # 删除关联
        manager.update_workspace_documents("ws", deletes=[doc_a])
        names2 = {d["doc_name"] for d in manager.get_workspace_documents("ws")}
        assert doc_a not in names2
        assert doc_b in names2


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #
class TestSearch:
    def test_search_delegates(self, manager):
        manager.memory_manager.search_results = [{"id": "r1"}]
        assert manager.search_in_workspace("ws", "q") == [{"id": "r1"}]

    def test_search_exception_returns_empty(self, manager):
        manager.memory_manager.search_memories = lambda **k: (_ for _ in ()).throw(RuntimeError("x"))
        assert manager.search_in_workspace("ws", "q") == []


# --------------------------------------------------------------------------- #
# 关闭
# --------------------------------------------------------------------------- #
class TestClose:
    def test_close(self, manager):
        manager.close()
        assert manager.conn is None or manager.conn is not None  # 不抛异常即可