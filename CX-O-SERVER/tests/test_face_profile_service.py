"""face_profile_service 单元测试（spec add-vlm-frame-filter-face-match Task 2.4）。

隔离策略：FakeExtractor 注入绕开 insightface 真模型（本机未装）；
config 注入 store_path 指向 tmp_path，不写生产档案文件。
运行：python -m pytest tests/test_face_profile_service.py -x -q
"""
import asyncio
import json

import pytest

from server.config import FaceMatchConfig
from server.services import face_profile_service as face_mod
from server.services.face_profile_service import (
    FaceProfileService,
    FaceServiceUnavailable,
    LocalFaceExtractor,
)


class FakeExtractor:
    """可控假提取器：返回预设人脸列表（绕开 insightface 真模型依赖）。

    faces: 固定返回的人脸列表（每次调用相同）；
    faces_queue: 每次调用依次弹出一个元素作为返回值，元素本身须是 faces 列表
    （即 [[face, ...], ...] 形态），用于并发/多次调用返回不同人脸。
    """

    def __init__(self, faces=None, error=None, faces_queue=None):
        self._faces = faces if faces is not None else []
        self._faces_queue = list(faces_queue) if faces_queue else None
        self._error = error
        self.calls: list = []

    def is_available(self) -> bool:
        return self._error is None

    async def extract(self, image_b64):
        self.calls.append(image_b64)
        if self._error is not None:
            raise self._error
        if self._faces_queue:
            return self._faces_queue.pop(0)
        return list(self._faces)


def _face(embedding, bbox=(0.0, 0.0, 100.0, 100.0)):
    """构造单个人脸提取结果。"""
    return {"embedding": list(embedding), "bbox": list(bbox)}


def _make_service(tmp_path, extractor=None, **cfg_kwargs):
    """构造注入假提取器 + tmp 档案路径的服务实例。"""
    cfg_kwargs.setdefault("enabled", True)
    cfg_kwargs.setdefault("store_path", str(tmp_path / "profiles.json"))
    cfg = FaceMatchConfig(**cfg_kwargs)
    if extractor is None:
        extractor = FakeExtractor()
    return FaceProfileService(config=cfg, extractor=extractor)


# ---------------------------------------------------------------------- register


@pytest.mark.asyncio
async def test_register_success_largest_bbox_and_overwrite(tmp_path):
    """注册成功：取最大 bbox 人脸入档；重名覆盖向量且档案数不变。"""
    # 两张脸：小 bbox 脸 [0.5, 0.5]，大 bbox 脸 [1.0, 0.0]（应被选中）
    svc = _make_service(
        tmp_path,
        FakeExtractor(
            faces=[
                _face([0.5, 0.5], bbox=(0.0, 0.0, 10.0, 10.0)),
                _face([1.0, 0.0], bbox=(0.0, 0.0, 200.0, 200.0)),
            ]
        ),
    )
    result = await svc.register("小A", "img_b64")
    assert result["name"] == "小A"
    assert result["embedding_dim"] == 2
    assert result["faces_detected"] == 2
    assert result["created_at"]

    data = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert data["version"] == "1.0"
    assert len(data["profiles"]) == 1
    assert data["profiles"][0]["embedding"] == [1.0, 0.0]  # 最大 bbox 脸的向量

    # 重名覆盖：第二个服务实例指向同一档案文件，覆盖向量，档案数仍为 1
    svc2 = _make_service(tmp_path, FakeExtractor(faces=[_face([0.0, 1.0])]))
    await svc2.register("小A", "img_b64_2")
    data = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert len(data["profiles"]) == 1
    assert data["profiles"][0]["embedding"] == [0.0, 1.0]


@pytest.mark.asyncio
async def test_register_no_face_raises(tmp_path):
    """注册无人脸报 ValueError，且不落盘。"""
    svc = _make_service(tmp_path, FakeExtractor(faces=[]))
    with pytest.raises(ValueError):
        await svc.register("小A", "img_b64")
    assert not (tmp_path / "profiles.json").exists()


@pytest.mark.asyncio
async def test_register_empty_name_raises(tmp_path):
    svc = _make_service(tmp_path)
    with pytest.raises(ValueError):
        await svc.register("  ", "img_b64")


# ---------------------------------------------------------------------- match


@pytest.mark.asyncio
async def test_match_hit_and_unknown_branches(tmp_path):
    """match 命中分支（≥阈值返回 name/similarity/bbox）与 unknown 分支。"""
    svc = _make_service(tmp_path, FakeExtractor(faces=[_face([1.0, 0.0])]))
    await svc.register("小A", "img_b64")

    hit_extractor = FakeExtractor(
        faces=[
            _face([0.98, 0.199], bbox=(1.0, 2.0, 3.0, 4.0)),  # 余弦≈0.98 ≥ 0.45 → 命中
            _face([0.0, 1.0], bbox=(5.0, 6.0, 7.0, 8.0)),  # 与档案正交 → unknown
        ]
    )
    svc2 = _make_service(tmp_path, hit_extractor)
    results = await svc2.match("img_b64")
    assert len(results) == 2

    hit = results[0]
    assert hit["name"] == "小A"
    assert hit["similarity"] == pytest.approx(0.98, abs=1e-3)
    assert hit["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert "unknown" not in hit

    unknown = results[1]
    assert unknown["unknown"] is True
    assert unknown["best_similarity"] == pytest.approx(0.0, abs=1e-6)
    assert unknown["bbox"] == [5.0, 6.0, 7.0, 8.0]
    assert "name" not in unknown


@pytest.mark.asyncio
async def test_match_without_profiles_all_unknown(tmp_path):
    """无档案：各脸均 unknown（best_similarity=0.0），不自动入档。"""
    svc = _make_service(tmp_path, FakeExtractor(faces=[_face([1.0, 0.0])]))
    results = await svc.match("img_b64")
    assert results == [
        {"unknown": True, "best_similarity": 0.0, "bbox": [0.0, 0.0, 100.0, 100.0]}
    ]
    assert await svc.list_profiles() == []


@pytest.mark.asyncio
async def test_match_no_face_returns_empty(tmp_path):
    svc = _make_service(tmp_path, FakeExtractor(faces=[]))
    assert await svc.match("img_b64") == []


# ---------------------------------------------------------------------- list / delete


@pytest.mark.asyncio
async def test_list_profiles_desensitized(tmp_path):
    """list 脱敏：仅 name/embedding_dim/created_at，断言无 embedding 键。"""
    svc = _make_service(tmp_path, FakeExtractor(faces=[_face([1.0, 0.0])]))
    await svc.register("小A", "img_b64")
    items = await svc.list_profiles()
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "小A"
    assert item["embedding_dim"] == 2
    assert item["created_at"]
    assert "embedding" not in item  # 隐私红线：向量本体不透出


@pytest.mark.asyncio
async def test_delete_profile_hit_and_miss(tmp_path):
    svc = _make_service(tmp_path, FakeExtractor(faces=[_face([1.0, 0.0])]))
    await svc.register("小A", "img_b64")
    assert await svc.delete_profile("小A") is True
    assert await svc.delete_profile("小A") is False  # 幂等：不存在返回 False
    assert await svc.list_profiles() == []


# ---------------------------------------------------------------------- 存储与并发


@pytest.mark.asyncio
async def test_atomic_write_loadable_no_tmp_left(tmp_path):
    """原子写：写后文件可直接 json.load，且无残留 .tmp 临时文件。"""
    svc = _make_service(tmp_path, FakeExtractor(faces=[_face([1.0, 0.0])]))
    await svc.register("小A", "img_b64")
    path = tmp_path / "profiles.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "1.0"
    assert len(data["profiles"]) == 1
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_custom_store_path_used(tmp_path):
    """store_path 自定义路径生效（含父目录自动创建），默认路径未被使用。"""
    custom = tmp_path / "custom_dir" / "my_faces.json"
    svc = _make_service(
        tmp_path, FakeExtractor(faces=[_face([1.0, 0.0])]), store_path=str(custom)
    )
    await svc.register("小A", "img_b64")
    assert custom.exists()
    assert not (tmp_path / "profiles.json").exists()


@pytest.mark.asyncio
async def test_concurrent_register_no_lost_update(tmp_path):
    """并发注册经 _io_lock 串行 RMW：四个档案全部落盘不丢更新。"""
    # 每次调用弹出一个元素（该元素须是一次 extract 调用应返回的 faces 列表）
    queue = [[_face([float(i), 1.0])] for i in range(4)]
    svc = _make_service(tmp_path, FakeExtractor(faces_queue=queue))
    results = await asyncio.gather(
        *(svc.register(f"person{i}", "img_b64") for i in range(4))
    )
    assert {r["name"] for r in results} == {f"person{i}" for i in range(4)}
    data = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert sorted(p["name"] for p in data["profiles"]) == [
        f"person{i}" for i in range(4)
    ]


# ---------------------------------------------------------------------- 降级与开关


@pytest.mark.asyncio
async def test_local_deps_missing_graceful_degradation(tmp_path, monkeypatch):
    """local 库缺失降级：register/match 抛 FaceServiceUnavailable（含安装提示），
    get_status available=False 且不触发模型加载。"""
    monkeypatch.setattr(face_mod, "_check_local_deps", lambda: False)
    cfg = FaceMatchConfig(
        enabled=True, provider="local", store_path=str(tmp_path / "profiles.json")
    )
    svc = FaceProfileService(config=cfg)  # 不注入 extractor → 走真实 LocalFaceExtractor

    status = svc.get_status()
    assert status["available"] is False
    assert status["provider"] == "local"
    assert status["enabled"] is True

    with pytest.raises(FaceServiceUnavailable, match=r"pip install insightface onnxruntime"):
        await svc.register("小A", "img_b64")
    with pytest.raises(FaceServiceUnavailable, match=r"pip install insightface onnxruntime"):
        await svc.match("img_b64")
    # 降级后提取器置 unavailable，is_available 持续 False
    assert isinstance(svc._get_extractor(), LocalFaceExtractor)
    assert svc._get_extractor().is_available() is False


@pytest.mark.asyncio
async def test_disabled_raises_unavailable(tmp_path):
    """enabled=false：四个异步方法均抛 FaceServiceUnavailable（face.pyi 契约），
    get_status 正常返回且 enabled=False。"""
    svc = _make_service(tmp_path, enabled=False)
    with pytest.raises(FaceServiceUnavailable):
        await svc.register("小A", "img_b64")
    with pytest.raises(FaceServiceUnavailable):
        await svc.match("img_b64")
    with pytest.raises(FaceServiceUnavailable):
        await svc.list_profiles()
    with pytest.raises(FaceServiceUnavailable):
        await svc.delete_profile("小A")
    status = svc.get_status()
    assert status["enabled"] is False
