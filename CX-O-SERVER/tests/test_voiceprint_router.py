"""server.api.routers.voiceprint 路由测试（Task 5/6）。

monkeypatch voiceprint_service 各函数，不真连声纹容器。覆盖：
- 注册成功 201 / 容器不可用 503 / audio 非法或空 400 / name 非法 400
- 删除成功 200 / 不存在 404
- 列表 GET 200 / 状态 GET 200

运行：python -m pytest tests/test_voiceprint_router.py -v
"""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import voiceprint as vp_router_mod
from server.services import voiceprint_service as vp_mod
from server.services.voiceprint_service import VoiceprintUnavailableError

_AUDIO_B64 = base64.b64encode(b"\x00\x01\x02fake-wav-data").decode()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(vp_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


def test_register_success_201(client, monkeypatch):
    async def _register(name, audio_bytes):
        assert name == "阿明"
        assert audio_bytes
        return {"name": "阿明", "embeddings_count": 1, "created_at": "t", "updated": False}

    monkeypatch.setattr(vp_mod, "register", _register)
    r = client.post("/voiceprint/profiles", json={"name": "阿明", "audio": _AUDIO_B64})
    assert r.status_code == 201
    assert r.json()["profile"]["name"] == "阿明"


def test_register_container_unavailable_503(client, monkeypatch):
    async def _register(name, audio_bytes):
        raise VoiceprintUnavailableError("voiceprint service unavailable")

    monkeypatch.setattr(vp_mod, "register", _register)
    r = client.post("/voiceprint/profiles", json={"name": "阿明", "audio": _AUDIO_B64})
    assert r.status_code == 503
    # 对齐规范 detail 文案
    assert r.json()["detail"] == "voiceprint service unavailable"


def test_register_audio_empty_400(client, monkeypatch):
    r = client.post("/voiceprint/profiles", json={"name": "阿明", "audio": ""})
    assert r.status_code == 400


def test_register_audio_invalid_base64_400(client, monkeypatch):
    r = client.post("/voiceprint/profiles", json={"name": "阿明", "audio": "!!!not-base64!!!"})
    assert r.status_code == 400


def test_register_name_invalid_400(client, monkeypatch):
    async def _register(name, audio_bytes):
        raise ValueError("声纹档案名不能为空且长度不能超过 32")

    monkeypatch.setattr(vp_mod, "register", _register)
    r = client.post("/voiceprint/profiles", json={"name": "x" * 33, "audio": _AUDIO_B64})
    assert r.status_code == 400


def test_list_profiles_200(client, monkeypatch):
    monkeypatch.setattr(vp_mod, "list_profiles", lambda: [
        {"name": "阿明", "embeddings_count": 2, "created_at": "t"}
    ])
    r = client.get("/voiceprint/profiles")
    assert r.status_code == 200
    assert r.json()["profiles"][0]["name"] == "阿明"


def test_delete_success_200(client, monkeypatch):
    async def _delete(name):
        assert name == "阿明"
        return True

    monkeypatch.setattr(vp_mod, "delete", _delete)
    r = client.delete("/voiceprint/profiles/阿明")
    assert r.status_code == 200
    assert r.json()["status"] == "success"


def test_delete_not_found_404(client, monkeypatch):
    async def _delete(name):
        return False

    monkeypatch.setattr(vp_mod, "delete", _delete)
    r = client.delete("/voiceprint/profiles/不存在")
    assert r.status_code == 404


def test_status_200(client, monkeypatch):
    async def _status():
        return {"available": True, "profiles": 3, "threshold": 0.65}

    monkeypatch.setattr(vp_mod, "get_status", _status)
    r = client.get("/voiceprint/status")
    assert r.status_code == 200
    assert r.json()["available"] is True
    assert r.json()["profiles"] == 3
    assert r.json()["threshold"] == 0.65