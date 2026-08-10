"""
server/api/routers/agents.py 路由回归测试
Agent 配置 CRUD / 默认获取 / 克隆 / 统计 / 上下文 / per-agent 资源清理。
用 FastAPI TestClient + monkeypatch AGENTS_CONFIG_PATH 指向 tmp_path，
隔离真实 `data/agents.json` 与 agent_config_cache 全局缓存。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.api.routers.agents as agents_mod
from server.api.routers.agents import router as agents_router


# --------------------------------------------------------------------------- #
# 假依赖
# --------------------------------------------------------------------------- #
class FakeCache:
    """模拟 LRUCache 的最小替身（get/set/delete/clear）。"""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value

    def delete(self, key):
        return self.data.pop(key, None) is not None

    def clear(self):
        self.data.clear()


class FakeContextManager:
    def __init__(self, sessions=None):
        self.sessions = sessions or []

    def list_sessions(self):
        return self.sessions


class FakeAgentContextManager:
    def __init__(self, summary=None, messages=None):
        self.summary = summary or {"has_context": False}
        self.messages = messages or []
        self.cleared = []

    def get_context_summary(self, agent_id):
        return self.summary

    def get_message_history(self, agent_id, limit=20):
        return self.messages[:limit]

    def clear_context(self, agent_id):
        self.cleared.append(agent_id)


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg_path = tmp_path / "agents.json"
    monkeypatch.setattr(agents_mod, "AGENTS_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(agents_mod, "agent_config_cache", FakeCache())
    # 隔离 per-agent 资源清理，避免真实 DB / Weaviate 副作用
    monkeypatch.setattr(agents_mod, "_cleanup_agent_resources", lambda agent_id: None)

    app = FastAPI()
    app.include_router(agents_router)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def _seed(client, agents):
    """直接落盘 agents 到 AGENTS_CONFIG_PATH。"""
    with open(agents_mod.AGENTS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(agents, f, ensure_ascii=False, indent=2)
    agents_mod.agent_config_cache.clear()


def _default_agents():
    return [
        {
            "id": "default", "name": "默认助手", "model": "main",
            "system_prompt": "p", "temperature": 0.7, "max_tokens": 0,
            "use_memory": True, "use_tools": True, "memory_scene": "chat",
            "decay_model": "exponential", "is_default": True,
            "created_at": "2026-08-09T00:00:00", "updated_at": "2026-08-09T00:00:00",
        },
        {
            "id": "memory-agent", "name": "记忆管理助手", "model": "memory",
            "system_prompt": "p", "temperature": 0.3, "max_tokens": 0,
            "use_memory": False, "use_tools": True, "memory_scene": "task",
            "decay_model": "exponential", "is_default": False,
            "created_at": "2026-08-09T00:00:00", "updated_at": "2026-08-09T00:00:00",
        },
    ]


def _load_file():
    with open(agents_mod.AGENTS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# _load_agents / _save_agents / _generate_agent_id
# --------------------------------------------------------------------------- #
class TestPrivateHelpers:
    def test_load_agents_uses_cache(self, client, monkeypatch):
        _seed(client, _default_agents())
        agents_mod.agent_config_cache.set("all_agents", [{"id": "cached"}])
        assert agents_mod._load_agents() == [{"id": "cached"}]

    def test_load_agents_missing_file_creates_defaults(self, client):
        agents = agents_mod._load_agents()
        ids = {a["id"] for a in agents}
        assert {"default", "memory-agent"} <= ids
        # 落盘且缓存
        assert _load_file()[0]["id"] == "default"
        assert agents_mod.agent_config_cache.get("all_agents") is not None

    def test_load_agents_corrupt_returns_empty(self, client):
        with open(agents_mod.AGENTS_CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write("{ invalid json")
        assert agents_mod._load_agents() == []

    def test_save_agents_roundtrip_and_cache_delete(self, client):
        _seed(client, [])
        agents_mod._save_agents(_default_agents())
        assert len(_load_file()) == 2
        assert agents_mod.agent_config_cache.get("all_agents") is None

    def test_generate_agent_id_format(self):
        aid = agents_mod._generate_agent_id()
        assert aid.startswith("agent-")
        assert len(aid) == len("agent-") + 8

    def test_ensure_data_dir_creates_parent(self, tmp_path, monkeypatch):
        target = tmp_path / "nested" / "dir"
        monkeypatch.setattr(agents_mod, "AGENTS_CONFIG_PATH", str(target / "agents.json"))
        agents_mod._ensure_data_dir()
        assert (tmp_path / "nested" / "dir").is_dir()


# --------------------------------------------------------------------------- #
# GET /agents
# --------------------------------------------------------------------------- #
class TestGetAgents:
    def test_success(self, client):
        _seed(client, _default_agents())
        r = client.get("/agents")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["total"] == 2
        assert {a["id"] for a in body["agents"]} == {"default", "memory-agent"}

    def test_load_error_500(self, client, monkeypatch):
        def boom():
            raise RuntimeError("boom")

        monkeypatch.setattr(agents_mod, "_load_agents", boom)
        r = client.get("/agents")
        assert r.status_code == 500
        assert r.json()["detail"] == "内部服务器错误"


# --------------------------------------------------------------------------- #
# POST /agents
# --------------------------------------------------------------------------- #
class TestCreateAgent:
    def test_success(self, client):
        _seed(client, [])
        r = client.post("/agents", json={
            "name": "新助手", "description": "d", "model": "main",
            "temperature": 0.5, "max_tokens": 100,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        agent = body["agent"]
        assert agent["name"] == "新助手"
        assert agent["model"] == "main"
        assert agent["is_default"] is False
        assert agent["id"].startswith("agent-")

    def test_empty_model_defaults_to_main(self, client):
        _seed(client, [])
        r = client.post("/agents", json={"name": "空模型", "model": "  "})
        assert r.status_code == 200
        assert r.json()["agent"]["model"] == "main"

    def test_duplicate_name_400(self, client):
        _seed(client, _default_agents())
        r = client.post("/agents", json={"name": "默认助手"})
        assert r.status_code == 400
        assert "已存在" in r.json()["detail"]

    def test_save_error_500(self, client, monkeypatch):
        _seed(client, [])
        def boom(agents):
            raise RuntimeError("disk full")

        monkeypatch.setattr(agents_mod, "_save_agents", boom)
        r = client.post("/agents", json={"name": "x"})
        assert r.status_code == 500
        assert r.json()["detail"] == "内部服务器错误"


# --------------------------------------------------------------------------- #
# GET /agents/default
# --------------------------------------------------------------------------- #
class TestGetDefaultAgent:
    def test_prefers_is_default(self, client):
        _seed(client, [
            {"id": "memory-agent", "name": "m", "is_default": False},
            {"id": "default", "name": "d", "is_default": True},
        ])
        r = client.get("/agents/default")
        assert r.status_code == 200
        assert r.json()["agent"]["id"] == "default"

    def test_fallback_to_id_default(self, client):
        _seed(client, [{"id": "default", "name": "d", "is_default": False}])
        r = client.get("/agents/default")
        assert r.status_code == 200
        assert r.json()["agent"]["id"] == "default"

    def test_no_default_404(self, client):
        _seed(client, [{"id": "other", "name": "o", "is_default": False}])
        r = client.get("/agents/default")
        assert r.status_code == 404
        assert "未配置默认 Agent" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# GET /agents/{agent_id}
# --------------------------------------------------------------------------- #
class TestGetAgent:
    def test_success(self, client):
        _seed(client, _default_agents())
        r = client.get("/agents/default")
        assert r.status_code == 200
        assert r.json()["agent"]["id"] == "default"

    def test_not_found_404(self, client):
        _seed(client, _default_agents())
        r = client.get("/agents/nope")
        assert r.status_code == 404
        assert "不存在" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# PUT /agents/{agent_id}
# --------------------------------------------------------------------------- #
class TestUpdateAgent:
    def test_success(self, client):
        _seed(client, _default_agents())
        r = client.put("/agents/default", json={"name": "改名", "temperature": 0.9})
        assert r.status_code == 200
        agent = r.json()["agent"]
        assert agent["name"] == "改名"
        assert agent["temperature"] == 0.9
        # 未传字段保留
        assert agent["model"] == "main"

    def test_empty_model_defaults_to_main(self, client):
        _seed(client, _default_agents())
        r = client.put("/agents/default", json={"model": "   "})
        assert r.status_code == 200
        assert r.json()["agent"]["model"] == "main"

    def test_not_found_404(self, client):
        _seed(client, _default_agents())
        r = client.put("/agents/nope", json={"name": "x"})
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# DELETE /agents/{agent_id} + 资源清理
# --------------------------------------------------------------------------- #
class TestDeleteAgent:
    def test_success(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(agents_mod, "_cleanup_agent_resources",
                            lambda agent_id: calls.append(agent_id))
        _seed(client, _default_agents())
        r = client.delete("/agents/memory-agent")
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert calls == ["memory-agent"]
        # 已从列表移除
        assert [a["id"] for a in _load_file()] == ["default"]

    def test_not_found_404(self, client, monkeypatch):
        monkeypatch.setattr(agents_mod, "_cleanup_agent_resources",
                            lambda agent_id: None)
        _seed(client, _default_agents())
        r = client.delete("/agents/nope")
        assert r.status_code == 404

    def test_cannot_delete_default_400(self, client, monkeypatch):
        monkeypatch.setattr(agents_mod, "_cleanup_agent_resources",
                            lambda agent_id: None)
        _seed(client, _default_agents())
        r = client.delete("/agents/default")
        assert r.status_code == 400
        assert "不能删除默认 Agent" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# POST /agents/{agent_id}/clone
# --------------------------------------------------------------------------- #
class TestCloneAgent:
    def test_success(self, client):
        _seed(client, _default_agents())
        r = client.post("/agents/default/clone")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        agent = body["agent"]
        assert agent["name"] == "默认助手 (副本)"
        assert agent["is_default"] is False
        assert agent["id"] != "default"
        assert len(_load_file()) == 3

    def test_not_found_404(self, client):
        _seed(client, _default_agents())
        r = client.post("/agents/nope/clone")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# GET /agents/{agent_id}/stats
# --------------------------------------------------------------------------- #
class TestGetAgentStats:
    def test_success(self, client, monkeypatch):
        _seed(client, _default_agents())
        sessions = [
            {"agent_id": "default", "message_count": 5},
            {"agent_id": "default", "message_count": 3},
            {"agent_id": "memory-agent", "message_count": 2},
        ]
        monkeypatch.setattr(
            "server.dependencies.get_context_manager",
            lambda: FakeContextManager(sessions),
        )
        r = client.get("/agents/default/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["session_count"] == 2
        assert body["total_messages"] == 8

    def test_not_found_404(self, client):
        _seed(client, _default_agents())
        r = client.get("/agents/nope/stats")
        assert r.status_code == 404

    def test_error_returns_zeros(self, client, monkeypatch):
        _seed(client, _default_agents())
        def boom():
            raise RuntimeError("down")

        monkeypatch.setattr("server.dependencies.get_context_manager", boom)
        r = client.get("/agents/default/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["session_count"] == 0
        assert "error" in body


# --------------------------------------------------------------------------- #
# GET/DELETE /agents/{agent_id}/context
# --------------------------------------------------------------------------- #
class TestAgentContext:
    def test_get_success(self, client, monkeypatch):
        _seed(client, _default_agents())
        monkeypatch.setattr(
            "server.core.context.agent_context_manager.get_agent_context_manager",
            lambda: FakeAgentContextManager(
                summary={"has_context": True, "session_id": "s1", "total_messages": 3,
                         "role_counts": {"user": 2, "assistant": 1}},
                messages=[{"role": "user", "content": "hi"}],
            ),
        )
        r = client.get("/agents/default/context")
        assert r.status_code == 200
        body = r.json()
        assert body["has_context"] is True
        assert body["total_messages"] == 3
        assert len(body["recent_messages"]) == 1

    def test_get_not_found_404(self, client):
        _seed(client, _default_agents())
        r = client.get("/agents/nope/context")
        assert r.status_code == 404

    def test_delete_success(self, client, monkeypatch):
        _seed(client, _default_agents())
        fake = FakeAgentContextManager()
        monkeypatch.setattr(
            "server.core.context.agent_context_manager.get_agent_context_manager",
            lambda: fake,
        )
        r = client.delete("/agents/default/context")
        assert r.status_code == 200
        assert fake.cleared == ["default"]

    def test_delete_not_found_404(self, client):
        _seed(client, _default_agents())
        r = client.delete("/agents/nope/context")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# per-agent 资源清理函数
# --------------------------------------------------------------------------- #
class TestResourceCleanup:
    def test_cleanup_graph_db(self, tmp_path, monkeypatch):
        db_file = tmp_path / "agent_default.db"
        db_file.write_bytes(b"\x00")
        removed = []

        class FakeConfig:
            def __init__(self, path):
                self.database_path = path

        monkeypatch.setattr(
            "server.dependencies.remove_graph_database",
            lambda agent_id: removed.append(("remove", agent_id)),
        )
        monkeypatch.setattr(
            "server.core.graph.config.get_graph_config",
            lambda agent_id=...: FakeConfig(str(db_file)),
        )
        agents_mod._cleanup_agent_graph_db("default")
        assert ("remove", "default") in removed
        assert not db_file.exists()

    def test_cleanup_graph_db_deps_error_no_raise(self, tmp_path, monkeypatch):
        db_file = tmp_path / "agent_default.db"
        db_file.write_bytes(b"\x00")
        def boom(agent_id):
            raise RuntimeError("down")

        monkeypatch.setattr("server.dependencies.remove_graph_database", boom)
        monkeypatch.setattr(
            "server.core.graph.config.get_graph_config",
            lambda agent_id=...: type("C", (), {"database_path": str(db_file)})(),
        )
        # 注册表移除失败不抛异常，文件仍被删除
        agents_mod._cleanup_agent_graph_db("default")
        assert not db_file.exists()

    def test_cleanup_weaviate_collection(self, monkeypatch):
        deleted = []

        class FakeState:
            memory_manager = type(
                "MM", (), {
                    "_vector_store": type(
                        "VS", (), {"delete_agent_collection": lambda self, aid: deleted.append(aid)}
                    )()
                }
            )()

        monkeypatch.setattr("server.dependencies._resolve_state", lambda: FakeState())
        agents_mod._cleanup_agent_weaviate_collection("mem-agent")
        assert deleted == ["mem-agent"]

    def test_cleanup_weaviate_no_memory_manager(self, monkeypatch):
        class FakeState:
            memory_manager = None

        monkeypatch.setattr("server.dependencies._resolve_state", lambda: FakeState())
        # 不抛
        agents_mod._cleanup_agent_weaviate_collection("x")

    def test_cleanup_weaviate_no_vector_store(self, monkeypatch):
        class FakeState:
            memory_manager = type("MM", (), {"_vector_store": None})()

        monkeypatch.setattr("server.dependencies._resolve_state", lambda: FakeState())
        agents_mod._cleanup_agent_weaviate_collection("x")

    def test_cleanup_memory_tables(self, monkeypatch):
        class FakeMM:
            def __init__(self):
                self.drop_calls = []
                self.conn = FakeConn(self)

            def _get_table_name(self, agent_id):
                return f"memories_{agent_id}" if agent_id != "default" else "memories"

            def _get_connection(self):
                return self.conn

        class FakeConn:
            def __init__(self, mm):
                self.mm = mm
                self.closed = False

            def cursor(self):
                return FakeCursor(self.mm)

            def close(self):
                self.closed = True

        class FakeCursor:
            def __init__(self, mm):
                self.mm = mm
                self.rowcount = 0

            def execute(self, sql, params=()):
                pass

            def fetchone(self):
                # 表存在 → 触发 DROP
                return ("memories_mem-agent",)

        fake = FakeMM()
        class FakeState:
            memory_manager = fake

        monkeypatch.setattr("server.dependencies._resolve_state", lambda: FakeState())
        agents_mod._cleanup_agent_memory_tables("mem-agent")
        assert fake.conn.closed is True

    def test_cleanup_memory_tables_default_skips(self, monkeypatch):
        class FakeMM:
            def _get_table_name(self, agent_id):
                return "memories"

        class FakeState:
            memory_manager = FakeMM()

        monkeypatch.setattr("server.dependencies._resolve_state", lambda: FakeState())
        # 不抛
        agents_mod._cleanup_agent_memory_tables("default")

    def test_cleanup_resources_dispatches_all(self, monkeypatch):
        calls = []
        monkeypatch.setattr(agents_mod, "_cleanup_agent_graph_db",
                            lambda aid: calls.append(("graph", aid)))
        monkeypatch.setattr(agents_mod, "_cleanup_agent_weaviate_collection",
                            lambda aid: calls.append(("weav", aid)))
        monkeypatch.setattr(agents_mod, "_cleanup_agent_memory_tables",
                            lambda aid: calls.append(("mem", aid)))
        agents_mod._cleanup_agent_resources("a1")
        assert calls == [("graph", "a1"), ("weav", "a1"), ("mem", "a1")]