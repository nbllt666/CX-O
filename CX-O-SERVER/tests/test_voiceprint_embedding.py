"""voiceprint_service.register_embedding 单元测试。

隔离数据路径：monkeypatch 模块级 _DATA_DIR / _PROFILES_FILE 到 tmp_path，
并把 _sync_remote 打成 no-op async，避免真连声纹容器/真写生产档案文件。
运行：python -m pytest tests/test_voiceprint_embedding.py -v
"""
import json

import pytest

from server.services import voiceprint_service as vp_mod
from server.services.voiceprint_service import VoiceprintService


@pytest.fixture
def service(tmp_path, monkeypatch):
    """隔离数据路径 + 屏蔽容器同步，返回模块级单例。"""
    monkeypatch.setattr(vp_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(vp_mod, "_PROFILES_FILE", tmp_path / "speaker_profiles.json")

    async def _noop_sync(self):
        pass

    monkeypatch.setattr(VoiceprintService, "_sync_remote", _noop_sync)
    return vp_mod._service


@pytest.mark.asyncio
async def test_register_new_profile_embeddings_count_1(service):
    summary = await service.register_embedding("阿明", [0.1, 0.2, 0.3])
    assert summary["name"] == "阿明"
    assert summary["embeddings_count"] == 1
    assert summary["created_at"]
    # 落盘文件结构正确
    data = json.loads(vp_mod._PROFILES_FILE.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["profiles"]) == 1
    assert data["profiles"][0]["embeddings"] == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_same_name_appends_embeddings_count_2(service):
    await service.register_embedding("阿明", [0.1, 0.2])
    summary = await service.register_embedding("阿明", [0.3, 0.4])
    assert summary["embeddings_count"] == 2
    data = json.loads(vp_mod._PROFILES_FILE.read_text(encoding="utf-8"))
    assert len(data["profiles"]) == 1
    assert data["profiles"][0]["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_register_tuple_embedding(service):
    summary = await service.register_embedding("老张", (0.5, 0.6))
    assert summary["embeddings_count"] == 1


@pytest.mark.asyncio
async def test_invalid_name_empty_raises(service):
    with pytest.raises(ValueError):
        await service.register_embedding("", [0.1, 0.2])


@pytest.mark.asyncio
async def test_invalid_name_too_long_raises(service):
    with pytest.raises(ValueError):
        await service.register_embedding("x" * 33, [0.1, 0.2])


@pytest.mark.asyncio
async def test_invalid_embedding_empty_raises(service):
    with pytest.raises(ValueError):
        await service.register_embedding("阿明", [])


@pytest.mark.asyncio
async def test_invalid_embedding_non_list_raises(service):
    with pytest.raises(ValueError):
        await service.register_embedding("阿明", "abc")


@pytest.mark.asyncio
async def test_file_not_written_on_invalid_args(service):
    with pytest.raises(ValueError):
        await service.register_embedding("阿明", [])
    assert not vp_mod._PROFILES_FILE.exists()


@pytest.mark.asyncio
async def test_concurrent_register_no_lost_update(service):
    """M 回归：并发注册经 _io_lock 串行 RMW，两个档案都落盘不丢更新。"""
    import asyncio

    results = await asyncio.gather(
        service.register_embedding("阿明", [0.1, 0.1]),
        service.register_embedding("老张", [0.2, 0.2]),
    )
    names = {r["name"] for r in results}
    assert names == {"阿明", "老张"}
    data = json.loads(vp_mod._PROFILES_FILE.read_text(encoding="utf-8"))
    persisted = sorted(p["name"] for p in data["profiles"])
    assert persisted == ["老张", "阿明"]  # 修复前并发覆写可能只留下一个


@pytest.mark.asyncio
async def test_delete_under_lock_roundtrip(service):
    """delete 走同一把锁：注册→删除→状态计数归零。"""
    await service.register_embedding("临时", [0.3, 0.3])
    assert await service.delete("临时") is True
    assert await service.delete("不存在") is False
    status = await service.get_status()
    assert status["profiles"] == 0