"""哨兵集群 ref_audio 单元接入（B1/B2/B3）测试。

覆盖：
- UNIT_REGISTRY 含 ref_audio 且策略 incremental
- manager 按 config.sync_units 白名单过滤单元（B1）
- 快照 provider 打包 / 恢复 roundtrip（B2）
- ref_audio_store emit hook → replicator.apply_event 重放绑定/资产元数据（B3）

运行：python -m pytest tests/test_cluster_ref_audio.py -q
"""
import io
import wave
from types import SimpleNamespace

import pytest

from server import ref_audio_store
from server.core.cluster.manager import SentinelCluster
from server.core.cluster.replicator import StateReplicator
from server.core.cluster.units import UNIT_REGISTRY


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
def _cleanup_hook():
    yield
    ref_audio_store.set_emit_hook(None)
    ref_audio_store._set_assets_dir(None)


def _make_config(sync_units=None, enabled=True, peers=()):
    if sync_units is None:
        sync_units = ["memory", "config", "ref_audio"]
    return SimpleNamespace(
        enabled=enabled,
        node_name="ra-node",
        cluster_secret="sekrit",
        peers=list(peers),
        role="standby",
        peer_heartbeat_interval_sec=1,
        peer_timeout_sec=5,
        miss_threshold=3,
        snapshot_interval_sec=60,
        sync_units=list(sync_units),
        transport="https",
        bind="10.0.0.9",
        witness=SimpleNamespace(endpoint="", secret=""),
    )


def _file_asset(dirpath, name="ref.wav", **kw):
    path = dirpath / name
    path.write_bytes(_wav_bytes(**kw))
    return ref_audio_store.register_from_file(str(path))


# ================================================================ B2.1 units
class TestUnitsRegistry:
    def test_registry_contains_ref_audio(self):
        assert "ref_audio" in UNIT_REGISTRY
        assert UNIT_REGISTRY["ref_audio"] == "incremental"


# ================================================================ B1 whitelist
class TestSyncUnitsWhitelist:
    @pytest.mark.asyncio
    async def test_manager_filters_units_by_sync_units(self):
        cfg = _make_config(sync_units=["memory", "config", "ref_audio"])
        cl = SentinelCluster(config=cfg)
        await cl.start()
        try:
            active = set(cl.replicator._units.keys())
            assert active == {"memory", "config", "ref_audio"}
            assert "vector" not in active
            assert "graph" not in active
        finally:
            await cl.shutdown()

    @pytest.mark.asyncio
    async def test_empty_sync_units_falls_back_to_full_registry(self):
        # 与既有 test_cluster_manager 一致：sync_units 为空 → 全量 UNIT_REGISTRY
        raw = dict(ref_audio_store.__dict__)
        _ = raw  # 保持引用
        cfg = _make_config(sync_units=[])
        cl = SentinelCluster(config=cfg)
        await cl.start()
        try:
            assert set(cl.replicator._units.keys()) == set(UNIT_REGISTRY.keys())
        finally:
            await cl.shutdown()


# ================================================================ B2 snapshot
class TestRefAudioSnapshot:
    def test_build_restore_roundtrip(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        ref_audio_store._set_assets_dir(src)
        asset = _file_asset(src)
        ref_audio_store.set_for_agent("agent-x", asset.id, tts_voice="v1")

        blob = ref_audio_store.build_snapshot()
        assert blob["version"] == 1
        assert blob["checksum"]
        assert len(blob["assets"]) == 1
        assert blob["bindings"]["agent-x"]["asset_id"] == asset.id
        assert blob["audio"][asset.id]  # base64 非空

        dst = tmp_path / "dst"
        dst.mkdir()
        ref_audio_store._set_assets_dir(dst)
        ref_audio_store.restore_snapshot(blob)

        got = ref_audio_store.get(asset.id)
        assert got is not None
        assert got.status != "deleted"
        assert ref_audio_store.get_for_agent("agent-x")["asset_id"] == asset.id
        path = ref_audio_store._audio_path_for(asset.id, "wav")
        assert path.exists()
        assert path.read_bytes().startswith(b"RIFF")

    def test_snapshot_provider_via_replicator_writes_to_disk(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        ref_audio_store._set_assets_dir(src)
        asset = _file_asset(src)

        rep = StateReplicator(
            config=SimpleNamespace(peers=[], snapshot_interval_sec=60),
            node_id="me",
            units=UNIT_REGISTRY,
        )
        rep.register_backup_provider("ref_audio", lambda unit: ref_audio_store.build_snapshot())
        # 直接采集 + 落盘，验证 snapshot 写盘（不走后台循环）
        blob = ref_audio_store.build_snapshot()
        rep._write_snapshot("ref_audio", blob)
        target = rep._snapshot_dir / "ref_audio.json"
        assert target.exists()
        import json
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["version"] == 1
        assert any(a["id"] == asset.id for a in saved["assets"])


# ================================================================ B3 emit→apply
class TestEmitApplyReplay:
    def _real_replicator(self):
        return StateReplicator(
            config=SimpleNamespace(peers=[], snapshot_interval_sec=60),
            node_id="peer",
            units=UNIT_REGISTRY,
        )

    @pytest.mark.asyncio
    async def test_replay_binding_and_asset_metadata(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        ref_audio_store._set_assets_dir(src)
        events = []
        ref_audio_store.set_emit_hook(lambda unit, op, payload: events.append((op, payload)))
        asset = _file_asset(src)  # 注册 → 触发 asset_register
        ref_audio_store.set_for_agent("agent-x", asset.id, tts_voice="v1")  # 触发 binding_set
        ref_audio_store.set_emit_hook(None)

        assert any(op == "asset_register" for op, _ in events)
        assert any(op == "binding_set" for op, _ in events)

        # 目标：全新资产目录，重放事件后应恢复资产元数据 + 绑定
        dst = tmp_path / "dst"
        dst.mkdir()
        ref_audio_store._set_assets_dir(dst)
        rep = self._real_replicator()
        seq = 0
        for op, payload in events:
            seq += 1
            applied = await rep.apply_event(
                {"unit": "ref_audio", "seq": seq, "op": op, "payload": payload}
            )
            assert applied is True

        assert ref_audio_store.get(asset.id) is not None
        assert ref_audio_store.get_for_agent("agent-x")["asset_id"] == asset.id
        assert ref_audio_store.get_for_agent("agent-x")["tts_voice"] == "v1"
        assert rep.last_applied().get("ref_audio") == seq

    @pytest.mark.asyncio
    async def test_replay_binding_clear(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        ref_audio_store._set_assets_dir(src)
        asset = _file_asset(src)
        events = []
        ref_audio_store.set_emit_hook(lambda unit, op, payload: events.append((op, payload)))
        ref_audio_store.set_for_agent("agent-x", asset.id)
        ref_audio_store.clear_for_agent("agent-x")
        ref_audio_store.set_emit_hook(None)

        dst = tmp_path / "dst"
        dst.mkdir()
        ref_audio_store._set_assets_dir(dst)
        rep = self._real_replicator()
        seq = 0
        for op, payload in events:
            seq += 1
            await rep.apply_event(
                {"unit": "ref_audio", "seq": seq, "op": op, "payload": payload}
            )
        # 重放 asset_register（绑定于 set_for_agent 前），最终 binding 被清除
        assert ref_audio_store.get_for_agent("agent-x") is None

    @pytest.mark.asyncio
    async def test_apply_event_idempotent_for_ref_audio(self, tmp_path):
        dst = tmp_path / "dst"
        dst.mkdir()
        ref_audio_store._set_assets_dir(dst)
        rep = self._real_replicator()
        ev = {"unit": "ref_audio", "seq": 3, "op": "binding_clear", "payload": {"agent_id": "agent-x"}}
        assert await rep.apply_event(ev) is True
        assert await rep.apply_event(ev) is False  # 同 seq 重放幂等跳过
        assert rep.last_applied().get("ref_audio") == 3