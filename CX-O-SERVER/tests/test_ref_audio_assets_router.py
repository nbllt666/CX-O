"""server.api.routers.ref_audio_assets 路由测试。

覆盖：
- GET /ref-audio-assets 列表（空 / 有资产）
- POST /ref-audio-assets/from-file 外部文件注册（成功 / 空文件 / 非音频）
- POST /ref-audio-assets/from-prompt 提示词生成（成功 / 空提示词 / 运行时未就绪 503）
- GET /ref-audio-assets/{id} 详情（成功 / 404）
- GET /ref-audio-assets/{id}/audio 试听（成功 / 404）
- PATCH /ref-audio-assets/{id}/note 注释更新（成功 / 404）
- DELETE /ref-audio-assets/{id} 删除（成功 / 404）

store 资产目录通过 ref_audio_store._set_assets_dir 隔离，与 test_ref_audio_store 一致。
运行：python -m pytest tests/test_ref_audio_assets_router.py -v
"""
import io
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import ref_audio_store
from server.api.routers import ref_audio_assets as router_mod
from server.ref_audio_store import GeneratedAudio, set_prompt_generator


def _wav_bytes(sample_rate: int = 24000, channels: int = 1, duration: float = 3.0) -> bytes:
    """生成一段 WAV 字节（PCM 静音）。"""
    buf = io.BytesIO()
    nframes = int(sample_rate * duration)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * nframes)
    return buf.getvalue()


async def _mock_prompt_generator(prompt, language):
    audio = _wav_bytes(sample_rate=24000, channels=1, duration=3.0)
    return GeneratedAudio(
        audio=audio, format="wav", sample_rate=24000, channels=1, duration_seconds=3.0
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离资产目录、清理生成器，并挂载路由。"""
    ref_audio_store._set_assets_dir(tmp_path)
    set_prompt_generator(_mock_prompt_generator)
    app = FastAPI()
    app.include_router(router_mod.router)
    yield TestClient(app, raise_server_exceptions=False)
    ref_audio_store._set_assets_dir(None)
    set_prompt_generator(None)


class TestListAssets:
    def test_empty(self, client):
        r = client.get("/ref-audio-assets")
        assert r.status_code == 200
        assert r.json() == {"assets": [], "current_asset_id": None}

    def test_with_assets(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        ref_audio_store.register_from_file(str(src))
        r = client.get("/ref-audio-assets")
        assert r.status_code == 200
        assets = r.json()["assets"]
        assert len(assets) == 1
        assert assets[0]["source"] == "file"
        assert assets[0]["id"].startswith("ref_")

    def test_list_reflects_current(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        ref_audio_store.set_current(asset.id)
        r = client.get("/ref-audio-assets")
        assert r.status_code == 200
        assert r.json()["current_asset_id"] == asset.id


class TestCurrentAsset:
    def test_get_none_when_unset(self, client):
        r = client.get("/ref-audio-assets/current")
        assert r.status_code == 200
        assert r.json() == {"asset": None}

    def test_set_and_get(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        r = client.put("/ref-audio-assets/current", json={"asset_id": asset.id})
        assert r.status_code == 200
        assert r.json()["current_asset_id"] == asset.id
        r2 = client.get("/ref-audio-assets/current")
        assert r2.status_code == 200
        assert r2.json()["asset"]["id"] == asset.id

    def test_set_missing_raises_404(self, client):
        r = client.put("/ref-audio-assets/current", json={"asset_id": "ref_nonexistent123"})
        assert r.status_code == 404

    def test_set_missing_asset_id_raises_400(self, client):
        r = client.put("/ref-audio-assets/current", json={})
        assert r.status_code == 400

    def test_clear(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        ref_audio_store.set_current(asset.id)
        r = client.delete("/ref-audio-assets/current")
        assert r.status_code == 200
        assert r.json()["current_asset_id"] is None
        assert client.get("/ref-audio-assets/current").json()["asset"] is None

    def test_delete_current_clears_pointer(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        ref_audio_store.set_current(asset.id)
        r = client.delete(f"/ref-audio-assets/{asset.id}")
        assert r.status_code == 200
        assert client.get("/ref-audio-assets/current").json()["asset"] is None


class TestFromFile:
    def test_register_success(self, client):
        r = client.post(
            "/ref-audio-assets/from-file",
            files={"file": ("ref.wav", _wav_bytes(), "audio/wav")},
            data={"ref_text": "你好", "note": "测试"},
        )
        assert r.status_code == 200
        asset = r.json()["asset"]
        assert asset["source"] == "file"
        assert asset["ref_text"] == "你好"
        assert asset["note"] == "测试"

    def test_empty_file(self, client):
        r = client.post(
            "/ref-audio-assets/from-file",
            files={"file": ("e.wav", b"", "audio/wav")},
        )
        assert r.status_code == 400

    def test_not_audio(self, client):
        r = client.post(
            "/ref-audio-assets/from-file",
            files={"file": ("x.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 400


class TestFromPrompt:
    def test_register_success(self, client):
        r = client.post("/ref-audio-assets/from-prompt", json={"prompt": "温柔可爱的少女音"})
        assert r.status_code == 200
        asset = r.json()["asset"]
        assert asset["source"] == "prompt"
        assert asset["prompt"] == "温柔可爱的少女音"

    def test_empty_prompt(self, client):
        r = client.post("/ref-audio-assets/from-prompt", json={"prompt": "  "})
        assert r.status_code == 400

    def test_runtime_unavailable(self, client):
        set_prompt_generator(None)
        r = client.post("/ref-audio-assets/from-prompt", json={"prompt": "少女音"})
        assert r.status_code == 503


class TestGetAsset:
    def test_success(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        r = client.get(f"/ref-audio-assets/{asset.id}")
        assert r.status_code == 200
        assert r.json()["id"] == asset.id

    def test_not_found(self, client):
        r = client.get("/ref-audio-assets/ref_nonexistent123")
        assert r.status_code in (404, 400)


class TestGetAssetAudio:
    def test_success(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        r = client.get(f"/ref-audio-assets/{asset.id}/audio")
        assert r.status_code == 200
        assert r.content[:4] == b"RIFF"

    def test_not_found(self, client):
        r = client.get("/ref-audio-assets/ref_nonexistent123/audio")
        assert r.status_code in (404, 400)


class TestUpdateNote:
    def test_success(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        r = client.patch(f"/ref-audio-assets/{asset.id}/note", json={"note": "新注释"})
        assert r.status_code == 200
        assert r.json()["note"] == "新注释"

    def test_not_found(self, client):
        r = client.patch("/ref-audio-assets/ref_nonexistent123/note", json={"note": "x"})
        assert r.status_code == 404


class TestDeleteAsset:
    def test_success(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        r = client.delete(f"/ref-audio-assets/{asset.id}")
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_not_found(self, client):
        r = client.delete("/ref-audio-assets/ref_nonexistent123")
        assert r.status_code == 404