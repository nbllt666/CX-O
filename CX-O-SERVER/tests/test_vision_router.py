"""server.api.routers.vision 路由 + server.core.vision.clip_queue 队列测试。

覆盖（HEAD 基线 12 例）：
- 路由护栏：enabled=False 已忽略且不排队不落盘；source/ts/event_type 非法 4xx；文件过大 413。
- 路由收取合法片段：返回 accepted 并提交队列（含 pending）；真实队列端到端临时文件最终清理。
- 队列 worker：consumer 抛出异常时文件仍被清洁、worker 不崩溃并继续处理后续条目。
- 队列惰性启动安全失败（无运行中事件循环时 enqueue 返回 False）。

R9 合并并入（第九轮 6 例）——频率护栏记账回滚：
``_guard_check`` 在 enqueue **之前**写小时滑窗（_RATE_WINDOW）与冷却戳
（_COOLDOWN_STAMP）。队列满 503 / 入队异常路径下，片段被丢弃却已耗配额并
刷新冷却——修复后 enqueue 失败路径回滚本条记账：
- 队列满（enqueue→False）→ 503 + 滑窗/冷却戳回滚（新键删除）
- 队列满且冷却戳有旧值 → 旧值恢复
- 入队异常 → 500 + 记账回滚
- 成功入队 → 记账保留（不误回滚）

运行：python -m pytest tests/test_vision_router.py -q
"""
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core.vision.clip_queue import VisionClipQueue
from server.api.routers import vision as vision_router_mod
# R9 合并：第九轮回滚用例以 vision_mod 别名引用同一模块
from server.api.routers import vision as vision_mod


# --------------------------------------------------------------------------- #
# 假依赖（settings / 队列）
# --------------------------------------------------------------------------- #
class FakeVisionCfg:
    def __init__(self, enabled):
        self.enabled = enabled
        self.clip_max_sec = 10


class FakeConfig:
    def __init__(self, enabled):
        self.vision_enhanced = FakeVisionCfg(enabled)


class FakeSettings:
    def __init__(self, enabled):
        self.config = FakeConfig(enabled)


class FakeQueue:
    """可注入路由的替身队列：记录入队、可配置 pending 值。"""

    def __init__(self, pending=0, enqueue_result=True):
        self.enqueued = []
        self.pending = pending
        self.enqueue_result = enqueue_result
        self.consumer = None

    def set_consumer(self, consumer):
        self.consumer = consumer

    def enqueue(self, item):
        self.enqueued.append(item)
        return self.enqueue_result

    def pending_count(self):
        return self.pending

    def is_ready(self):
        return self.consumer is not None


# --------------------------------------------------------------------------- #
# R9 合并并入：护栏内存态复位（模块级 deque/dict 进程内共享，autouse 全局生效）
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clean_guard():
    """每个用例复位护栏内存态（模块级 deque/dict 进程内共享）。"""
    vision_mod.reset_vision_guard()
    yield
    vision_mod.reset_vision_guard()


# --------------------------------------------------------------------------- #
# 路由测试（假队列，确定性）
# --------------------------------------------------------------------------- #
@pytest.fixture
def enable_patches(monkeypatch, tmp_path):
    """返回一个应用构造器，可注入 FakeSettings + FakeQueue + 临时区到 tmp_path。"""
    queue = FakeQueue()

    def _ctrl(enabled):
        app = FastAPI()
        app.include_router(vision_router_mod.router)
        monkeypatch.setattr(vision_router_mod, "get_settings", lambda: FakeSettings(enabled))
        monkeypatch.setattr(vision_router_mod, "vision_clip_queue", queue)
        monkeypatch.setattr(vision_router_mod, "_vision_tmp_dir", lambda: tmp_path)
        return TestClient(app), queue

    return _ctrl


def _post(client, *, pure=True, **overrides):
    payload = {
        "event_type": "object_motion",
        "ts": "1234.5",
        "source": "camera",
    }
    payload.update({k: v for k, v in overrides.items() if v is not None})
    files = {
        "clip": (overrides.get("filename", "fake.mp4"), b"fakevideodata", "video/mp4")
        if pure
        else overrides["clip_payload"]
    }
    return client.post("/vision/clip", files=files, data=payload)


def test_disabled_returns_ignored_and_no_enqueue(enable_patches, tmp_path):
    app, queue = enable_patches(enabled=False)
    with app as c:
        r = _post(c)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["accepted"] is False
        assert queue.enqueued == []
        # 未落盘：临时区无文件
        assert list(tmp_path.iterdir()) == []


def test_valid_enqueue_accepted_and_pending(enable_patches):
    app, queue = enable_patches(enabled=True)
    queue.pending = 1
    with app as c:
        r = _post(c)
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["accepted"] is True
        assert isinstance(body["data"]["clip_id"], str)
        assert body["data"]["pending"] == 1
        # 提交了队列条目，且临时文件确实被写入
        assert len(queue.enqueued) == 1
        item = queue.enqueued[0]
        assert item["source"] == "camera"
        assert item["ts"] == pytest.approx(1234.5)
        assert item["event_meta"]["event_type"] == "object_motion"
        clip_path = Path(item["clip_path"])
        assert clip_path.exists()
        assert clip_path.read_bytes() == b"fakevideodata"
        # 清理测试假队列遗留的临时文件
        clip_path.unlink(missing_ok=True)


def test_invalid_source_422(enable_patches):
    app, queue = enable_patches(enabled=True)
    with app as c:
        r = _post(c, source="unknown")
        assert r.status_code == 422
        assert queue.enqueued == []


def test_missing_event_type_422(enable_patches):
    app, queue = enable_patches(enabled=True)
    with app as c:
        # 缺省 event_type 由 Form 必填触发 422（FastAPI 校验）
        payload = {"ts": "123.0", "source": "camera"}
        files = {"clip": ("fake.mp4", b"data", "video/mp4")}
        r = c.post("/vision/clip", files=files, data=payload)
        assert r.status_code == 422
        assert queue.enqueued == []


def test_bad_number_only_field_semantics(enable_patches):
    # ts 不可解析 → 422（Generated by 业务校验）
    app, queue = enable_patches(enabled=True)
    with app as c:
        r = _post(c, ts="not-a-number")
        assert r.status_code == 422
        assert queue.enqueued == []


def test_oversize_413(enable_patches):
    app, queue = enable_patches(enabled=True)
    big = b"x" * (100 * 1024 * 1024 + 1)
    with app as c:
        files = {"clip": ("big.mp4", big, "video/mp4")}
        r = c.post(
            "/vision/clip",
            files=files,
            data={"event_type": "motion", "ts": "1.0", "source": "camera"},
        )
        assert r.status_code == 413
        assert queue.enqueued == []


# --------------------------------------------------------------------------- #
# 路由 + 真实队列端到端（临时文件终态清理）
# --------------------------------------------------------------------------- #
def test_real_queue_end_to_end_cleanup(monkeypatch, tmp_path):
    """enabled=True + 合法片段 → accepted；真实 worker 在 finally 中清理临时文件。"""
    queue = VisionClipQueue()
    app = FastAPI()
    app.include_router(vision_router_mod.router)
    monkeypatch.setattr(vision_router_mod, "get_settings", lambda: FakeSettings(True))
    monkeypatch.setattr(vision_router_mod, "vision_clip_queue", queue)
    monkeypatch.setattr(vision_router_mod, "_vision_tmp_dir", lambda: tmp_path)

    with TestClient(app) as c:
        r = _post(c)
        assert r.status_code == 200
        assert r.json()["data"]["accepted"] is True

        def cleaned():
            return list(tmp_path.iterdir()) == []

        assert _wait(cleaned, timeout=3.0), f"临时文件未在预期时间内被清理: {list(tmp_path.iterdir())}"
    # 队列 worker 后台任务随 TestClient 关闭被取消，此处仅验证已清理
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- #
# 队列 worker 行为（纯异步，可控）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_queue_consumer_success_cleans_and_pending(tmp_path):
    q = VisionClipQueue()
    f = tmp_path / "clip1.mp4"
    f.write_bytes(b"data")
    processed = []

    async def consumer(item):
        processed.append(item["clip_path"])
        # consumer 不做删除 —— 依赖队列 finally 兜底清理
        await asyncio.sleep(0.001)

    q.set_consumer(consumer)
    assert q.enqueue({"clip_path": str(f), "event_meta": {}, "source": "camera", "ts": 1.0, "accepted_at": ""})
    assert q.pending_count() == 1
    await _async_wait(lambda: not f.exists())
    assert not f.exists(), "临时文件应由队列 finally 清理"
    assert processed == [str(f)]


@pytest.mark.asyncio
async def test_queue_consumer_exception_cleans_and_survives(tmp_path):
    """consumer 抛异常：文件仍清理，worker 存活并继续处理后续条目。"""
    q = VisionClipQueue()
    calls = []

    async def consumer(item):
        calls.append(item["clip_path"])
        if len(calls) == 1:
            raise RuntimeError("理解后端 boom")

    q.set_consumer(consumer)
    f1 = tmp_path / "c1.mp4"
    f2 = tmp_path / "c2.mp4"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")

    assert q.enqueue({"clip_path": str(f1), "event_meta": {}, "source": "camera", "ts": 1.0, "accepted_at": ""})
    assert q.enqueue({"clip_path": str(f2), "event_meta": {}, "source": "camera", "ts": 2.0, "accepted_at": ""})

    await _async_wait(lambda: not f1.exists() and not f2.exists())
    assert not f1.exists()
    assert not f2.exists()
    assert len(calls) == 2, "worker 处理第一条失败后应继续处理第二条"


@pytest.mark.asyncio
async def test_enqueue_safe_fail_no_running_loop(monkeypatch):
    """无运行中事件循环时 enqueue 安全失败返回 False（不崩）。"""
    q = VisionClipQueue()

    def _no_loop():
        raise RuntimeError("no running event loop")

    monkeypatch.setattr(asyncio, "get_running_loop", _no_loop)
    assert q.enqueue({"clip_path": "whatever.mp4"}) is False
    assert q.pending_count() == 0


@pytest.mark.asyncio
async def test_is_ready_toggles():
    q = VisionClipQueue()
    assert q.is_ready() is False
    q.set_consumer(lambda item: None)
    assert q.is_ready() is True
    q.set_consumer(None)
    assert q.is_ready() is False


@pytest.mark.asyncio
async def test_queue_cancel_single_task_done_and_cleanup(tmp_path):
    """consumer 被取消：由 finally 统一收口——单次 task_done（不溢出）且文件仍被清理。

    回归背景：此前取消分支先 cleanup+task_done，finally 再来一遍，同一条目双次
    task_done 触发 ``ValueError: task_done() called too many times`` 并顶替
    CancelledError 向上传播。
    """
    q = VisionClipQueue()
    f = tmp_path / "cc.mp4"
    f.write_bytes(b"data")

    started = asyncio.Event()
    release = asyncio.Event()

    async def consumer(item):
        started.set()
        await release.wait()  # 挂在 consumer 内，等待外部取消

    q.set_consumer(consumer)
    assert q.enqueue({"clip_path": str(f), "event_meta": {}, "source": "camera", "ts": 9.0, "accepted_at": ""})
    await asyncio.wait_for(started.wait(), timeout=2.0)

    task = q._task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    assert not f.exists(), "取消路径最终仍应由 finally 清理临时文件"
    # 单次 task_done：join 立即返回即代表未完成计数已归零（未溢出）
    await asyncio.wait_for(q._queue.join(), timeout=1.0)


# --------------------------------------------------------------------------- #
# R9 合并并入：频率护栏记账回滚（第九轮）
# --------------------------------------------------------------------------- #
def _fake_settings(max_per_hour=10, cooldown_sec=30):
    """构造 vision_enhanced 配置（enabled + 限流/冷却参数）。"""
    return SimpleNamespace(
        config=SimpleNamespace(
            vision_enhanced=SimpleNamespace(
                enabled=True,
                max_clips_per_hour=max_per_hour,
                event_cooldown_sec=cooldown_sec,
                clip_max_sec=None,
            )
        )
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(vision_mod, "get_settings", lambda: _fake_settings())
    app = FastAPI()
    app.include_router(vision_mod.router)
    return TestClient(app)


def _post_clip(c, event_type="person", source="camera"):
    return c.post(
        "/vision/clip",
        files={"clip": ("clip.mp4", b"\x00\x01\x02", "video/mp4")},
        data={"event_type": event_type, "ts": "100.5", "source": source},
    )


class TestQueueFullRollback:
    def test_queue_full_rolls_back_rate_window_and_cooldown(self, client, monkeypatch):
        """队列满 503：本条滑窗时间戳被移除、新建冷却戳被删除。"""
        monkeypatch.setattr(vision_mod.vision_clip_queue, "enqueue", lambda item: False)
        r = _post_clip(client)
        assert r.status_code == 503
        assert len(vision_mod._RATE_WINDOW) == 0      # 记账已回滚
        assert dict(vision_mod._COOLDOWN_STAMP) == {}  # 新键已回滚删除

    def test_queue_full_restores_previous_cooldown_stamp(self, client, monkeypatch):
        """队列满 503：冷却戳原有旧值被恢复（而非停留在本次覆盖写的新值）。"""
        old_ts = time.monotonic() - 1000.0
        key = ("camera", "person")
        vision_mod._COOLDOWN_STAMP[key] = old_ts
        monkeypatch.setattr(vision_mod.vision_clip_queue, "enqueue", lambda item: False)
        r = _post_clip(client)
        assert r.status_code == 503
        assert len(vision_mod._RATE_WINDOW) == 0
        assert vision_mod._COOLDOWN_STAMP[key] == old_ts  # 旧值恢复

    def test_queue_full_does_not_consume_hourly_quota(self, client, monkeypatch):
        """队列满 503 后配额未被消耗：紧接着的下一请求可正常入队。"""
        state = {"full_once": True}

        def fake_enqueue(item):
            if state["full_once"]:
                state["full_once"] = False
                return False  # 第一次队列满
            return True       # 之后恢复

        monkeypatch.setattr(vision_mod.vision_clip_queue, "enqueue", fake_enqueue)
        r1 = _post_clip(client)
        assert r1.status_code == 503
        assert len(vision_mod._RATE_WINDOW) == 0

        r2 = _post_clip(client)
        assert r2.status_code == 200
        assert len(vision_mod._RATE_WINDOW) == 1  # 仅成功那条占配额

    def test_enqueue_exception_rolls_back_guard(self, client, monkeypatch):
        """入队抛异常（500 路径）：同样回滚本条记账。"""
        def boom(item):
            raise RuntimeError("queue broken")

        monkeypatch.setattr(vision_mod.vision_clip_queue, "enqueue", boom)
        r = _post_clip(client)
        assert r.status_code == 500
        assert len(vision_mod._RATE_WINDOW) == 0
        assert dict(vision_mod._COOLDOWN_STAMP) == {}


class TestSuccessfulEnqueueKeepsRecord:
    def test_success_keeps_guard_record(self, client, monkeypatch):
        """成功入队：记账保留（滑窗 1 条 + 冷却戳存在），不误回滚。"""
        monkeypatch.setattr(vision_mod.vision_clip_queue, "enqueue", lambda item: True)
        r = _post_clip(client)
        assert r.status_code == 200
        assert len(vision_mod._RATE_WINDOW) == 1
        assert ("camera", "person") in vision_mod._COOLDOWN_STAMP


class TestGuardRollbackUnit:
    def test_rollback_ignores_foreign_new_stamp(self, client):
        """回滚不覆盖并发请求其后写入的新冷却戳：仅当当前值仍是本条 now 时恢复。"""
        key = ("camera", "person")
        my_now = 1000.0
        vision_mod._COOLDOWN_STAMP[key] = my_now  # 模拟本条写入
        foreign_now = 2000.0                      # 并发请求其后覆盖写
        vision_mod._COOLDOWN_STAMP[key] = foreign_now
        vision_mod._rollback_guard_record(key, my_now, None)
        assert vision_mod._COOLDOWN_STAMP[key] == foreign_now  # 未被回滚破坏


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _wait(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


async def _async_wait(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.01)
    return False
