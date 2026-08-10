"""server.api.routers.anythingllm 路由测试。

用 FastAPI TestClient + monkeypatch 隔离外部依赖（agents 存储、LLM、document
manager）。覆盖：
- 认证：开放模式放行 / 设置 key 后 Bearer 校验（缺失/前缀/不匹配→403）
- OpenAI 模型列表、chat completions（非流式）
- Workspace 管理：list/create/get/update/delete（含重复、默认保护、404）
- 模型解析：agent:<id> 与默认 agent
- Phase 2 文档端点：upload/raw-text/documents/get/delete/update-embeddings/metadata-schema

运行：python -m pytest tests/test_anythingllm_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import anythingllm as anythingllm_mod
from server.dependencies import get_document_memory_manager


@pytest.fixture
def base_agents() -> List[Dict[str, Any]]:
    return [
        {
            "id": "default",
            "name": "默认助手",
            "description": "",
            "system_prompt": "you are helpful",
            "model": "main",
            "temperature": 0.7,
            "max_tokens": 4096,
            "use_memory": False,
            "use_tools": False,
            "vision_enabled": False,
            "is_default": True,
            "created_at": "2026-08-09T00:00:00",
        },
        {
            "id": "alice",
            "name": "Alice",
            "description": "",
            "system_prompt": "be alice",
            "model": "qwen",
            "temperature": 0.5,
            "max_tokens": 2048,
            "use_memory": False,
            "use_tools": False,
            "vision_enabled": False,
            "is_default": False,
            "created_at": "2026-08-09T00:00:00",
        },
    ]


class FakeLLM:
    def __init__(self, content="你好世界"):
        self.content = content

    async def chat(self, messages, stream=False, **kwargs):
        class Resp:
            pass
        r = Resp()
        r.content = self.content
        r.finish_reason = "stop"
        r.usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
        return r


class FakeDMM:
    def __init__(self):
        self.docs = {}
        self.upload_calls = []
        self.embeddings_calls = []

    def upload_file(self, file_bytes, filename, mime, metadata=None, workspaces=None):
        self.upload_calls.append(("file", filename))
        doc = {"doc_name": f"{filename}-u1", "title": filename, "word_count": 1}
        self.docs[doc["doc_name"]] = doc
        return doc

    def upload_text(self, text_content, metadata=None, workspaces=None):
        self.upload_calls.append(("text", text_content))
        doc = {"doc_name": "text-u1", "title": "text", "word_count": len(text_content)}
        self.docs[doc["doc_name"]] = doc
        return doc

    def list_documents(self):
        return list(self.docs.values())

    def get_document(self, doc_name):
        return self.docs.get(doc_name)

    def delete_document(self, doc_name):
        if doc_name in self.docs:
            del self.docs[doc_name]
            return True
        return False

    def update_workspace_documents(self, slug, adds, deletes):
        self.embeddings_calls.append((slug, adds, deletes))
        return {"documents": adds}


@pytest.fixture
def dmm() -> FakeDMM:
    return FakeDMM()


@pytest.fixture
def agents_state(base_agents) -> Dict[str, Any]:
    return {"list": list(base_agents)}


@pytest.fixture
def client(monkeypatch, base_agents, dmm, agents_state):
    monkeypatch.setattr(anythingllm_mod, "ANYTHINGLLM_API_KEY", "")
    monkeypatch.setattr(anythingllm_mod, "_load_agents", lambda: agents_state["list"])
    monkeypatch.setattr(anythingllm_mod, "_save_agents", lambda lst: agents_state.__setitem__("list", lst))
    monkeypatch.setattr(anythingllm_mod, "_get_model_list", lambda: [{"id": "main", "object": "model"}])
    monkeypatch.setattr(
        anythingllm_mod, "get_llm_client_for_agent", lambda agent: FakeLLM()
    )

    app = FastAPI()
    app.include_router(anythingllm_mod.router)
    app.dependency_overrides[get_document_memory_manager] = lambda: dmm
    return TestClient(app), agents_state, dmm


# --------------------------------------------------------------------------- #
# 认证
# --------------------------------------------------------------------------- #
class TestAuth:
    def test_open_mode(self, client):
        c, _, _ = client
        r = c.get("/v1/auth")
        assert r.status_code == 200
        assert r.json()["authenticated"] is True

    def test_auth_endpoint_requires_key(self, client, monkeypatch):
        c, _, _ = client
        monkeypatch.setattr(anythingllm_mod, "ANYTHINGLLM_API_KEY", "secret123")
        # 无 header
        assert c.get("/v1/auth").status_code == 403
        # 前缀错误
        assert c.get("/v1/auth", headers={"Authorization": "Token secret123"}).status_code == 403
        # token 不匹配
        assert c.get("/v1/auth", headers={"Authorization": "Bearer wrong"}).status_code == 403
        # 匹配
        r = c.get("/v1/auth", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200
        assert r.json()["authenticated"] is True


# --------------------------------------------------------------------------- #
# 模型列表
# --------------------------------------------------------------------------- #
class TestListModels:
    def test_success(self, client):
        c, _, _ = client
        r = c.get("/v1/openai/models")
        assert r.status_code == 200
        body = r.json()
        assert body["object"] == "list"
        assert body["data"] == [{"id": "main", "object": "model"}]


# --------------------------------------------------------------------------- #
# OpenAI chat completions（非流式）
# --------------------------------------------------------------------------- #
class TestChatCompletions:
    def test_success(self, client):
        c, _, _ = client
        r = c.post("/v1/openai/chat/completions", json={
            "model": "main",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["content"] == "你好世界"
        assert body["model"] == "main"

    def test_agent_model_field(self, client):
        c, _, _ = client
        r = c.post("/v1/openai/chat/completions", json={
            "model": "agent:alice",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert r.status_code == 200
        assert r.json()["model"] == "qwen"

    def test_agent_not_found_404(self, client):
        c, _, _ = client
        r = c.post("/v1/openai/chat/completions", json={
            "model": "agent:nonexistent",
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert r.status_code == 404

    def test_temperature_and_max_tokens_passed(self, client, monkeypatch):
        c, _, _ = client
        captured = {}

        def fake_llm(agent):
            class Resp:
                pass
            async def chat(messages, stream=False, **kwargs):
                captured.update(kwargs)
                r = Resp()
                r.content = "x"
                r.finish_reason = "stop"
                r.usage = {}
                return r
            llm = FakeLLM()
            llm.chat = chat
            return llm

        monkeypatch.setattr(anythingllm_mod, "get_llm_client_for_agent", fake_llm)
        r = c.post("/v1/openai/chat/completions", json={
            "model": "main",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.3,
            "max_tokens": 100,
        })
        assert r.status_code == 200
        assert captured.get("temperature") == 0.3
        assert captured.get("max_tokens") == 100


# --------------------------------------------------------------------------- #
# Workspace 管理
# --------------------------------------------------------------------------- #
class TestListWorkspaces:
    def test_success(self, client, base_agents):
        c, _, _ = client
        r = c.get("/v1/workspaces")
        assert r.status_code == 200
        ws = r.json()["workspaces"]
        assert len(ws) == 2
        slugs = {w["slug"] for w in ws}
        assert slugs == {"default", "alice"}


class TestCreateWorkspace:
    def test_success(self, client):
        c, agents_state, _ = client
        r = c.post("/v1/workspace/new", json={"name": "My New Workspace"})
        assert r.status_code == 200
        ws = r.json()["workspace"]
        assert ws["slug"] == "my-new-workspace"
        # 已落盘
        assert any(a["id"] == "my-new-workspace" for a in agents_state["list"])

    def test_duplicate_name_400(self, client):
        c, _, _ = client
        r = c.post("/v1/workspace/new", json={"name": "Alice"})
        assert r.status_code == 400
        assert "已存在" in r.json()["detail"]

    def test_duplicate_slug_400(self, client):
        c, _, _ = client
        # 名称不同但 slug 相同（alice → alice）
        r = c.post("/v1/workspace/new", json={"name": "alice"})
        assert r.status_code == 400

    def test_empty_slug_fallback(self, client):
        c, _, _ = client
        r = c.post("/v1/workspace/new", json={"name": "!!!@@@"})
        assert r.status_code == 200
        assert r.json()["workspace"]["slug"].startswith("workspace-")


class TestGetWorkspace:
    def test_success(self, client):
        c, _, _ = client
        r = c.get("/v1/workspace/alice")
        assert r.status_code == 200
        ws = r.json()["workspace"]
        assert ws["slug"] == "alice"
        assert ws["settings"]["model"] == "qwen"

    def test_not_found_404(self, client):
        c, _, _ = client
        r = c.get("/v1/workspace/nope")
        assert r.status_code == 404


class TestUpdateWorkspace:
    def test_update_settings(self, client, agents_state):
        c, _, _ = client
        r = c.post("/v1/workspace/alice/update", json={
            "name": "Alice2",
            "settings": {"model": "gpt4", "temperature": 0.9, "system_prompt": "new"},
        })
        assert r.status_code == 200
        ws = r.json()["workspace"]
        assert ws["name"] == "Alice2"
        assert ws["settings"]["model"] == "gpt4"
        assert ws["settings"]["temperature"] == 0.9
        assert ws["settings"]["system_prompt"] == "new"

    def test_not_found_404(self, client):
        c, _, _ = client
        r = c.post("/v1/workspace/nope/update", json={"name": "x"})
        assert r.status_code == 404


class TestDeleteWorkspace:
    def test_success(self, client, agents_state):
        c, _, _ = client
        r = c.delete("/v1/workspace/alice")
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert not any(a["id"] == "alice" for a in agents_state["list"])

    def test_not_found_404(self, client):
        c, _, _ = client
        r = c.delete("/v1/workspace/nope")
        assert r.status_code == 404

    def test_delete_default_400(self, client):
        c, _, _ = client
        r = c.delete("/v1/workspace/default")
        assert r.status_code == 400
        assert "默认" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Document 端点
# --------------------------------------------------------------------------- #
class TestDocumentEndpoints:
    def test_upload_raw_text_success(self, client, dmm):
        c, _, _ = client
        r = c.post("/v1/document/raw-text", json={"textContent": "hello world"})
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert dmm.upload_calls[0][0] == "text"

    def test_upload_file_success(self, client, dmm):
        c, _, _ = client
        r = c.post(
            "/v1/document/upload",
            files={"file": ("a.txt", b"abc", "text/plain")},
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert dmm.upload_calls[0][0] == "file"

    def test_list_documents(self, client, dmm):
        c, _, _ = client
        dmm.docs["doc1"] = {"doc_name": "doc1", "title": "t1", "word_count": 2}
        r = c.get("/v1/documents")
        assert r.status_code == 200
        items = r.json()["localFiles"]["items"]
        assert any(i["doc_name"] == "doc1" for i in items)

    def test_get_document_success(self, client, dmm):
        c, _, _ = client
        dmm.docs["doc1"] = {"doc_name": "doc1", "title": "t1", "text_content": "x"}
        r = c.get("/v1/document/doc1")
        assert r.status_code == 200
        assert r.json()["doc_name"] == "doc1"

    def test_get_document_not_found_404(self, client):
        c, _, _ = client
        r = c.get("/v1/document/missing")
        assert r.status_code == 404

    def test_delete_document_success(self, client, dmm):
        c, _, _ = client
        dmm.docs["doc1"] = {"doc_name": "doc1"}
        r = c.delete("/v1/document/doc1")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_delete_document_not_found_404(self, client):
        c, _, _ = client
        r = c.delete("/v1/document/missing")
        assert r.status_code == 404

    def test_metadata_schema(self, client):
        c, _, _ = client
        r = c.get("/v1/document/metadata-schema")
        assert r.status_code == 200
        assert "title" in r.json()["schema"]

    def test_update_embeddings(self, client, dmm):
        c, _, _ = client
        r = c.post("/v1/workspace/alice/update-embeddings", json={
            "adds": ["a1"], "deletes": ["d1"]})
        assert r.status_code == 200
        assert r.json()["added"] == ["a1"]
        assert r.json()["removed"] == ["d1"]
        assert dmm.embeddings_calls[0][0] == "alice"