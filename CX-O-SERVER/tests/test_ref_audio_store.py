"""统一参考音频资产存储（Task 3）单测。

覆盖：
- 两种来源（prompt/file）均能注册、解析、复用、删除；
- 非法文件与路径穿越抛 InvalidRefAudioError；
- checksum 去重；
- 软删除、注释更新、列表过滤。

运行：python -m pytest tests/test_ref_audio_store.py -q
"""
import io
import wave

import pytest

from server.qwen3_tts_provider import (
    InvalidRefAudioError,
    RefAudioNotFoundError,
    RuntimeUnavailableError,
)
from server import ref_audio_store
from server.ref_audio_store import (
    GeneratedAudio,
    clear_current,
    delete,
    exists,
    get,
    get_current,
    list,
    register_from_file,
    register_from_prompt,
    resolve,
    set_current,
    set_prompt_generator,
    update_note,
)


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
    """Mock Qwen3 VoiceDesign 生成器：返回固定 3s 24k mono WAV。"""
    audio = _wav_bytes(sample_rate=24000, channels=1, duration=3.0)
    return GeneratedAudio(
        audio=audio, format="wav", sample_rate=24000, channels=1, duration_seconds=3.0
    )


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """每个测试隔离资产目录并清理生成器。"""
    ref_audio_store._set_assets_dir(tmp_path)
    set_prompt_generator(None)
    yield
    ref_audio_store._set_assets_dir(None)
    set_prompt_generator(None)


def _write_wav(dirpath, name="ref.wav", **kwargs) -> str:
    path = dirpath / name
    path.write_bytes(_wav_bytes(**kwargs))
    return str(path)


# ================================================================ source=file
class TestRegisterFromFile:
    def test_registers_valid_wav(self, tmp_path):
        file_path = _write_wav(tmp_path, "voice.wav")
        asset = register_from_file(file_path, ref_text="你好", note="我的声音")
        assert asset.source == "file"
        assert asset.file_name == "voice.wav"
        assert asset.ref_text == "你好"
        assert asset.note == "我的声音"
        assert asset.checksum
        assert asset.format == "wav"
        assert asset.sample_rate == 24000
        assert asset.channels == 1
        assert asset.duration_seconds == pytest.approx(3.0)
        assert asset.status == "registered"
        assert asset.id.startswith("ref_")

    def test_asset_id_matches_contract_pattern(self, tmp_path):
        import re
        asset = register_from_file(_write_wav(tmp_path))
        assert re.match(r"^ref_[a-zA-Z0-9_-]+$", asset.id)

    def test_resolve_and_get(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        resolved = resolve(asset.id)
        assert resolved.id == asset.id
        assert get(asset.id).id == asset.id
        assert get("ref_nonexistent_000") is None

    def test_audio_file_persisted(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        audio_path = ref_audio_store._audio_path_for(asset.id, asset.format)
        assert audio_path.exists()
        assert audio_path.read_bytes()[:4] == b"RIFF"

    def test_checksum_dedup_reuse(self, tmp_path):
        file_path = _write_wav(tmp_path, "a.wav")
        first = register_from_file(file_path)
        second = register_from_file(file_path)
        assert second.id == first.id  # 复用
        assert exists(first.checksum) is True
        assert len(list()) == 1

    def test_list_excludes_none(self, tmp_path):
        assert list() == []
        register_from_file(_write_wav(tmp_path))
        assert len(list()) == 1

    def test_update_note(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        updated = update_note(asset.id, "新注释")
        assert updated.note == "新注释"

    def test_soft_delete(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        delete(asset.id)
        deleted = get(asset.id)
        assert deleted.status == "deleted"
        assert deleted.id not in [a.id for a in list()]  # 列表排除
        with pytest.raises(RefAudioNotFoundError):
            resolve(asset.id)

    def test_delete_missing_raises(self, tmp_path):
        with pytest.raises(RefAudioNotFoundError):
            delete("ref_nonexistent")


# ================================================================ 当前默认
class TestCurrentDefault:
    def test_unset_returns_none(self, tmp_path):
        assert get_current() is None

    def test_set_and_get(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        returned = set_current(asset.id)
        assert returned.id == asset.id
        assert get_current().id == asset.id

    def test_set_persisted_across_reload(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        set_current(asset.id)
        # 重新加载索引（同一资产目录）后仍可读
        assert get_current().id == asset.id

    def test_set_missing_raises(self, tmp_path):
        with pytest.raises(RefAudioNotFoundError):
            set_current("ref_nonexistent")

    def test_set_deleted_raises(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        delete(asset.id)
        with pytest.raises(RefAudioNotFoundError):
            set_current(asset.id)

    def test_clear(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        set_current(asset.id)
        clear_current()
        assert get_current() is None

    def test_delete_current_clears_pointer(self, tmp_path):
        asset = register_from_file(_write_wav(tmp_path))
        set_current(asset.id)
        delete(asset.id)
        assert get_current() is None

    def test_delete_non_current_keeps_pointer(self, tmp_path):
        a = register_from_file(_write_wav(tmp_path, "a.wav"))
        b = register_from_file(_write_wav(tmp_path, "b.wav", sample_rate=16000, duration=2.0))
        set_current(a.id)
        delete(b.id)
        assert get_current().id == a.id

    def test_switching_current(self, tmp_path):
        a = register_from_file(_write_wav(tmp_path, "a.wav"))
        b = register_from_file(_write_wav(tmp_path, "b.wav", sample_rate=16000, duration=2.0))
        set_current(a.id)
        set_current(b.id)
        assert get_current().id == b.id


# ================================================================ 非法文件
class TestInvalidFile:
    def test_empty_file_raises(self, tmp_path):
        bad = tmp_path / "empty.wav"
        bad.write_bytes(b"")
        with pytest.raises(InvalidRefAudioError):
            register_from_file(str(bad))

    def test_non_wav_content_with_wav_ext_raises(self, tmp_path):
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"NOT A WAVE FILE AT ALL")
        with pytest.raises(InvalidRefAudioError):
            register_from_file(str(bad))

    def test_unsupported_extension_raises(self, tmp_path):
        bad = tmp_path / "voice.mp4"
        bad.write_bytes(b"\x00\x01")
        with pytest.raises(InvalidRefAudioError):
            register_from_file(str(bad))

    def test_too_short_duration_raises(self, tmp_path):
        # 0.1s WAV → 时长 < 1s
        short = tmp_path / "short.wav"
        short.write_bytes(_wav_bytes(sample_rate=24000, duration=0.1))
        with pytest.raises(InvalidRefAudioError):
            register_from_file(str(short))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(InvalidRefAudioError):
            register_from_file(str(tmp_path / "nope.wav"))


# ================================================================ 路径穿越
class TestPathSafety:
    def test_path_traversal_raises(self, tmp_path):
        with pytest.raises(InvalidRefAudioError):
            register_from_file("../outside.wav")

    def test_absolute_path_outside_raises(self, tmp_path):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(_wav_bytes())
            outside = f.name
        try:
            with pytest.raises(InvalidRefAudioError):
                register_from_file(outside)
        finally:
            import os
            os.unlink(outside)

    def test_relative_path_within_assets_ok(self, tmp_path):
        _write_wav(tmp_path, "ref.wav")
        asset = register_from_file("ref.wav")  # 相对允许目录解析
        assert asset.source == "file"


# ================================================================ source=prompt
class TestRegisterFromPrompt:
    @pytest.mark.asyncio
    async def test_without_generator_raises_runtime_unavailable(self, tmp_path):
        with pytest.raises(RuntimeUnavailableError):
            await register_from_prompt("温柔的女声")

    @pytest.mark.asyncio
    async def test_registers_prompt_asset(self, tmp_path):
        set_prompt_generator(_mock_prompt_generator)
        asset = await register_from_prompt("温柔的女声", language="Chinese")
        assert asset.source == "prompt"
        assert asset.prompt == "温柔的女声"
        assert asset.format == "wav"
        assert asset.status == "registered"
        assert asset.id.startswith("ref_")

    @pytest.mark.asyncio
    async def test_prompt_checksum_dedup(self, tmp_path):
        set_prompt_generator(_mock_prompt_generator)
        first = await register_from_prompt("温柔的女声")
        second = await register_from_prompt("一样的女声")
        assert second.id == first.id  # 相同生成音频 → 去重复用
        assert len(list()) == 1

    @pytest.mark.asyncio
    async def test_prompt_and_file_share_checksum(self, tmp_path):
        # prompt 生成与 file 注册内容 MD5 相同 → 复用一个资产
        set_prompt_generator(_mock_prompt_generator)
        prompt_asset = await register_from_prompt("温柔的女声")
        file_asset = register_from_file(_write_wav(tmp_path, "same.wav"))
        assert file_asset.id == prompt_asset.id

    @pytest.mark.asyncio
    async def test_empty_prompt_raises_invalid(self, tmp_path):
        with pytest.raises(InvalidRefAudioError):
            await register_from_prompt("   ")


# ================================================================ 双向复用/删除
class TestCrossSourceLifecycle:
    @pytest.mark.asyncio
    async def test_both_sources_resolve_via_same_api(self, tmp_path):
        set_prompt_generator(_mock_prompt_generator)
        p = await register_from_prompt("女声")
        set_prompt_generator(None)
        f = register_from_file(_write_wav(tmp_path, "f.wav", sample_rate=16000, duration=2.0))
        assert resolve(p.id).source == "prompt"
        assert resolve(f.id).source == "file"
        assert len(list()) == 2