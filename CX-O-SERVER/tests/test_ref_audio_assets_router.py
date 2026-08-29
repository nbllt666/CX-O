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
from server.qwen3_tts_provider import InvalidRefAudioError
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

    def test_set_missing_asset_id_raises_422(self, client):
        r = client.put("/ref-audio-assets/current", json={})
        assert r.status_code == 422

    def test_set_non_string_asset_id_raises_422(self, client):
        r = client.put("/ref-audio-assets/current", json={"asset_id": 123})
        assert r.status_code == 422

    def test_set_empty_asset_id_raises_422(self, client):
        r = client.put("/ref-audio-assets/current", json={"asset_id": ""})
        assert r.status_code == 422

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

    def test_oversize_returns_413(self, client, monkeypatch):
        # 上传防呆：Content-Length 预检超限 → 413（不整读入内存）
        monkeypatch.setattr(router_mod, "_MAX_UPLOAD_BYTES", 8)
        r = client.post(
            "/ref-audio-assets/from-file",
            files={"file": ("ref.wav", _wav_bytes(), "audio/wav")},
        )
        assert r.status_code == 413
        assert r.json()["detail"] == "音频文件过大"

    def test_invalid_audio_cleans_tmp(self, client):
        # InvalidRefAudioError 路径也必须清理 _upload_ 临时文件（实证残留回归）
        r = client.post(
            "/ref-audio-assets/from-file",
            files={"file": ("x.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 400
        residue = [
            p.name
            for p in ref_audio_store._resolve_assets_dir().iterdir()
            if p.name.startswith("_upload_")
        ]
        assert residue == []

    def test_tmp_name_unique_same_filename(self, client, monkeypatch):
        # 临时名含 uuid：同名文件上传不再互相覆盖（两次注册拿到不同临时路径）
        seen = []

        def _capture_and_fail(path, ref_text="", note=""):
            seen.append(path)
            raise InvalidRefAudioError("模拟校验失败")

        monkeypatch.setattr(ref_audio_store, "register_from_file", _capture_and_fail)
        for _ in range(2):
            r = client.post(
                "/ref-audio-assets/from-file",
                files={"file": ("ref.wav", _wav_bytes(), "audio/wav")},
            )
            assert r.status_code == 400
        assert len(seen) == 2
        assert seen[0] != seen[1]
        # 异常路径同样清理完毕
        residue = [
            p.name
            for p in ref_audio_store._resolve_assets_dir().iterdir()
            if p.name.startswith("_upload_")
        ]
        assert residue == []


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

    def test_missing_prompt_raises_422(self, client):
        r = client.post("/ref-audio-assets/from-prompt", json={})
        assert r.status_code == 422

    def test_non_string_prompt_raises_422(self, client):
        r = client.post("/ref-audio-assets/from-prompt", json={"prompt": 123})
        assert r.status_code == 422

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

    @pytest.mark.parametrize(
        "suffix,expected",
        [
            (".wav", "audio/wav"),
            (".mp3", "audio/mpeg"),
            (".flac", "audio/flac"),
            (".ogg", "audio/ogg"),
            (".m4a", "audio/mp4"),
            (".xyz", "audio/mpeg"),  # 未列出的扩展名保持现口径
        ],
    )
    def test_media_type_mapping(self, client, monkeypatch, tmp_path, suffix, expected):
        p = tmp_path / f"asset{suffix}"
        p.write_bytes(b"fake")
        monkeypatch.setattr(ref_audio_store, "get_audio_path", lambda asset_id: p)
        r = client.get("/ref-audio-assets/ref_any/audio")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(expected)


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

    def test_non_string_note_raises_422(self, client, tmp_path):
        src = tmp_path / "src_ref.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        r = client.patch(f"/ref-audio-assets/{asset.id}/note", json={"note": 123})
        assert r.status_code == 422


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