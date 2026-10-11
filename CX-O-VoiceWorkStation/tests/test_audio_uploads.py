"""
受控上传端点单测：POST /api/audio-uploads

对应 spec：split-audio-workstation-cxfc-modelstation「翻唱音频受控上传」。
覆盖：合法上传（含 .m4a 大小写不敏感）落盘、非法扩展 400 不落盘、
超限 400（注入 1MB 小上限而非真传 50MB）、空文件 400、
文件名服务端重生成格式、上传目录与 infer 白名单根一致性（上传即可推理）。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import anyio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workstation.config import get_settings
from workstation.main import create_app
from workstation.api.audio_uploads import upload_audio
from fastapi import HTTPException

# 服务端重生成文件名格式：{uuid4 hex 前 12 位}{原扩展名}
_UUID12_RE = re.compile(r"^[0-9a-f]{12}$")


@pytest_asyncio.fixture
async def upload_env(tmp_path, monkeypatch):
    """隔离的上传测试环境：落盘目录指向 tmp_path/input（不污染真实 data/input）"""
    settings = get_settings()
    input_dir = tmp_path / "input"
    monkeypatch.setattr(settings.audio_upload, "input_dir", str(input_dir))

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, input_dir


def _dir_entries(input_dir: Path) -> list[str]:
    if not input_dir.exists():
        return []
    return [p.name for p in input_dir.iterdir()]


class TestAudioUploads:
    @pytest.mark.asyncio
    async def test_upload_wav_ok(self, upload_env):
        """合法 .wav 上传：200、文件落盘、audio_path 为落盘绝对路径"""
        client, input_dir = upload_env
        resp = await client.post(
            "/api/audio-uploads",
            files={"file": ("song.wav", b"RIFF-fake-wav", "audio/wav")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"

        # 文件名服务端重生成：12 位 uuid hex + 原扩展名（不沿用原始文件名）
        filename = body["filename"]
        assert _UUID12_RE.match(Path(filename).stem), f"filename 格式非法: {filename}"
        assert Path(filename).suffix == ".wav"

        dest = Path(body["audio_path"])
        assert dest.is_absolute(), "audio_path 必须为绝对路径"
        assert dest.is_file()
        assert dest.read_bytes() == b"RIFF-fake-wav"
        assert dest.parent == input_dir.resolve()
        assert body["filename"] == dest.name

    @pytest.mark.asyncio
    async def test_upload_m4a_case_insensitive_ok(self, upload_env):
        """扩展名白名单大小写不敏感：.M4A 亦接受，落盘为小写 .m4a"""
        client, input_dir = upload_env
        resp = await client.post(
            "/api/audio-uploads",
            files={"file": ("SONG.M4A", b"fake-m4a-bytes", "audio/mp4")},
        )
        assert resp.status_code == 200
        assert Path(resp.json()["filename"]).suffix == ".m4a"

    @pytest.mark.asyncio
    async def test_upload_rejects_bad_extension(self, upload_env):
        """白名单外扩展名（.exe）→ 400 可读错误，不落盘"""
        client, input_dir = upload_env
        resp = await client.post(
            "/api/audio-uploads",
            files={"file": ("evil.exe", b"MZ-fake-binary", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "不支持的音频格式" in resp.json()["detail"]
        assert _dir_entries(input_dir) == []

    @pytest.mark.asyncio
    async def test_upload_rejects_oversize(self, upload_env, monkeypatch):
        """超上限 → 400 可读错误，不落盘（注入 1MB 小上限，不真传 50MB）"""
        client, input_dir = upload_env
        settings = get_settings()
        monkeypatch.setattr(settings.audio_upload, "max_size_mb", 1)

        big = b"\x00" * (1024 * 1024 + 1)
        resp = await client.post(
            "/api/audio-uploads",
            files={"file": ("big.wav", big, "audio/wav")},
        )
        assert resp.status_code == 400
        assert "文件过大" in resp.json()["detail"]
        assert _dir_entries(input_dir) == []

    @pytest.mark.asyncio
    async def test_upload_rejects_empty_file(self, upload_env):
        """空文件 → 400，不落盘"""
        client, input_dir = upload_env
        resp = await client.post(
            "/api/audio-uploads",
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        assert resp.status_code == 400
        assert _dir_entries(input_dir) == []

    @pytest.mark.asyncio
    async def test_upload_filename_no_path_traversal(self, upload_env):
        """原始文件名含路径分隔符也不落盘到白名单根之外（服务端重生成命名）"""
        client, input_dir = upload_env
        resp = await client.post(
            "/api/audio-uploads",
            files={"file": ("..\\..\\escape.wav", b"RIFF-x", "audio/wav")},
        )
        assert resp.status_code == 200
        dest = Path(resp.json()["audio_path"])
        assert dest.is_relative_to(input_dir.resolve())
        assert _dir_entries(input_dir) == [dest.name]


class TestUploadDirMatchesInferWhitelist:
    def test_upload_input_dir_equals_infer_allowed_root(self):
        """config.audio_upload.input_dir 默认值 == SoVITSSVCInferer 默认白名单根
        （data/input/）：上传产物天然通过 infer 的 audio_path 校验，上传即可推理"""
        from workstation.services.sovits_svc_infer import SoVITSSVCInferer

        inferer = SoVITSSVCInferer()
        assert Path(get_settings().audio_upload.input_dir).resolve() == (
            inferer._allowed_audio_root
        )


class BoundedUpload:
    filename = "stream.wav"
    size = None

    def __init__(self, length, failure=None):
        self.remaining = length
        self.read_sizes = []
        self.bytes_read = 0
        self.failure = failure

    async def read(self, size=-1):
        assert 0 < size <= 1024 * 1024, "upload must use bounded reads"
        self.read_sizes.append(size)
        if self.failure and self.bytes_read:
            raise self.failure
        size = min(size, self.remaining)
        self.remaining -= size
        self.bytes_read += size
        return b"x" * size


@pytest.mark.asyncio
async def test_unknown_size_stream_stops_at_limit(upload_env, monkeypatch):
    _, input_dir = upload_env
    monkeypatch.setattr(get_settings().audio_upload, "max_size_mb", 1)
    upload = BoundedUpload(100 * 1024 * 1024)
    with pytest.raises(HTTPException) as caught:
        await upload_audio(upload)
    assert caught.value.status_code == 400
    assert upload.bytes_read == 1024 * 1024 + 1
    assert _dir_entries(input_dir) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [OSError("read failed"), asyncio.CancelledError()])
async def test_partial_upload_cleanup_on_failure(upload_env, failure):
    _, input_dir = upload_env
    upload = BoundedUpload(2 * 1024 * 1024, failure)
    with pytest.raises(type(failure)):
        await upload_audio(upload)
    assert upload.bytes_read == 1024 * 1024
    assert _dir_entries(input_dir) == []


@pytest.mark.asyncio
async def test_exact_limit_stream_is_published_atomically(upload_env, monkeypatch):
    _, input_dir = upload_env
    monkeypatch.setattr(get_settings().audio_upload, "max_size_mb", 1)
    upload = BoundedUpload(1024 * 1024)
    result = await upload_audio(upload)
    dest = Path(result["audio_path"])
    assert dest.stat().st_size == 1024 * 1024
    assert _dir_entries(input_dir) == [dest.name]


@pytest.mark.asyncio
async def test_active_cancel_scope_closes_before_removing_temporary_file(upload_env):
    _, input_dir = upload_env
    with anyio.CancelScope() as scope:
        class CancelledUpload(BoundedUpload):
            async def read(self, size=-1):
                if self.bytes_read:
                    scope.cancel()
                    await anyio.sleep(0)
                return await super().read(size)

        await upload_audio(CancelledUpload(2 * 1024 * 1024))
        pytest.fail("cancelled upload must not be published")
    assert scope.cancel_called
    assert _dir_entries(input_dir) == []
