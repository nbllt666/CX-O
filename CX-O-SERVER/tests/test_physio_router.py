"""CX-O-Dream 生理信号 REST 路由测试：/api/physio/* 端点。

覆盖：
① GET  /physio/status  未装配/未启用返回 {"status":"disabled"}（200 不抛错）；启用返回状态快照
② POST /physio/hr      未启用返回 {"status":"disabled"}；启用调用 estimator.ingest 返回 {hr_sleep_confidence}
③ POST /physio/state   上报 S1/S6 provider 输入，返回 {"ok":true}；runtime 缺失/无能力时仍 ok
④ GET  /physio/sleep   未启用 disabled；启用返回 sleep_sensor.snapshot()；无 sleep_sensor 返回默认清醒态
⑤ GET  /physio/devices 未启用返回 {"devices":[]}；启用返回 {name, fingerprint(脱敏前 8+****), id(真实指纹仅供 forget)}
⑥ POST /physio/devices/{id}/forget  解除配对返回 ok；不存在 404；脱敏指纹 forget 必 404（Task 6 回归）
⑦ GET  /physio/config  返回 physio 子节配置（不依赖 runtime）
⑧ PUT  /physio/config  合法更新持久化 + GET 往返 + set_config 通知 runtime；store_raw_hr=true / 非法字段 422
⑨ POST /physio/clear   调用 store.clear() 返回 {"ok":true,"cleared":true}；runtime 缺失返回 cleared:false

运行：python -m pytest tests/test_physio_router.py -q
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import physio as physio_router
from server.autonomy.dream.config import DreamConfig, PhysioConfig


# ================================================================ 假 runtime
class FakeEstimator:
    def __init__(self, confidence=0.0):
        self.confidence = confidence
        self.ingested = []

    def ingest(self, bpm, ts):
        self.ingested.append((bpm, ts))
        self.confidence = 0.8
        return self.confidence

    def get_state(self):
        return {
            "base_hr": 70.0,
            "hr_sleep_confidence": self.confidence,
            "window_size": len(self.ingested),
            "updated_at": "2026-08-23T01:00:00",
        }


class FakeStore:
    def __init__(self):
        self.cleared = 0
        self._state = {"base_hr": 70.0, "device_fingerprint": "fp-abcdef1234567890"}

    def clear(self):
        self.cleared += 1
        self._state = {}

    def get(self, key, default=None):
        return self._state.get(key, default)


class FakeSleepSensor:
    def snapshot(self):
        return {
            "state": "DROWSY",
            "confidence": 0.5,
            "signals": [
                {"key": "S1", "name": "输入静默", "value": 0.8, "weight": 0.15, "available": True},
                {"key": "S9", "name": "心率", "value": 0.9, "weight": 0.4, "available": True},
            ],
        }


class FakeRuntime:
    def __init__(self, enabled=True):
        self._enabled = enabled
        self.estimator = FakeEstimator()
        self.store = FakeStore()
        self.sleep_sensor = FakeSleepSensor()
        self.devices = [
            {"fingerprint": "fp-abcdef1234567890", "device_name": "Mi Band 8"},
            {"fingerprint": "fp-1111222233334444", "device_name": "Huawei Band"},
        ]
        self._config = DreamConfig(
            enabled=True,
            physio=PhysioConfig(
                enabled=enabled,
                device_fingerprint="fp-abcdef1234567890",
                device_name_hint="Mi Band 8",
            ),
        )
        self.state_updates = []
        self.forgotten = []
        self.applied_configs = []

    def is_enabled(self):
        return self._enabled

    def get_config(self):
        return self._config

    def set_config(self, cfg):
        self._config = cfg
        self.applied_configs.append(cfg)

    def get_devices(self):
        return list(self.devices)

    def forget_device(self, fp):
        for i, device in enumerate(self.devices):
            if device["fingerprint"] == fp:
                self.devices.pop(i)
                self.forgotten.append(fp)
                return True
        return False

    def update_system_state(self, system_idle_sec=None, user_active=None):
        self.state_updates.append(
            {"system_idle_sec": system_idle_sec, "user_active": user_active}
        )


# ================================================================ fixtures
@pytest.fixture(autouse=True)
def _reset_router_globals():
    """每个测试前后重置路由模块全局注入，避免跨测试污染。"""
    physio_router.set_physio_runtime(None)
    yield
    physio_router.set_physio_runtime(None)


@pytest.fixture
def client():
    """构造仅挂载 physio 路由的 FastAPI 测试客户端（/api 前缀）。"""
    app = FastAPI()
    app.include_router(physio_router.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def runtime():
    return FakeRuntime()


@pytest.fixture
def disabled_runtime():
    return FakeRuntime(enabled=False)


def _patch_config_io(monkeypatch, tmp_path):
    """将路由的 load_config/save_config 指向临时目录，避免污染真实 data/dream_config.json。"""
    cfg_file = tmp_path / "dream_config.json"

    def fake_load(store_path=""):
        if not cfg_file.exists():
            return DreamConfig()
        return DreamConfig.model_validate(json.loads(cfg_file.read_text(encoding="utf-8")))

    def fake_save(config, store_path=""):
        cfg_file.write_text(
            json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(cfg_file)

    monkeypatch.setattr(physio_router, "load_config", fake_load)
    monkeypatch.setattr(physio_router, "save_config", fake_save)


# ================================================================ ① GET /physio/status
class TestStatus:
    def test_status_disabled_when_no_runtime(self, client):
        r = client.get("/api/physio/status")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_status_disabled_when_runtime_disabled(self, client, disabled_runtime):
        physio_router.set_physio_runtime(disabled_runtime)
        r = client.get("/api/physio/status")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_status_returns_snapshot(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.get("/api/physio/status")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["status"] == "active"
        assert body["collector"]["backend"] == "noble"
        assert body["estimator"]["hr_sleep_confidence"] == 0.0


# ================================================================ ② POST /physio/hr
class TestHr:
    def test_hr_disabled_when_no_runtime(self, client):
        r = client.post("/api/physio/hr", json={"bpm": 60, "ts": "2026-08-23T01:00:00"})
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_hr_disabled_when_runtime_disabled(self, client, disabled_runtime):
        physio_router.set_physio_runtime(disabled_runtime)
        r = client.post("/api/physio/hr", json={"bpm": 60, "ts": "2026-08-23T01:00:00"})
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_hr_ingests_sample_and_returns_confidence(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.post(
            "/api/physio/hr",
            json={"bpm": 58.5, "ts": "2026-08-23T01:00:00", "device_fingerprint": "fp-abcdef1234567890"},
        )
        assert r.status_code == 200
        assert r.json() == {"hr_sleep_confidence": 0.8}
        assert len(runtime.estimator.ingested) == 1
        assert runtime.estimator.ingested[0][0] == 58.5


# ================================================================ ③ POST /physio/state
class TestState:
    def test_state_updates_runtime(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.post(
            "/api/physio/state", json={"system_idle_sec": 300.0, "user_active": False}
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert runtime.state_updates == [
            {"system_idle_sec": 300.0, "user_active": False}
        ]

    def test_state_ok_when_runtime_missing(self, client):
        r = client.post("/api/physio/state", json={"system_idle_sec": 300.0, "user_active": False})
        assert r.status_code == 200
        assert r.json() == {"ok": True}


# ================================================================ ④ GET /physio/sleep
class TestSleep:
    def test_sleep_disabled_when_no_runtime(self, client):
        r = client.get("/api/physio/sleep")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_sleep_returns_sensor_snapshot(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.get("/api/physio/sleep")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "DROWSY"
        assert body["confidence"] == 0.5
        assert len(body["signals"]) == 2
        assert body["signals"][0]["key"] == "S1"

    def test_sleep_default_state_when_no_sensor(self, client, runtime):
        runtime.sleep_sensor = None
        physio_router.set_physio_runtime(runtime)
        r = client.get("/api/physio/sleep")
        assert r.status_code == 200
        assert r.json() == {"state": "AWAKE", "signals": [], "confidence": 0.0}


# ================================================================ ⑤ GET /physio/devices
class TestDevices:
    def test_devices_empty_when_no_runtime(self, client):
        r = client.get("/api/physio/devices")
        assert r.status_code == 200
        assert r.json() == {"devices": []}

    def test_devices_masked(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.get("/api/physio/devices")
        assert r.status_code == 200
        body = r.json()
        assert len(body["devices"]) == 2
        d0 = body["devices"][0]
        # 展示字段：name + 脱敏 fingerprint（前 8 + ****），不得泄露完整指纹
        assert d0["name"] == "Mi Band 8"
        assert d0["fingerprint"] == "fp-abcde****"
        assert d0["fingerprint"].endswith("****")
        assert "abcdef1234567890" not in d0["fingerprint"]
        # id 为真实指纹（仅供 forget 使用），不得脱敏
        assert d0["id"] == "fp-abcdef1234567890"


# ================================================================ ⑥ POST /physio/devices/{id}/forget
class TestForget:
    def test_forget_removes_device(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.post("/api/physio/devices/fp-abcdef1234567890/forget")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "fingerprint": "fp-abcdef1234567890"}
        assert "fp-abcdef1234567890" in runtime.forgotten
        assert len(runtime.devices) == 1

    def test_forget_404_when_not_paired(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.post("/api/physio/devices/fp-unknown/forget")
        assert r.status_code == 404

    def test_forget_by_masked_fingerprint_404(self, client, runtime):
        """Task 6 回归：GET /devices 返回的脱敏 fingerprint 不可用于 forget（必 404）。"""
        physio_router.set_physio_runtime(runtime)
        r = client.get("/api/physio/devices")
        masked = r.json()["devices"][0]["fingerprint"]
        assert masked.endswith("****")
        r2 = client.post(f"/api/physio/devices/{masked}/forget")
        assert r2.status_code == 404
        assert runtime.forgotten == []

    def test_forget_by_devices_id(self, client, runtime):
        """Task 6 修复：GET /devices 返回真实指纹 id，按 id forget 成功（重启后亦可用）。"""
        physio_router.set_physio_runtime(runtime)
        r = client.get("/api/physio/devices")
        device_id = r.json()["devices"][0]["id"]
        assert device_id == "fp-abcdef1234567890"
        r2 = client.post(f"/api/physio/devices/{device_id}/forget")
        assert r2.status_code == 200
        assert device_id in runtime.forgotten


# ================================================================ ⑦⑧ GET/PUT /physio/config
class TestConfig:
    def test_get_config_returns_defaults(self, client):
        r = client.get("/api/physio/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["backend"] == "noble"
        assert body["device_fingerprint"] is None
        assert body["store_raw_hr"] is False

    def test_put_config_valid_update_persists_and_roundtrip(self, client, monkeypatch, tmp_path, runtime):
        _patch_config_io(monkeypatch, tmp_path)
        physio_router.set_physio_runtime(runtime)
        r = client.put(
            "/api/physio/config",
            json={"enabled": True, "device_name_hint": "Mi Band 8", "base_drop_ratio": 0.85},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["device_name_hint"] == "Mi Band 8"
        assert body["base_drop_ratio"] == 0.85
        # 未提交字段保留默认（深度合并 + 自动补齐）
        assert body["scan_timeout_sec"] == 15
        assert body["store_raw_hr"] is False
        # runtime.set_config 已应用（enabled 变更生效）
        assert len(runtime.applied_configs) == 1
        # GET 往返
        r2 = client.get("/api/physio/config")
        assert r2.status_code == 200
        assert r2.json()["enabled"] is True

    def test_put_config_store_raw_hr_true_422(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
        r = client.put("/api/physio/config", json={"store_raw_hr": True})
        assert r.status_code == 422

    def test_put_config_invalid_field_422(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
        r = client.put("/api/physio/config", json={"unknown_field": 1})
        assert r.status_code == 422

    def test_put_config_physio_wrapped_form(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
        r = client.put("/api/physio/config", json={"physio": {"enabled": True}})
        assert r.status_code == 200
        assert r.json()["enabled"] is True


# ================================================================ ⑨ POST /physio/clear
class TestClear:
    def test_clear_clears_store(self, client, runtime):
        physio_router.set_physio_runtime(runtime)
        r = client.post("/api/physio/clear")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "cleared": True}
        assert runtime.store.cleared == 1
        assert runtime.store._state == {}

    def test_clear_ok_false_when_no_runtime(self, client):
        r = client.post("/api/physio/clear")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "cleared": False}
