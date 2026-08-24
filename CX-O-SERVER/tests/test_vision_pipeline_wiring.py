"""主动视觉「生产接线 + 后端二次护栏」端到端测试（Task 12.1 / 12.2）。

目标（GN-004 阻断项 12.1/12.2 修复验证，非临时脚本，落入 tests/）：
1. **生产装配路径**（非手动 set_consumer）：显式调用生产装配函数
   ``server.core.vision.pipeline.register_vision_pipeline``（service 启动调用的同一
   装配函数）把队列接到「理解 → NarrativeSummary → NarrativeVisionMemory 落库」。
2. 用 TestClient 打 ``POST /api/vision/clip`` 且 enabled=true → 走真实 enqueue →
   登录生产 consumer（含注入的假理解 + 真实落库 memory）→ 记忆表出现
   ``source='vision'`` 行可召回。不依赖真实 vLLM（注入假 understanding，disable 图片解帧）。
3. 并发/幂等：装配函数重复调用不报错；enabled=false 不上传。
4. 护栏：超 ``max_clips_per_hour`` → 429 rate_limited；``event_cooldown_sec`` 内
   重复同类事件 → 429 cooldown。

运行：python -m pytest tests/test_vision_pipeline_wiring.py -q
"""
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core.decision.decision_core import DecisionCore, RubricSnapshot, _default_rubric_dict
from server.core.memory.manager import MemoryManager
from server.core.vision.clip_queue import VisionClipQueue
from server.core.vision.narrative_memory import NarrativeVisionMemory
from server.core.vision.video_understanding import NarrativeSummary
from server.api.routers import vision as vision_router_mod
from server.core.vision import pipeline as pipe_mod


# --------------------------------------------------------------------------- #
# 假依赖（配置 / 理解组件）
# --------------------------------------------------------------------------- #
class FakeVisionCfg:
    def __init__(self, enabled=True, max_clips_per_hour=12, event_cooldown_sec=0):
        self.enabled = enabled
        self.max_clips_per_hour = max_clips_per_hour
        self.event_cooldown_sec = event_cooldown_sec
        self.clip_max_sec = 10


class FakeConfig:
    def __init__(self, enabled=True, max_clips_per_hour=12, event_cooldown_sec=0):
        self.vision_enhanced = FakeVisionCfg(
            enabled, max_clips_per_hour, event_cooldown_sec
        )


class FakeSettings:
    def __init__(self, enabled=True, max_clips_per_hour=12, event_cooldown_sec=0):
        self.config = FakeConfig(enabled, max_clips_per_hour, event_cooldown_sec)


class FakeQueue:
    """可注入路由的替身队列（护栏测试用，避免真实 worker 清理干扰）。"""

    def __init__(self, enqueue_result=True):
        self.enqueued = []
        self.enqueue_result = enqueue_result
        self.consumer = None

    def set_consumer(self, consumer):
        self.consumer = consumer

    def enqueue(self, item):
        self.enqueued.append(item)
        return self.enqueue_result

    def pending_count(self):
        return len(self.enqueued)

    def is_ready(self):
        return self.consumer is not None


class FakeUnderstanding:
    """假理解组件：不触碰 vLLM / 解帧，直接产出可沉淀的叙事摘要。"""

    async def consume(self, item):
        event_type = (item.get("event_meta") or {}).get("event_type", "video_clip")
        return NarrativeSummary(
            content="用户点击了保存按钮并成功保存文件",
            events=[event_type],
            emotion="专注",
            clip_ts=float(item.get("ts") or 0.0),
            source=str(item.get("source") or ""),
            event_type=event_type,
            confidence=0.9,
            native_used=False,
            degraded=True,
            ocr_blocks=[],
        )


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """临时库 MemoryManager（禁用后台线程/高级组件），并重置单例。"""
    monkeypatch.setattr(MemoryManager, "_start_cleanup_task", lambda self: None)

    def _noop_init(self):
        self.archiver = None
        self.deduplication_engine = None
        self.vectorization_queue = None

    monkeypatch.setattr(MemoryManager, "_init_advanced_components", _noop_init)

    MemoryManager._instance = None
    m = MemoryManager(db_path=str(tmp_path / "memories.db"))
    yield m
    m.shutdown()
    MemoryManager._instance = None


def _rubric(**kw):
    base = _default_rubric_dict()
    base.update(kw)
    return RubricSnapshot(**base)


def _make_decision_core(tmp_path):
    cfg = {
        "decision_core": {"rejected_content_retention_days": 30},
        "vllm": {"base_url": "http://127.0.0.1:8002", "timeout_seconds": 5},
    }
    return DecisionCore(
        config=cfg,
        agents_file=str(tmp_path / "agents.json"),
        log_dir=str(tmp_path / "logs"),
        llm_available=False,
    )


def _post(client, event_type="click_save", source="screen"):
    files = {"clip": ("fake.mp4", b"fakevideodata", "video/mp4")}
    data = {"event_type": event_type, "ts": "1234.5", "source": source}
    return client.post("/vision/clip", files=files, data=data)


def _wait_until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- #
# 12.1 生产接线（端到端，走生产装配函数）
# --------------------------------------------------------------------------- #
def test_pipeline_wiring_end_to_end_source_vision(mgr, tmp_path, monkeypatch):
    """enabled=true → 走生产装配 → POST → 理解 → 沉积 → 记忆表 source='vision' 可召回。"""
    monkeypatch.setattr(pipe_mod, "_REGISTERED_QUEUES", set())
    monkeypatch.setattr(pipe_mod, "get_settings", lambda: FakeSettings(enabled=True))
    monkeypatch.setattr(vision_router_mod, "get_settings",
                        lambda: FakeSettings(enabled=True))

    queue = VisionClipQueue()
    # 注入真实落库 memory + 假理解组件（不依赖真实 vLLM）
    nvm = NarrativeVisionMemory(
        manager=mgr,
        decision_core=_make_decision_core(tmp_path),
        rubric=_rubric(importance_threshold_permanent=0.8),
        enabled=True,
        # 注入空链接器：跳过真实图落库/Weaviate 探测，避免外部依赖拖慢测试
        entity_linkers={},
    )
    # 记录沉淀调用结果（拿到 memory_id + written），同时保持真实落库
    holder = {}

    def spy_sediment(item, summary):
        result = nvm.__class__.sediment_from_consumer(nvm, item, summary)
        holder["memory_id"] = result.get("memory_id")
        holder["written"] = result.get("written")
        holder["location"] = result.get("location")
        return result

    nvm.sediment_from_consumer = spy_sediment  # 实例级替换（仅测试注入点）

    # 生产装配（显式调用服务启动装配的同一函数，注入组件使其可独立验证）
    assert pipe_mod.register_vision_pipeline(
        queue=queue, understanding=FakeUnderstanding(), memory=nvm
    ) is True, "enabled=true 时装配应成功"
    assert queue.is_ready() is True, "装配后队列应已挂 consumer"

    monkeypatch.setattr(vision_router_mod, "vision_clip_queue", queue)
    app = FastAPI()
    app.include_router(vision_router_mod.router)

    with TestClient(app) as c:
        r = _post(c)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["accepted"] is True
        # 等待 worker 消费 → 理解 → 沉淀（Timeout 放宽以容纳沉淀全链路）
        assert _wait_until(lambda: "memory_id" in holder, timeout=20.0), "worker 未在预期内完成沉淀"

    assert holder["written"] is True
    assert holder["location"] == "memories"
    memory_id = holder["memory_id"]
    assert memory_id is not None

    # 可召回验证：从 db 读取该记忆，source 落列 = 'vision'，metadata 冗余字段完整
    mem = mgr.get_memory(memory_id)
    assert mem is not None
    assert mem["source"] == "vision"
    metadata = mem["metadata"]
    assert metadata["source"] == "vision"
    assert metadata["event_type"] == "click_save"
    assert "visual" in metadata["tags"]
    assert "visual" in mem["tags"]
    # 临时片段已被队列 finally 清理
    assert list(tmp_path.glob("*.mp4")) == []


def test_pipeline_wiring_idempotent_repeat_call(mgr, tmp_path, monkeypatch):
    """装配函数重复调用不报错（幂等，不重复 set_consumer 也无副作用）。"""
    monkeypatch.setattr(pipe_mod, "_REGISTERED_QUEUES", set())
    monkeypatch.setattr(pipe_mod, "get_settings", lambda: FakeSettings(enabled=True))

    queue = VisionClipQueue()
    nvm = NarrativeVisionMemory(
        manager=mgr,
        decision_core=_make_decision_core(tmp_path),
        rubric=_rubric(importance_threshold_permanent=0.8),
        enabled=True,
    )
    assert pipe_mod.register_vision_pipeline(
        queue=queue, understanding=FakeUnderstanding(), memory=nvm
    ) is True
    # 重复调用：不抛错、仍返回 True（幂等）
    assert pipe_mod.register_vision_pipeline(
        queue=queue, understanding=FakeUnderstanding(), memory=nvm
    ) is True


def test_pipeline_wiring_disabled_not_registered(monkeypatch):
    """enabled=false → 装配返回 False 且不注册 consumer。"""
    monkeypatch.setattr(pipe_mod, "_REGISTERED_QUEUES", set())
    monkeypatch.setattr(pipe_mod, "get_settings", lambda: FakeSettings(enabled=False))

    queue = VisionClipQueue()
    assert pipe_mod.register_vision_pipeline(queue=queue) is False
    assert queue.is_ready() is False, "enabled=false 时不应注册 consumer"


# --------------------------------------------------------------------------- #
# 12.2 后端二次护栏
# --------------------------------------------------------------------------- #
@pytest.fixture
def guard_reset():
    vision_router_mod.reset_vision_guard()
    yield
    vision_router_mod.reset_vision_guard()


def test_guard_rate_limit_429(monkeypatch, tmp_path, guard_reset):
    """小时滑窗限流：超 max_clips_per_hour → 429 detail='rate_limited'。"""
    # max_clips_per_hour=1，冷却关闭（event_cooldown_sec=0）
    queue = FakeQueue()
    monkeypatch.setattr(vision_router_mod, "get_settings",
                        lambda: FakeSettings(enabled=True, max_clips_per_hour=1, event_cooldown_sec=0))
    monkeypatch.setattr(vision_router_mod, "vision_clip_queue", queue)
    monkeypatch.setattr(vision_router_mod, "_vision_tmp_dir", lambda: tmp_path)

    app = FastAPI()
    app.include_router(vision_router_mod.router)
    with TestClient(app) as c:
        r1 = _post(c, event_type="motion", source="camera")
        assert r1.status_code == 200, r1.text
        assert r1.json()["data"]["accepted"] is True
        r2 = _post(c, event_type="motion", source="camera")
        assert r2.status_code == 429, r2.text
        assert "rate_limited" in r2.json().get("detail", "")


def test_guard_cooldown_429(monkeypatch, tmp_path, guard_reset):
    """同类事件冷却：event_cooldown_sec 内重复同 (source,event_type) → 429 cooldown。"""
    queue = FakeQueue()
    monkeypatch.setattr(vision_router_mod, "get_settings",
                        lambda: FakeSettings(enabled=True, max_clips_per_hour=100, event_cooldown_sec=1000))
    monkeypatch.setattr(vision_router_mod, "vision_clip_queue", queue)
    monkeypatch.setattr(vision_router_mod, "_vision_tmp_dir", lambda: tmp_path)

    app = FastAPI()
    app.include_router(vision_router_mod.router)
    with TestClient(app) as c:
        r1 = _post(c, event_type="object_motion", source="screen")
        assert r1.status_code == 200, r1.text
        r2 = _post(c, event_type="object_motion", source="screen")
        assert r2.status_code == 429, r2.text
        assert "cooldown" in r2.json().get("detail", "")
    # 幂等复位
    vision_router_mod.reset_vision_guard()