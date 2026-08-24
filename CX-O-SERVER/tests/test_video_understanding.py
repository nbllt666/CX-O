"""server.core.vision.video_understanding (VideoUnderstanding) 单元测试。

通过 mock 隔离外部依赖（不真调 vLLM / PaddleOCR / 解帧）：
- 用假 MultimodalPipeline 注入 `VideoUnderstanding.pipeline`，mock preprocess 返回
  携带不同 native_decode_used 的 artifact。
- 用假配置（monkeypatch ``server.core.vision.video_understanding.get_settings``）
  控制 require_vllm / provider / ocr_keyframe_enabled / task_timeout_seconds。
- ``draw_keyframe`` 环境无 cv2/imageio/av 时默认返回 None，OCR 自动跳过；测试用
  mock 覆盖验证 OCR 分支。

运行：python -m pytest tests/test_video_understanding.py -q
"""
import asyncio
import time
from pathlib import Path

import pytest

from server.core.multimodal.multimodal_pipeline import MultimodalArtifact
from server.core.vision import video_understanding as vu_mod
from server.core.vision.clip_queue import VisionClipQueue
from server.core.vision.video_understanding import NarrativeSummary, VideoUnderstanding, draw_keyframe


# --------------------------------------------------------------------------- #
# 假依赖（配置 / pipeline / image_worker）
# --------------------------------------------------------------------------- #
class FakeVisionCfg:
    def __init__(self, require_vllm=True, ocr_keyframe_enabled=True,
                 narrative_memory_enabled=True):
        self.require_vllm = require_vllm
        self.ocr_keyframe_enabled = ocr_keyframe_enabled
        self.narrative_memory_enabled = narrative_memory_enabled


class FakeMultimodalCfg:
    def __init__(self, task_timeout_seconds=30):
        self.task_timeout_seconds = task_timeout_seconds


class FakeLLM:
    def __init__(self, provider="ollama"):
        self.provider = provider


class FakeConfig:
    def __init__(self, provider="ollama", require_vllm=True,
                 ocr_keyframe_enabled=True, timeout=30):
        self.vision_enhanced = FakeVisionCfg(
            require_vllm=require_vllm, ocr_keyframe_enabled=ocr_keyframe_enabled
        )
        self.multimodal_pipeline = FakeMultimodalCfg(timeout)
        self.llm = FakeLLM(provider)


class FakeSettings:
    def __init__(self, provider="ollama", require_vllm=True,
                 ocr_keyframe_enabled=True, timeout=30):
        self.config = FakeConfig(
            provider=provider, require_vllm=require_vllm,
            ocr_keyframe_enabled=ocr_keyframe_enabled, timeout=timeout,
        )


class FakePipeline:
    """记录 preprocess 调用；可配置返回指定 artifact / 抛错。"""

    def __init__(self, artifact=None, error=None):
        self.artifact = artifact
        self.error = error
        self.preprocess_calls = []

    def preprocess(self, source_type, source_ref):
        self.preprocess_calls.append((source_type, source_ref))
        if self.error is not None:
            raise self.error
        return self.artifact


class FakeImageWorker:
    """记录 ocr 调用；可配置返回 blocks / 抛错。"""

    def __init__(self, blocks=None, error=None):
        self.blocks = blocks or [{"text": "你好世界", "bbox": [0, 0, 10, 10]}]
        self.error = error
        self.ocr_calls = []

    def ocr(self, image_path):
        self.ocr_calls.append(image_path)
        if self.error is not None:
            raise self.error
        return [dict(b) for b in self.blocks], 0.9


def _native_artifact(text="一个人在敲击键盘编写代码，随后保存文件"):
    return MultimodalArtifact(
        artifact_id="a1",
        type="video",
        source="/tmp/x.mp4",
        text_content=text,
        native_decode_used=True,
        extra_metadata={
            "modality": "video",
            "decode_mode": "native",
            "vision_description": text,
        },
        confidence=0.88,
        vision_degraded=False,
        created_at="2026-01-01T00:00:00+08:00",
    )


def _degraded_artifact():
    return MultimodalArtifact(
        artifact_id="a2",
        type="video",
        source="/tmp/y.mp4",
        text_content="[降级] video 模态原生解码不可用。",
        native_decode_used=False,
        extra_metadata={"modality": "video", "decode_mode": "degraded"},
        confidence=0.5,
        vision_degraded=True,
        created_at="2026-01-01T00:00:01+08:00",
    )


def _install_conf(monkeypatch, **kw):
    monkeypatch.setattr(vu_mod, "get_settings", lambda: FakeSettings(**kw))


def _make_vu(pipeline_artifact=None, pipeline_error=None, image_blocks=None):
    return VideoUnderstanding(
        pipeline=FakePipeline(artifact=pipeline_artifact, error=pipeline_error),
        image_worker=FakeImageWorker(blocks=image_blocks),
    )


# --------------------------------------------------------------------------- #
# draw_keyframe（环境无解码库 → None，不抛异常）
# --------------------------------------------------------------------------- #
def test_draw_keyframe_returns_none_without_libs():
    try:
        import cv2  # noqa: F401
        has = True
    except ImportError:
        has = False
    if not has:
        assert draw_keyframe("/nonexistent/video.mp4", 0.0) is None


# --------------------------------------------------------------------------- #
# understand —— 原生路径
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_native_path_narrative_not_degraded(monkeypatch, tmp_path):
    _install_conf(monkeypatch, provider="vllm", require_vllm=True,
                  ocr_keyframe_enabled=False)
    vu = _make_vu(pipeline_artifact=_native_artifact())
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"v")
    summary = await vu.understand(
        clip_path=str(clip),
        event_meta={"event_type": "screen_coding"},
        source="screen",
        ts=123.0,
    )
    assert isinstance(summary, NarrativeSummary)
    assert summary.degraded is False
    assert summary.native_used is True
    assert summary.confidence == pytest.approx(0.88)
    assert summary.source == "screen"
    assert summary.event_type == "screen_coding"
    assert "敲击键盘" in summary.content
    assert "screen_coding" in summary.events
    assert vu.image_worker.ocr_calls == [], "OCR 未启用时不应调用 image_worker"


@pytest.mark.asyncio
async def test_native_path_source_camera_no_ocr(monkeypatch, tmp_path):
    # source=camera 不触发 OCR（读屏字仅对屏幕有意义）
    _install_conf(monkeypatch, provider="vllm", require_vllm=True,
                  ocr_keyframe_enabled=True)
    vu = _make_vu(
        pipeline_artifact=_native_artifact(),
        image_blocks=[{"text": "不应读取", "bbox": [0, 0, 1, 1]}],
    )
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"v")
    summary = await vu.understand(
        clip_path=str(clip),
        event_meta={"event_type": "motion"},
        source="camera",
        ts=1.0,
    )
    assert summary.degraded is False
    assert vu.image_worker.ocr_calls == []


# --------------------------------------------------------------------------- #
# understand —— 降级单帧快照
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_degraded_path_provider_not_vllm(monkeypatch, tmp_path):
    # provider != vllm 且 require_vllm=True → 降级，degraded=True，不抛异常
    _install_conf(monkeypatch, provider="ollama", require_vllm=True,
                  ocr_keyframe_enabled=False)
    vu = _make_vu(pipeline_artifact=_degraded_artifact())
    clip = tmp_path / "d.mp4"
    clip.write_bytes(b"v")
    summary = await vu.understand(
        clip_path=str(clip),
        event_meta={"event_type": "object_motion"},
        source="screen",
        ts=5.0,
    )
    assert summary.degraded is True
    assert summary.native_used is False
    assert summary.confidence == pytest.approx(0.5)
    assert "降级" in summary.content


@pytest.mark.asyncio
async def test_degraded_path_artifact_native_unused(monkeypatch, tmp_path):
    # artifact 自身 native_decode_used=False（vLLM 端点降级）→ 也走降级
    _install_conf(monkeypatch, provider="vllm", require_vllm=True,
                  ocr_keyframe_enabled=False)
    vu = _make_vu(pipeline_artifact=_degraded_artifact())
    clip = tmp_path / "e.mp4"
    clip.write_bytes(b"v")
    summary = await vu.understand(
        clip_path=str(clip),
        event_meta={"event_type": "scene_change"},
        source="camera",
        ts=0.0,
    )
    assert summary.degraded is True
    assert summary.native_used is False


# --------------------------------------------------------------------------- #
# OCR 分支
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ocr_disabled_does_not_run(monkeypatch, tmp_path):
    _install_conf(monkeypatch, provider="ollama", require_vllm=True,
                  ocr_keyframe_enabled=False)
    clip = tmp_path / "o.mp4"
    clip.write_bytes(b"v")
    vu = _make_vu(pipeline_artifact=_degraded_artifact())
    frame = tmp_path / "kf.png"
    frame.write_bytes(b"png")

    def fake_draw(*a, **k):
        return str(frame)

    monkeypatch.setattr(vu_mod, "draw_keyframe", fake_draw)
    summary = await vu.understand(
        clip_path=str(clip),
        event_meta={"event_type": "typing"},
        source="screen",
        ts=2.0,
    )
    assert summary.degraded is True
    assert vu.image_worker.ocr_calls == [], "OCR 关闭时不应执行"


@pytest.mark.asyncio
async def test_ocr_executed_on_screen_source(monkeypatch, tmp_path):
    _install_conf(monkeypatch, provider="ollama", require_vllm=True,
                  ocr_keyframe_enabled=True)
    o_blocks = [{"text": "保存文件成功", "bbox": [0, 0, 20, 20]}]
    vu = _make_vu(pipeline_artifact=_degraded_artifact(), image_blocks=o_blocks)
    clip = tmp_path / "k.mp4"
    clip.write_bytes(b"v")
    frame = tmp_path / "key.png"
    frame.write_bytes(b"png")

    def fake_draw(video_path, timestamp_sec):
        return str(frame)

    monkeypatch.setattr(vu_mod, "draw_keyframe", fake_draw)

    summary = await vu.understand(
        clip_path=str(clip),
        event_meta={"event_type": "screen_change"},
        source="screen",
        ts=3.0,
    )
    assert vu.image_worker.ocr_calls, "OCR 应被调用"
    assert summary.degraded is True
    assert "保存文件成功" in summary.content
    assert summary.ocr_blocks == o_blocks
    assert not frame.exists(), "临时关键帧应由 _collect_keyframe_ocr 清理"


# --------------------------------------------------------------------------- #
# 超时 / 异常（understand 抛错冒泡，由队列兜底清理）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_timeout_raises(monkeypatch, tmp_path):
    import time as _time

    _install_conf(monkeypatch, provider="ollama", require_vllm=True,
                  ocr_keyframe_enabled=False, timeout=1)

    class SlowPipeline:
        def preprocess(self, st, sr):
            _time.sleep(5)  # 同步阻塞远超 1s 超时
            return _degraded_artifact()

    vu = VideoUnderstanding(pipeline=SlowPipeline(), image_worker=FakeImageWorker())
    clip = tmp_path / "t.mp4"
    clip.write_bytes(b"v")
    with pytest.raises(TimeoutError):
        await vu.understand(
            clip_path=str(clip),
            event_meta={"event_type": "timeout_case"},
            source="screen",
            ts=1.0,
        )


@pytest.mark.asyncio
async def test_preprocess_exception_bubbles(monkeypatch, tmp_path):
    _install_conf(monkeypatch, provider="vllm", require_vllm=True,
                  ocr_keyframe_enabled=False)
    vu = _make_vu(pipeline_error=RuntimeError("推理失败"))
    clip = tmp_path / "err.mp4"
    clip.write_bytes(b"v")
    with pytest.raises(RuntimeError):
        await vu.understand(
            clip_path=str(clip),
            event_meta={"event_type": "x"},
            source="camera",
            ts=0.0,
        )


def test_consumer_exception_cleaned_by_queue(monkeypatch, tmp_path):
    """consumer 抛错冒泡 → 队列 finally 兜底清理临时文件，worker 存活。"""
    asyncio.run(_run_consumer_exception(monkeypatch, tmp_path))


async def _run_consumer_exception(monkeypatch, tmp_path):
    _install_conf(monkeypatch, provider="vllm", require_vllm=True,
                  ocr_keyframe_enabled=False)

    class BoomPipeline:
        def preprocess(self, st, sr):
            raise RuntimeError("boom")

    vu = VideoUnderstanding(pipeline=BoomPipeline(), image_worker=FakeImageWorker())
    q = VisionClipQueue()
    vu.register_as_consumer(q)
    clip = tmp_path / "boom.mp4"
    clip.write_bytes(b"v")
    assert q.enqueue({
        "clip_path": str(clip),
        "event_meta": {"event_type": "x"},
        "source": "camera",
        "ts": 0.0,
        "accepted_at": "",
    }) is True

    await _async_wait(lambda: not clip.exists(), timeout=5.0)
    assert not clip.exists(), "consumer 抛错后临时片段仍应被队列 finally 清理"


# --------------------------------------------------------------------------- #
# 队列 consumer 端到端：register_as_consumer + 理解 + 临时文件清理
# --------------------------------------------------------------------------- #
def test_register_as_consumer_consumes_and_cleans(monkeypatch, tmp_path):
    asyncio.run(_run_register_consumer(monkeypatch, tmp_path))


async def _run_register_consumer(monkeypatch, tmp_path):
    _install_conf(monkeypatch, provider="ollama", require_vllm=True,
                  ocr_keyframe_enabled=False)

    class FakePipeline2:
        def preprocess(self, st, sr):
            return _degraded_artifact()

    vu = VideoUnderstanding(pipeline=FakePipeline2(), image_worker=FakeImageWorker())

    # 捕获 understand 调用（consume 以实例属性查找 self.understand，可整体替换）
    calls = []
    called_unexpected = []

    async def recorder(clip_path, event_meta, source, ts):
        calls.append((clip_path, event_meta, source, ts))
        return NarrativeSummary(
            content="captured",
            events=["scene_change"],
            emotion="中性",
            clip_ts=float(ts or 0),
            source=source,
            event_type=(event_meta or {}).get("event_type", ""),
            confidence=0.5,
            native_used=False,
            degraded=True,
            ocr_blocks=[],
        )

    vu.understand = recorder  # 实例属性覆盖方法
    q = VisionClipQueue()
    vu.register_as_consumer(q)
    assert q.is_ready() is True

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fakevideo")
    item = {
        "clip_path": str(clip),
        "event_meta": {"event_type": "scene_change"},
        "source": "camera",
        "ts": 8.0,
        "accepted_at": "2026-01-01T00:00:00+08:00",
    }
    assert q.enqueue(item) is True

    await _async_wait(lambda: not clip.exists(), timeout=5.0)
    assert not clip.exists(), "消费者处理后临时片段应由队列 finally 清理"
    assert q.pending_count() == 0
    assert calls, "队列 worker 应调用 understand"
    assert calls[0][2] == "camera"
    assert calls[0][1]["event_type"] == "scene_change"


async def _async_wait(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.01)
    return False