"""TemporalFusion 时序对齐多模态融合 —— 单元测试。

覆盖（对应任务「必完成」清单）：
    1. align：窗口过滤 / 分组 / 排序。
    2. temporal_fusion_enabled=false → 退化双流，不抛错。
    3. 缺 heartrate 流 → 自动退化双流。
    4. 提供 understand_fn → 调用并得到更丰富 narrative；未提供 → 确定性组装非空 content。
    5. 空 streams → 合理空结果不崩。
"""
import pytest

from server.core.vision.temporal_fusion import (
    FusedContext,
    TemporalFusion,
    TemporalStream,
)
from server.core.vision.video_understanding import NarrativeSummary

from server.core.vision import temporal_fusion as tf_module  # 便于 monkeypatch get_settings


def _make_settings(enabled: bool):
    """构造带 ``vision_enhanced.temporal_fusion_enabled`` 的伪配置单例。"""
    import types

    ve = types.SimpleNamespace(temporal_fusion_enabled=enabled)
    cfg = types.SimpleNamespace(vision_enhanced=ve)
    return types.SimpleNamespace(config=cfg)


def _set_enabled(monkeypatch, enabled: bool):
    monkeypatch.setattr(tf_module, "get_settings", lambda: _make_settings(enabled))


def _streams() -> list:
    """构造覆盖 vision/speech/heartrate/ocr 及窗口外条目的样本流。"""
    return [
        TemporalStream("vision", 12.0, "看到用户打开代码编辑器"),
        TemporalStream("speech", 11.0, "帮我看看这段报错"),
        TemporalStream("heartrate", 13.0, {"bpm": 86, "trend": "up"}),
        TemporalStream("ocr", 12.5, {"text": "Traceback (most recent call last)"}),
        TemporalStream("vision", 20.0, "窗口外条目，应被过滤"),
        TemporalStream("speech", 5.0, "窗口外条目，应被过滤"),
    ]


# --------------------------------------------------------------------------- #
# 1. align：窗口过滤 / 分组 / 排序
# --------------------------------------------------------------------------- #
def test_align_window_filter_group_sort():
    fusion = TemporalFusion()
    ctx = fusion.align(_streams(), window=(10.0, 14.0))

    # 窗口过滤：窗口外条目被剔除
    modalities = set(ctx.per_modality.keys())
    assert "vision" in modalities and "speech" in modalities
    assert "heartrate" in modalities and "ocr" in modalities
    all_ts = [s.ts for s in ctx.sorted_events]
    assert all(10.0 <= t <= 14.0 for t in all_ts)

    # 分组 + 组内排序：每路按 ts 升序
    assert [s.ts for s in ctx.per_modality["vision"]] == [12.0]
    assert [s.ts for s in ctx.per_modality["heartrate"]] == [13.0]

    # 统一时间轴按 (ts, modality) 升序
    assert ctx.sorted_events[0].ts == 11.0  # speech
    assert ctx.sorted_events[1].ts == 12.0  # vision
    assert ctx.window == {"startTs": 10.0, "endTs": 14.0}


def test_align_no_window_keeps_all():
    fusion = TemporalFusion()
    ctx = fusion.align(_streams(), window=None)
    assert len(ctx.sorted_events) == len(_streams())


# --------------------------------------------------------------------------- #
# 5. 空 streams → 合理空结果不崩
# --------------------------------------------------------------------------- #
def test_align_empty_streams_returns_empty_context():
    fusion = TemporalFusion()
    ctx = fusion.align([], window=(0.0, 10.0))
    assert isinstance(ctx, FusedContext)
    assert ctx.per_modality == {}
    assert ctx.sorted_events == []


# --------------------------------------------------------------------------- #
# 3. 缺 heartrate 流 → 自动退化双流（temporal_fusion_enabled=True）
# --------------------------------------------------------------------------- #
def test_fuse_missing_heartrate_degrades_to_dual(monkeypatch):
    _set_enabled(monkeypatch, True)
    fusion = TemporalFusion()
    streams = [
        TemporalStream("vision", 12.0, "看到画面"),
        TemporalStream("speech", 11.0, "说话内容"),
    ]
    ctx = fusion.align(streams, window=(10.0, 14.0))
    assert "heartrate" not in ctx.per_modality

    summary = fusion.fuse(ctx)
    assert isinstance(summary, NarrativeSummary)
    assert "（仅视觉+语音）" in summary.content
    assert "视觉" in summary.content and "语音" in summary.content
    # 缺心率仍不抛错、不阻断
    assert summary.degraded is True


# --------------------------------------------------------------------------- #
# 2. temporal_fusion_enabled=false → 退化双流，不抛错
# --------------------------------------------------------------------------- #
def test_fuse_disabled_degrades_to_dual(monkeypatch):
    _set_enabled(monkeypatch, False)
    fusion = TemporalFusion()
    # 即便同时存在 heartrate 流，开关关闭也必须退化为双流
    ctx = fusion.align(_streams(), window=(10.0, 14.0))
    assert "heartrate" in ctx.per_modality

    summary = fusion.fuse(ctx)
    assert isinstance(summary, NarrativeSummary)
    assert "（仅视觉+语音）" in summary.content
    # content 中不得出现多模态融合标注
    assert "多模态时间融合" not in summary.content
    assert summary.degraded is True


def test_fuse_disabled_without_vision_speech_still_nonblocking(monkeypatch):
    _set_enabled(monkeypatch, False)
    fusion = TemporalFusion()
    ctx = fusion.align([TemporalStream("heartrate", 13.0, {"bpm": 90})], window=(10.0, 14.0))

    summary = fusion.fuse(ctx)
    assert isinstance(summary, NarrativeSummary)
    # 无视觉/语音仍产出非空降级摘要，不抛异常
    assert "（仅视觉+语音）" in summary.content
    assert summary.content.strip()


# --------------------------------------------------------------------------- #
# 4. understand_fn / 确定性组装
# --------------------------------------------------------------------------- #
def test_fuse_with_understand_fn_returns_richer_narrative(monkeypatch):
    _set_enabled(monkeypatch, True)
    called = {"n": 0}

    def understand_fn(prompt: str):
        called["n"] += 1
        assert "clip 时间窗口" in prompt
        assert "heartrate" in prompt  # 心率流应进入 prompt
        return NarrativeSummary(
            content="CUSTOM_FUSED_NARRATIVE：用户因报错情绪紧张，心率升高且盯着屏幕",
            events=["debug_error"],
            emotion="焦虑",
            clip_ts=12.0,
            source="screen",
            degraded=False,
        )

    fusion = TemporalFusion()
    ctx = fusion.align(_streams(), window=(10.0, 14.0))
    summary = fusion.fuse(ctx, understand_fn=understand_fn)

    assert called["n"] == 1  # 确实被调用
    assert summary.content == "CUSTOM_FUSED_NARRATIVE：用户因报错情绪紧张，心率升高且盯着屏幕"
    assert summary.emotion == "焦虑"


def test_fuse_without_understand_fn_deterministic_nonempty(monkeypatch):
    _set_enabled(monkeypatch, True)
    fusion = TemporalFusion()
    ctx = fusion.align(_streams(), window=(10.0, 14.0))

    summary = fusion.fuse(ctx)  # 未提供 understand_fn
    assert isinstance(summary, NarrativeSummary)
    assert summary.content.strip()
    assert "多模态时间融合" in summary.content
    # 视觉为主干 + 心率/OCR 补充都有体现
    assert "视觉（主干）" in summary.content
    assert "心率" in summary.content
    assert "屏幕OCR" in summary.content
    assert summary.degraded is False


def test_fuse_understand_fn_failure_falls_back_to_deterministic(monkeypatch):
    _set_enabled(monkeypatch, True)

    def failing_fn(prompt: str):
        raise RuntimeError("VLM 服务不可用")

    fusion = TemporalFusion()
    ctx = fusion.align(_streams(), window=(10.0, 14.0))
    summary = fusion.fuse(ctx, understand_fn=failing_fn)
    # 真实 VLM 失败 → 回退确定性组装，非空不崩
    assert isinstance(summary, NarrativeSummary)
    assert summary.content.strip()
    assert "多模态时间融合" in summary.content


def test_fuse_base_narrative_metadata_carried(monkeypatch):
    _set_enabled(monkeypatch, True)
    fusion = TemporalFusion()
    base = NarrativeSummary(
        content="视觉主干摘要",
        events=["video_clip"],
        emotion="中性",
        clip_ts=12.0,
        source="camera",
        event_type="motion",
        confidence=0.9,
        ocr_blocks=[{"text": "abc"}],
    )
    ctx = fusion.align(
        [TemporalStream("vision", 12.0, "画面"), TemporalStream("speech", 11.0, "语音")],
        window=(10.0, 14.0),
    )
    summary = fusion.fuse(ctx, base_narrative=base)
    assert summary.source == "camera"
    assert summary.event_type == "motion"
    assert summary.confidence == 0.9
    assert summary.clip_ts == 12.0


# --------------------------------------------------------------------------- #
# 集成：真实配置入口（默认 temporal_fusion_enabled=False 时应降级，不崩）
# --------------------------------------------------------------------------- #
def test_fuse_without_monkeypatch_real_config_nonblocking():
    fusion = TemporalFusion()
    ctx = fusion.align(_streams(), window=(10.0, 14.0))
    summary = fusion.fuse(ctx, understand_fn=None)
    # 不施加 monkeypatch，走真实 get_settings() → 默认关闭 → 双流退化，必须仍可消费
    assert isinstance(summary, NarrativeSummary)
    assert summary.content.strip()