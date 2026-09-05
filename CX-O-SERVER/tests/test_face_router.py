"""人脸 REST 路由 + register_face_profile 工具 + frame_cache 单元测试（T3）。

隔离外部依赖：monkeypatch sys.modules 注入 fake face_profile_service 模块
（T2 实体并行交付中，不依赖其存在），不真连人脸提取模型。覆盖：

- 路由 CRUD 闭环：POST 201（image 原样透传含 dataURL 前缀）→ GET 含 → DELETE → GET 不含
- 参数校验 422：空 name / 缺 image / name 超 64 字符
- 大小防呆 413：对齐 voiceprint 的 base64 长度预检口径（monkeypatch 阈值）
- 服务层错误映射：ValueError → 400；FaceServiceUnavailable → 503（中文含安装提示）
- 鉴权口径：与 voiceprint 一致（无鉴权依赖），CRUD 成功用例即无 auth 头直接可达的证明
- face_tool：缓存空 → 中文错误；有帧 → 调 FakeService.register 成功回执
- frame_cache：set/get/clear、空值忽略、多线程并发覆盖不撕裂

运行：python -m pytest tests/test_face_router.py -v
"""
import base64
import sys
import threading
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.core.tools.face_tool as ft_mod
from server.api.routers import face as face_router_mod
from server.core.tools.registry import tool_registry
from server.core.tools.face_tool import _handler, register_face_tool
from server.core.vision import frame_cache

_IMAGE_B64 = base64.b64encode(b"\x00\x01fake-jpeg-data").decode()
_DATA_URL = f"data:image/jpeg;base64,{_IMAGE_B64}"


# ---------------------------------------------------------------- fake 服务
class FakeFaceService:
    """FaceProfileService 替身：记录调用，可注入错误场景。"""

    def __init__(self, unavailable_cls):
        self._unavailable_cls = unavailable_cls
        self.profiles = {}  # name -> created_at
        self.register_calls = []
        self.unavailable = False
        self.value_error = None

    async def register(self, name, image_b64):
        self.register_calls.append((name, image_b64))
        if self.unavailable:
            raise self._unavailable_cls("unavailable")
        if self.value_error:
            raise ValueError(self.value_error)
        self.profiles[name] = "t"
        return {"name": name, "faces_detected": 1, "created_at": "t"}

    async def match(self, image_b64):
        if self.unavailable:
            raise self._unavailable_cls("unavailable")
        if self.value_error:
            raise ValueError(self.value_error)
        return [{"name": "小A", "similarity": 0.8, "bbox": [1, 2, 3, 4]}]

    async def list_profiles(self):
        if self.unavailable:
            raise self._unavailable_cls("unavailable")
        return [{"name": n, "created_at": t} for n, t in self.profiles.items()]

    async def delete_profile(self, name):
        if self.unavailable:
            raise self._unavailable_cls("unavailable")
        return self.profiles.pop(name, None) is not None

    def get_status(self):
        return {"enabled": True, "provider": "local", "ready": True,
                "profile_count": len(self.profiles)}


@pytest.fixture
def fake_svc(monkeypatch):
    """注入 fake 服务并返回 (service, 异常类)。异常类与 fake 模块同源，确保路由捕获命中。"""
    svc_holder = {}
    svc = FakeFaceService(unavailable_cls=None)
    svc_holder["svc"] = svc

    def _factory():
        return svc_holder["svc"]

    mod = types.ModuleType("server.services.face_profile_service")

    class FaceServiceUnavailable(RuntimeError):
        pass

    mod.FaceServiceUnavailable = FaceServiceUnavailable
    mod.get_face_profile_service = _factory
    monkeypatch.setitem(sys.modules, "server.services.face_profile_service", mod)

    svc._unavailable_cls = FaceServiceUnavailable  # 回填：抛出与路由捕获同类异常
    return svc, FaceServiceUnavailable


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(face_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- 路由 CRUD
def test_register_success_201(client, fake_svc):
    svc, _ = fake_svc
    r = client.post("/face/profiles", json={"name": "小A", "image": _DATA_URL})
    assert r.status_code == 201
    assert r.json()["profile"]["name"] == "小A"
    # image 原样透传服务层（dataURL/base64 通用解码交服务层，路由不解码）
    assert svc.register_calls == [("小A", _DATA_URL)]


def test_register_list_delete_crud_loop(client, fake_svc):
    """CRUD 闭环：POST 注册 → GET 列表含 → DELETE → GET 不含（无鉴权头直接可达）。"""
    client.post("/face/profiles", json={"name": "小A", "image": _IMAGE_B64})

    r = client.get("/face/profiles")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()["profiles"]]
    assert "小A" in names
    assert "embedding" not in r.text  # 脱敏：列表不透出向量本体字段

    r = client.delete("/face/profiles/小A")
    assert r.status_code == 200
    assert r.json() == {"status": "success", "name": "小A"}

    r = client.get("/face/profiles")
    assert "小A" not in [p["name"] for p in r.json()["profiles"]]


def test_register_empty_name_422(client, fake_svc):
    r = client.post("/face/profiles", json={"name": "", "image": _IMAGE_B64})
    assert r.status_code == 422


def test_register_missing_image_422(client, fake_svc):
    r = client.post("/face/profiles", json={"name": "小A"})
    assert r.status_code == 422


def test_register_name_too_long_422(client, fake_svc):
    r = client.post("/face/profiles", json={"name": "x" * 65, "image": _IMAGE_B64})
    assert r.status_code == 422


def test_register_oversize_413(client, fake_svc, monkeypatch):
    # 上传防呆：对齐 voiceprint 的 base64 编码长度预检口径（缩阈值便于测试）
    monkeypatch.setattr(face_router_mod, "_MAX_UPLOAD_BYTES", 8)
    big = "A" * 64
    r = client.post("/face/profiles", json={"name": "小A", "image": big})
    assert r.status_code == 413
    assert r.json()["detail"] == "图像文件过大"


def test_register_service_value_error_400(client, fake_svc):
    svc, _ = fake_svc
    svc.value_error = "未检出人脸"
    r = client.post("/face/profiles", json={"name": "小A", "image": _IMAGE_B64})
    assert r.status_code == 400


def test_register_unavailable_503(client, fake_svc):
    svc, cls = fake_svc
    svc.unavailable = True
    r = client.post("/face/profiles", json={"name": "小A", "image": _IMAGE_B64})
    assert r.status_code == 503
    # 中文 detail 含安装提示（local 依赖 insightface/onnxruntime）
    assert "insightface" in r.json()["detail"]


def test_delete_not_found_404(client, fake_svc):
    r = client.delete("/face/profiles/不存在")
    assert r.status_code == 404
    assert r.json()["detail"] == "未找到该人脸档案"


def test_delete_unavailable_503(client, fake_svc):
    svc, _ = fake_svc
    svc.unavailable = True
    r = client.delete("/face/profiles/小A")
    assert r.status_code == 503


def test_list_unavailable_503(client, fake_svc):
    svc, _ = fake_svc
    svc.unavailable = True
    r = client.get("/face/profiles")
    assert r.status_code == 503


def test_status_200(client, fake_svc):
    r = client.get("/face/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["provider"] == "local"
    assert body["ready"] is True
    assert body["profile_count"] == 0


def test_match_200(client, fake_svc):
    r = client.post("/face/match", json={"image": _IMAGE_B64})
    assert r.status_code == 200
    matches = r.json()["matches"]
    assert matches[0]["name"] == "小A"
    assert matches[0]["similarity"] == 0.8


def test_match_empty_image_422(client, fake_svc):
    r = client.post("/face/match", json={"image": ""})
    assert r.status_code == 422


def test_match_unavailable_503(client, fake_svc):
    svc, _ = fake_svc
    svc.unavailable = True
    r = client.post("/face/match", json={"image": _IMAGE_B64})
    assert r.status_code == 503


# ---------------------------------------------------------------- face_tool
@pytest.fixture(autouse=True)
def _clean_frame_cache():
    """每个用例前后清空帧缓存单例，保证隔离。"""
    frame_cache.clear()
    yield
    frame_cache.clear()


@pytest.mark.asyncio
async def test_tool_no_frame_returns_chinese_error(fake_svc):
    result = await _handler(name="小明")
    assert result["success"] is False
    assert "摄像头" in result["error"]
    assert result["tool_name"] == "register_face_profile"


@pytest.mark.asyncio
async def test_tool_with_frame_registers(fake_svc):
    svc, _ = fake_svc
    frame_cache.set_recent_frame(_DATA_URL)
    result = await _handler(name="小明")
    assert result["success"] is True
    assert result["name"] == "小明"
    assert "已记住" in result["message"]
    # 最近帧原样透传服务层
    assert svc.register_calls == [("小明", _DATA_URL)]


@pytest.mark.asyncio
async def test_tool_unavailable_returns_install_hint(fake_svc):
    svc, cls = fake_svc
    svc.unavailable = True
    frame_cache.set_recent_frame(_IMAGE_B64)
    result = await _handler(name="小明")
    assert result["success"] is False
    assert "insightface" in result["error"]


@pytest.mark.asyncio
async def test_tool_value_error_passthrough(fake_svc):
    svc, _ = fake_svc
    svc.value_error = "未检出人脸"
    frame_cache.set_recent_frame(_IMAGE_B64)
    result = await _handler(name="小明")
    assert result["success"] is False
    assert "未检出人脸" in result["error"]


def test_register_face_tool_is_registered():
    tool_registry.delete_tool("register_face_profile")
    register_face_tool()
    tool = tool_registry.get_tool("register_face_profile")
    assert tool is not None
    assert tool.enabled is True

    fn = tool.to_openai_function()
    assert fn["function"]["name"] == "register_face_profile"
    params = fn["function"]["parameters"]
    assert params["required"] == ["name"]
    assert "name" in params["properties"]


# ---------------------------------------------------------------- frame_cache
def test_frame_cache_set_get_roundtrip():
    frame_cache.set_recent_frame(_DATA_URL)
    assert frame_cache.get_recent_frame() == _DATA_URL


def test_frame_cache_empty_returns_none():
    frame_cache.clear()
    assert frame_cache.get_recent_frame() is None


def test_frame_cache_clear():
    frame_cache.set_recent_frame(_IMAGE_B64)
    frame_cache.clear()
    assert frame_cache.get_recent_frame() is None


def test_frame_cache_set_empty_ignored():
    frame_cache.set_recent_frame(_IMAGE_B64)
    frame_cache.set_recent_frame("")  # 空串不覆盖已有帧
    assert frame_cache.get_recent_frame() == _IMAGE_B64


def test_frame_cache_overwrite_keeps_latest():
    frame_cache.set_recent_frame("first")
    frame_cache.set_recent_frame("second")
    assert frame_cache.get_recent_frame() == "second"


def test_frame_cache_concurrent_overwrite():
    """多线程并发覆盖：槽内值始终完整（不撕裂），最终值为写入集合之一。"""
    frame_cache.clear()
    payloads = [f"data:image/jpeg;base64,{'A' * 500}{i:04d}" for i in range(8)]
    errors = []

    def _worker(idx: int) -> None:
        try:
            payload = payloads[idx]
            for _ in range(200):
                frame_cache.set_recent_frame(payload)
                got = frame_cache.get_recent_frame()
                assert got is not None  # 读取原子性：非空且完整
        except Exception as e:  # noqa: BLE001 测试收集线程异常
            errors.append(e)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    final = frame_cache.get_recent_frame()
    assert final in payloads  # 完整串（含唯一后缀）∈ 写入集合 → 无撕裂
