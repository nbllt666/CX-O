"""presets 路由测试（Task 3 / SubTask 3.3）。

用 tmp_path 重定向预设根目录、monkeypatch ADMIN_API_KEY 隔离真实环境。覆盖：
- 鉴权：无 key / 错误 key → 403，正确 key 可达
- GET 两类预设全量列表（空态 / 有数据态）
- POST 情感/动作预设新增与覆盖，字段校验 400，pydantic 类型错误 422
- DELETE 存在 → 200，不存在 → 404
- agent_id 路径穿越 → 400

运行：python -m pytest tests/test_presets_router.py -x -q
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import presets as presets_router_mod
from server.services import preset_service as ps

HEADERS = {"x-api-key": "test-key"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    """隔离环境：预设根目录重定向 + 管理密钥注入 + 独立 FastAPI 应用。"""
    root = tmp_path / "presets"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ps, "_PRESETS_ROOT", root)
    monkeypatch.setattr(ps, "_CACHE", {})
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    app = FastAPI()
    app.include_router(presets_router_mod.router, prefix="/api")
    return TestClient(app), root


class TestAuth:
    def test_missing_key_403(self, client):
        c, _ = client
        r = c.get("/api/presets/agentA")
        assert r.status_code == 403

    def test_wrong_key_403(self, client):
        c, _ = client
        r = c.get("/api/presets/agentA", headers={"x-api-key": "wrong"})
        assert r.status_code == 403

    def test_correct_key_ok(self, client):
        c, _ = client
        r = c.get("/api/presets/agentA", headers=HEADERS)
        assert r.status_code == 200


class TestList:
    def test_empty(self, client):
        c, _ = client
        r = c.get("/api/presets/agentA", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert body["emotion"] == [] and body["action"] == []
        assert body["emotion_count"] == 0 and body["action_count"] == 0

    def test_after_upsert(self, client):
        c, _ = client
        c.post("/api/presets/agentA/emotion", headers=HEADERS,
               json={"name": "元气", "text": "元气满满"})
        c.post("/api/presets/agentA/action", headers=HEADERS,
               json={"name": "打招呼", "tags": ["[emotion:happy]"]})
        body = c.get("/api/presets/agentA", headers=HEADERS).json()
        assert body["emotion_count"] == 1
        assert body["action_count"] == 1
        assert body["emotion"][0]["name"] == "元气"
        assert body["action"][0]["tags"] == ["[emotion:happy]"]


class TestUpsert:
    def test_emotion_success(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/emotion", headers=HEADERS,
                   json={"name": "温柔", "text": "温柔低语", "speed": 0.9, "volume": 0.8,
                         "description": "轻声细语"})
        assert r.status_code == 200
        preset = r.json()["preset"]
        assert preset["speed"] == 0.9 and preset["volume"] == 0.8
        # 同名覆盖（POST 第二次仍 200，且不产生重复）
        r2 = c.post("/api/presets/agentA/emotion", headers=HEADERS,
                    json={"name": "温柔", "text": "更温柔了"})
        assert r2.status_code == 200
        body = c.get("/api/presets/agentA", headers=HEADERS).json()
        assert body["emotion_count"] == 1
        assert body["emotion"][0]["text"] == "更温柔了"

    def test_action_success(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/action", headers=HEADERS,
                   json={"name": "打招呼", "tags": ["[emotion:happy]", "[action:wave]"]})
        assert r.status_code == 200
        assert r.json()["preset"]["tags"] == ["[emotion:happy]", "[action:wave]"]

    def test_empty_name_400(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/emotion", headers=HEADERS,
                   json={"name": "", "text": "t"})
        assert r.status_code == 400

    def test_empty_text_400(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/emotion", headers=HEADERS,
                   json={"name": "n", "text": "  "})
        assert r.status_code == 400

    def test_speed_type_error_422(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/emotion", headers=HEADERS,
                   json={"name": "n", "text": "t", "speed": "快一点"})
        assert r.status_code == 422  # pydantic 类型校验拦截

    def test_bad_tag_400(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/action", headers=HEADERS,
                   json={"name": "n", "tags": ["emotion:happy"]})  # 缺方括号
        assert r.status_code == 400

    def test_empty_tags_400(self, client):
        c, _ = client
        r = c.post("/api/presets/agentA/action", headers=HEADERS,
                   json={"name": "n", "tags": []})
        assert r.status_code == 400

    def test_invalid_agent_id_400(self, client):
        """路由段内非法 agent_id（非 ASCII）到达 handler 后被服务层校验拒绝 → 400。

        注：含 ../ 的穿越段会被 Starlette 路径规范化拦截为 404，到不了 handler；
        ../ 穿越的服务层拒绝已由 tests/test_preset_service.py::TestAgentIdGuard 覆盖。
        """
        c, _ = client
        r = c.get("/api/presets/%E4%B8%AD%E6%96%87id", headers=HEADERS)  # "中文id"
        assert r.status_code == 400
        r2 = c.post("/api/presets/%E4%B8%AD%E6%96%87id/emotion", headers=HEADERS,
                    json={"name": "n", "text": "t"})
        assert r2.status_code == 400


class TestDelete:
    def test_delete_missing_404(self, client):
        c, _ = client
        r = c.delete("/api/presets/agentA/emotion/不存在", headers=HEADERS)
        assert r.status_code == 404

    def test_delete_success_then_404(self, client):
        c, _ = client
        c.post("/api/presets/agentA/action", headers=HEADERS,
               json={"name": "待删", "tags": ["[action:nod]"]})
        r = c.delete("/api/presets/agentA/action/待删", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["deleted"] == "待删"
        r2 = c.delete("/api/presets/agentA/action/待删", headers=HEADERS)
        assert r2.status_code == 404
