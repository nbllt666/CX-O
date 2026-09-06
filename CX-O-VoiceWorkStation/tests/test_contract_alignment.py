"""
契约对齐测试：sovits-svc infer / 音频文件服务 / 健康检查

对应 spec：add-voicews-music-cxfc-suite（Task 1 后端配置扩展与契约对齐）+
split-audio-workstation-cxfc-modelstation（VWS 瘦身：训练域端点迁至 ModelStation，
本文件不再覆盖 /status 与 trainer）。
所有外部依赖（So-VITS-SVC 子进程）均 mock，不触发真实推理。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workstation.config import get_settings
from workstation.main import create_app


@pytest_asyncio.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# So-VITS-SVC /infer 契约
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sovits_infer_contract(client, monkeypatch, tmp_path):
    """POST /api/sovits-svc/infer 响应含 audio_url，且不再包含 base64 audio_data"""
    fake_result = tmp_path / "converted_input.wav"
    fake_result.write_bytes(b"RIFF-fake-wav")

    class _FakeInferer:
        def __init__(self, **kwargs):
            pass

        async def infer(self, **kwargs):
            return fake_result

    import workstation.services.sovits_svc_infer as infer_module

    monkeypatch.setattr(infer_module, "SoVITSSVCInferer", _FakeInferer)

    resp = await client.post(
        "/api/sovits-svc/infer",
        json={"audio_path": "data/input/speaker/input.wav", "speaker_id": 0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["output_filename"] == "converted_input.wav"
    assert body["audio_url"] == "/api/audio-files/svc-results/converted_input.wav"
    assert "audio_data" not in body
    assert "format" not in body


@pytest.mark.asyncio
async def test_sovits_models_scans_models_dir(client, monkeypatch, tmp_path):
    """GET /api/sovits-svc/models 扫描 models_dir（ModelStation 模型目录），
    响应形状与原 trainer.list_models() 一致：{name, path, created, g_model, d_model}"""
    model_dir = tmp_path / "my_voice"
    model_dir.mkdir()
    (model_dir / "G_1000.pth").write_bytes(b"fake-g")
    (model_dir / "D_1000.pth").write_bytes(b"fake-d")

    settings = get_settings()
    monkeypatch.setattr(settings.sovits_svc, "models_dir", str(tmp_path))

    resp = await client.get("/api/sovits-svc/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert len(body["models"]) == 1
    item = body["models"][0]
    assert item["name"] == "my_voice"
    assert item["path"] == str(model_dir)
    assert "created" in item
    assert item["g_model"] == str(model_dir / "G_1000.pth")
    assert item["d_model"] == str(model_dir / "D_1000.pth")


@pytest.mark.asyncio
async def test_sovits_models_empty_dir(client, monkeypatch, tmp_path):
    """models_dir 不存在/为空时返回空列表而非报错"""
    settings = get_settings()
    monkeypatch.setattr(settings.sovits_svc, "models_dir", str(tmp_path / "nonexistent"))

    resp = await client.get("/api/sovits-svc/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == []


# ---------------------------------------------------------------------------
# 音频文件服务 /api/audio-files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_files_unknown_category_404(client):
    """白名单外 category 返回 404"""
    resp = await client.get("/api/audio-files/evil/x.wav")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audio_files_path_traversal_403(client, monkeypatch, tmp_path):
    """.. 路径穿越返回 403"""
    songs_dir = tmp_path / "songs"
    songs_dir.mkdir()
    (tmp_path / "secret.wav").write_bytes(b"secret")
    monkeypatch.setattr(get_settings().music, "songs_dir", str(songs_dir))

    # httpx 会在请求前归一化裸 ".." 段，故用 URL 编码的 %2e%2e 模拟穿越尝试，
    # 由服务端解码后进入路径校验逻辑
    resp = await client.get("/api/audio-files/songs/%2e%2e/secret.wav")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_audio_files_serve_ok(client, monkeypatch, tmp_path):
    """正常文件返回 200 且 Content-Type 正确"""
    songs_dir = tmp_path / "songs"
    songs_dir.mkdir()
    (songs_dir / "a.wav").write_bytes(b"RIFF-fake-wav")
    monkeypatch.setattr(get_settings().music, "songs_dir", str(songs_dir))

    resp = await client.get("/api/audio-files/songs/a.wav")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/wav")
    assert resp.content == b"RIFF-fake-wav"


@pytest.mark.asyncio
async def test_audio_files_songs_subpath_ok(client, monkeypatch, tmp_path):
    """songs 类别支持 <song_id>/final.wav 单层子路径"""
    song_dir = tmp_path / "songs" / "song-1"
    song_dir.mkdir(parents=True)
    (song_dir / "final.wav").write_bytes(b"RIFF-final")
    monkeypatch.setattr(get_settings().music, "songs_dir", str(tmp_path / "songs"))

    resp = await client.get("/api/audio-files/songs/song-1/final.wav")
    assert resp.status_code == 200
    assert resp.content == b"RIFF-final"


@pytest.mark.asyncio
async def test_audio_files_not_found_404(client, monkeypatch, tmp_path):
    """受控目录内但文件不存在返回 404"""
    songs_dir = tmp_path / "songs"
    songs_dir.mkdir()
    monkeypatch.setattr(get_settings().music, "songs_dir", str(songs_dir))

    resp = await client.get("/api/audio-files/songs/missing.wav")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /health 契约
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_contains_name_and_version(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    # 瘦身后 service 语义为「作曲/翻唱CXFC」；name = cxfc.plugin_name
    assert "作曲/翻唱CXFC" in body["service"]
    assert body["name"] == "作曲翻唱CXFC"
    assert body["version"] == "1.0.0"
