"""per-agent 参考音频绑定（A2/A3）单测。

覆盖：
- set/get/clear per-agent 绑定（真源落盘 agent_bindings.json，与 current 解耦）
- 资产不存在时 set_for_agent 拒绝（RefAudioNotFoundError）
- 被绑定的资产删除拒绝（AssetBoundError）
- _build_ref_ids fallback 顺序：显式 > 按 agent > 全局 current

运行：python -m pytest tests/test_ref_audio_agent.py -q
"""
import io
import wave

import pytest

from server import ref_audio_store
from server.qwen3_tts_provider import RefAudioNotFoundError
from server.ref_audio_store import AssetBoundError, register_from_file
from server.services.tts_service import TTSService


def _wav_bytes(sample_rate: int = 24000, channels: int = 1, duration: float = 3.0) -> bytes:
    buf = io.BytesIO()
    nframes = int(sample_rate * duration)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * nframes)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    ref_audio_store._set_assets_dir(tmp_path)
    ref_audio_store.set_emit_hook(None)
    yield tmp_path
    ref_audio_store._set_assets_dir(None)
    ref_audio_store.set_emit_hook(None)


def _file_asset(path, name="ref.wav", **kw):
    src = path / name
    src.write_bytes(_wav_bytes(**kw))
    return register_from_file(str(src))


# ================================================================ 绑定 CRUD
class TestAgentBinding:
    def test_set_and_get(self, tmp_path):
        asset = _file_asset(tmp_path)
        b = ref_audio_store.set_for_agent("agent-x", asset.id, tts_voice="v1")
        assert b["asset_id"] == asset.id
        assert b["tts_voice"] == "v1"
        got = ref_audio_store.get_for_agent("agent-x")
        assert got["asset_id"] == asset.id

    def test_set_without_voice(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.set_for_agent("agent-x", asset.id)
        assert ref_audio_store.get_for_agent("agent-x")["tts_voice"] is None

    def test_unbound_returns_none(self, tmp_path):
        assert ref_audio_store.get_for_agent("ghost") is None

    def test_clear(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.set_for_agent("agent-x", asset.id)
        ref_audio_store.clear_for_agent("agent-x")
        assert ref_audio_store.get_for_agent("agent-x") is None

    def test_list_bindings(self, tmp_path):
        a = _file_asset(tmp_path, "a.wav")
        b = _file_asset(tmp_path, "b.wav", sample_rate=16000, duration=2.0)
        ref_audio_store.set_for_agent("agent-a", a.id)
        ref_audio_store.set_for_agent("agent-b", b.id)
        bindings = ref_audio_store.list_bindings()
        assert set(bindings.keys()) == {"agent-a", "agent-b"}

    def test_binding_persisted_across_reload(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.set_for_agent("agent-x", asset.id, tts_voice="v9")
        # 重新读取（同资产目录）仍可读
        got = ref_audio_store.get_for_agent("agent-x")
        assert got["asset_id"] == asset.id
        assert got["tts_voice"] == "v9"


class TestAgentBindingValidation:
    def test_set_missing_asset_raises(self, tmp_path):
        with pytest.raises(RefAudioNotFoundError):
            ref_audio_store.set_for_agent("agent-x", "ref_nonexistent_000")

    def test_set_deleted_asset_raises(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.delete(asset.id)  # 未绑定可删
        with pytest.raises(RefAudioNotFoundError):
            ref_audio_store.set_for_agent("agent-x", asset.id)


# ================================================================ 删除保护
class TestBoundAssetDeleteProtection:
    def test_delete_bound_asset_rejected(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.set_for_agent("agent-x", asset.id)
        with pytest.raises(AssetBoundError):
            ref_audio_store.delete(asset.id)

    def test_asset_used_by_any_agent(self, tmp_path):
        a = _file_asset(tmp_path, "a.wav")
        b = _file_asset(tmp_path, "b.wav", sample_rate=16000, duration=2.0)
        ref_audio_store.set_for_agent("agent-x", a.id)
        assert ref_audio_store.asset_used_by_any_agent(a.id) is True
        assert ref_audio_store.asset_used_by_any_agent(b.id) is False

    def test_unbind_then_delete_ok(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.set_for_agent("agent-x", asset.id)
        ref_audio_store.clear_for_agent("agent-x")
        ref_audio_store.delete(asset.id)  # 解绑后可删
        assert ref_audio_store.get(asset.id).is_deleted

    def test_unbound_different_agent_deletable(self, tmp_path):
        a = _file_asset(tmp_path, "a.wav")
        b = _file_asset(tmp_path, "b.wav", sample_rate=16000, duration=2.0)
        ref_audio_store.set_for_agent("agent-x", a.id)
        ref_audio_store.delete(b.id)  # 未绑定 b 可删，不影响 a


# ================================================================ fallback 顺序
class TestBuildRefIdsFallback:
    def _svc(self):
        return TTSService(qwen3_enabled=True, qwen3_provider=None)

    def test_explicit_refs_win_over_agent_binding(self, tmp_path):
        asset = _file_asset(tmp_path)
        ref_audio_store.set_for_agent("agent-x", asset.id, tts_voice="v1")
        svc = self._svc()
        assert svc._build_ref_ids({"agent_id": "agent-x", "refs": ["ref_explicit"]}) == ["ref_explicit"]

    def test_agent_binding_wins_over_current(self, tmp_path):
        agent_asset = _file_asset(tmp_path, "a.wav")
        current_asset = _file_asset(tmp_path, "b.wav", sample_rate=16000, duration=2.0)
        ref_audio_store.set_for_agent("agent-x", agent_asset.id)
        ref_audio_store.set_current(current_asset.id)
        svc = self._svc()
        assert svc._build_ref_ids({"agent_id": "agent-x"}) == [agent_asset.id]

    def test_no_binding_falls_back_to_current(self, tmp_path):
        current_asset = _file_asset(tmp_path, "b.wav", sample_rate=16000, duration=2.0)
        ref_audio_store.set_current(current_asset.id)
        svc = self._svc()
        assert svc._build_ref_ids({"agent_id": "agent-no-binding"}) == [current_asset.id]

    def test_no_agent_no_current_returns_empty(self, tmp_path):
        _file_asset(tmp_path, "a.wav")  # 有资产但不设 current/绑定
        svc = self._svc()
        assert svc._build_ref_ids({}) == []

    def test_backward_compatible_without_agent_id(self, tmp_path):
        current_asset = _file_asset(tmp_path, "b.wav", sample_rate=16000, duration=2.0)
        ref_audio_store.set_current(current_asset.id)
        svc = self._svc()
        # 旧调用（不带 agent_id）行为不变
        assert svc._build_ref_ids({}) == [current_asset.id]
