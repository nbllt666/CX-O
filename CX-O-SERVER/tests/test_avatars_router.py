"""server.api.routers.avatars 路由测试。

用 tmp_path 重定向 VRM_DIR/LIVE2D_DIR，隔离真实文件系统。覆盖：
- list / upload（vrm/live2d/非法扩展名/空文件名/超限）
- get / get_file（404）/ update / delete
- avatar_id 路径遍历防护

运行：python -m pytest tests/test_avatars_router.py -v
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import avatars as avatars_mod


@pytest.fixture
def client(monkeypatch, tmp_path):
    vrm = tmp_path / "vrm"
    live2d = tmp_path / "live2d"
    vrm.mkdir(parents=True, exist_ok=True)
    live2d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(avatars_mod, "VRM_DIR", vrm)
    monkeypatch.setattr(avatars_mod, "LIVE2D_DIR", live2d)

    app = FastAPI()
    app.include_router(avatars_mod.router)
    return TestClient(app), vrm, live2d


def _upload(c, avatar_type="vrm", filename="model.vrm", content=b"\x00\x01", name=None):
    data = {"avatar_type": avatar_type}
    if name is not None:
        data["name"] = name
    return c.post("/avatars/upload", files={"file": (filename, content)}, data=data)


class TestValidateAvatarId:
    def test_path_traversal_rejected(self, client):
        c, vrm, _ = client
        # 路径穿越字符应被拒
        with pytest.raises(Exception):
            avatars_mod._validate_avatar_id("../evil", "vrm")

    def test_invalid_chars_rejected(self, client):
        c, vrm, _ = client
        import fastapi
        with pytest.raises(fastapi.HTTPException):
            avatars_mod._validate_avatar_id("bad id!", "vrm")

    def test_valid_id_accepted(self, client):
        c, vrm, _ = client
        # 合法 ID 不抛异常
        avatars_mod._validate_avatar_id("model-1_x", "vrm")


class TestListAvatars:
    def test_empty(self, client):
        c, vrm, _ = client
        r = c.get("/avatars")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_after_upload(self, client):
        c, vrm, _ = client
        _upload(c, avatar_type="vrm", filename="m.vrm")
        r = c.get("/avatars")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_type_filter_vrm_excludes_live2d(self, client):
        c, vrm, _ = client
        _upload(c, avatar_type="vrm", filename="m.vrm")
        _upload(c, avatar_type="live2d", filename="m.model.json")
        r = c.get("/avatars", params={"type": "vrm"})
        assert r.json()["total"] == 1


class TestUpload:
    def test_vrm_success(self, client):
        c, vrm, _ = client
        r = _upload(c, avatar_type="vrm", filename="model.vrm", name="我的模型")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["avatar"]["type"] == "vrm"
        assert body["avatar"]["name"] == "我的模型"
        # 文件已落盘
        assert len(list(vrm.glob("*.vrm"))) == 1

    def test_live2d_model3_json_success(self, client):
        c, _, live2d = client
        r = _upload(c, avatar_type="live2d", filename="char.model3.json")
        assert r.status_code == 200
        assert r.json()["avatar"]["type"] == "live2d"
        assert len(list(live2d.glob("*.model3.json"))) == 1

    def test_invalid_extension_400(self, client):
        c, vrm, _ = client
        r = _upload(c, avatar_type="vrm", filename="model.txt")
        assert r.status_code == 400

    def test_empty_filename_422(self, client):
        c, vrm, _ = client
        # FastAPI 在上传层校验文件名必填，空文件名在进入 handler 前即被 422 拒绝
        r = _upload(c, avatar_type="vrm", filename="")
        assert r.status_code == 422

    def test_oversize_400(self, client, monkeypatch):
        c, vrm, _ = client
        monkeypatch.setattr(avatars_mod, "MAX_FILE_SIZE", 10)
        r = _upload(c, avatar_type="vrm", filename="big.vrm", content=b"\x00" * 100)
        assert r.status_code == 400
        assert "大小" in r.json()["detail"]


class TestGetAvatar:
    def test_success(self, client):
        c, vrm, _ = client
        up = _upload(c, avatar_type="vrm", filename="m.vrm").json()["avatar"]
        r = c.get(f"/avatars/{up['id']}", params={"avatar_type": "vrm"})
        assert r.status_code == 200
        assert r.json()["id"] == up["id"]

    def test_not_found_404(self, client):
        c, vrm, _ = client
        r = c.get("/avatars/nonexistent", params={"avatar_type": "vrm"})
        assert r.status_code == 404


class TestGetAvatarFile:
    def test_success(self, client):
        c, vrm, _ = client
        up = _upload(c, avatar_type="vrm", filename="model.vrm", content=b"VRMBIN").json()["avatar"]
        r = c.get(f"/avatars/{up['id']}/file", params={"avatar_type": "vrm"})
        assert r.status_code == 200
        assert r.content == b"VRMBIN"

    def test_not_found_404(self, client):
        c, vrm, _ = client
        r = c.get("/avatars/nonexistent/file", params={"avatar_type": "vrm"})
        assert r.status_code == 404


class TestUpdateAvatar:
    def test_success(self, client):
        c, vrm, _ = client
        up = _upload(c, avatar_type="vrm", filename="m.vrm").json()["avatar"]
        r = c.put(f"/avatars/{up['id']}", params={"avatar_type": "vrm"},
                  json={"name": "新名字", "metadata": {"k": "v"}})
        assert r.status_code == 200
        assert r.json()["avatar"]["name"] == "新名字"

    def test_not_found_404(self, client):
        c, vrm, _ = client
        r = c.put("/avatars/nonexistent", params={"avatar_type": "vrm"}, json={"name": "x"})
        assert r.status_code == 404


class TestDeleteAvatar:
    def test_success(self, client):
        c, vrm, _ = client
        up = _upload(c, avatar_type="vrm", filename="m.vrm").json()["avatar"]
        r = c.delete(f"/avatars/{up['id']}", params={"avatar_type": "vrm"})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        # 文件已删除
        assert len(list(vrm.glob("*.vrm"))) == 0

    def test_not_found_404(self, client):
        c, vrm, _ = client
        r = c.delete("/avatars/nonexistent", params={"avatar_type": "vrm"})
        assert r.status_code == 404


class TestSaveAvatarMetadataAtomic:
    """E6: 元数据原子写——落盘为合法 JSON；写入中途失败不破坏原文件。"""

    def test_save_writes_valid_json(self, client):
        c, vrm, _ = client
        up = _upload(c, avatar_type="vrm", filename="m.vrm").json()["avatar"]
        meta_path = vrm / f"{up['id']}.json"
        # 保存后文件为合法 JSON 且字段一致
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["id"] == up["id"]
        assert data["name"] == up["name"]
        assert data["type"] == "vrm"

    def test_save_failure_keeps_original_file(self, client, monkeypatch):
        c, vrm, _ = client
        up = _upload(c, avatar_type="vrm", filename="m.vrm").json()["avatar"]
        meta_path = vrm / f"{up['id']}.json"
        old_content = meta_path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise RuntimeError("模拟 json.dump 中途失败")

        # 模拟序列化中途异常：原文件必须保持旧内容，且无残留 .tmp
        monkeypatch.setattr(json, "dump", _boom)
        metadata = avatars_mod.AvatarMetadata(**up)
        with pytest.raises(RuntimeError):
            avatars_mod._save_avatar_metadata(metadata)

        assert meta_path.read_text(encoding="utf-8") == old_content
        assert list(vrm.glob("*.tmp")) == []