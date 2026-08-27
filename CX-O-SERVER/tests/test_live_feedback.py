"""server.services.live_feedback (LiveFeedbackTracker) 单元测试。

覆盖：
- record_ai_response 后窗口内正向弹幕爆发 → 判定 chosen=ai_response 并推送 feedback
- 负向弹幕爆发 → rejected=ai_response，且 chosen/rejected 均非空并满足契约
- 无 AI 回复记录 → 不触发
- auto_push=False / Tuner 不可达 → 静默降级不抛异常
- 10s 窗口外弹幕不触发

运行：python -m pytest tests/test_live_feedback.py -v
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from server.core.memory.emotion import EmotionAnalyzer
from server.services.live_feedback import LiveFeedbackTracker

AI_RESPONSE = "这是 AI 助理的回复内容"
PROMPT = "你好"

# 加载 public/ 反馈数据契约，用于断言 payload 满足 minLength 等约束
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "public" / "schema" / "cxo_tuner_feedback.schema.json"
with open(_SCHEMA_PATH, "r", encoding="utf-8") as _f:
    FEEDBACK_SCHEMA = json.load(_f)


def _assert_valid_payload(payload: dict) -> None:
    """断言 payload 满足反馈数据契约（response_chosen/rejected 均非空且与 content 不同）。"""
    chosen = payload["response_chosen"]
    rejected = payload["response_rejected"]
    assert isinstance(chosen, str) and chosen.strip(), "response_chosen 不得为空"
    assert isinstance(rejected, str) and rejected.strip(), "response_rejected 不得为空"
    assert chosen != rejected, "response_chosen 与 response_rejected 内容必须不同"
    validate(instance=payload, schema=FEEDBACK_SCHEMA)


def _make_cfg(auto_push):
    """构造最小 evolution 配置提供者（仅暴露 auto_push）。"""
    return lambda: SimpleNamespace(auto_push=auto_push)


@pytest.fixture
def tracker():
    return LiveFeedbackTracker(
        emotion_analyzer=EmotionAnalyzer(),
        push_func=lambda payload: None,
        get_config=_make_cfg(True),
    )


class TestPositiveBurst:
    @pytest.mark.asyncio
    async def test_positive_burst_chosen_is_ai_response(self):
        captured = []
        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=lambda payload: captured.append(payload),
            get_config=_make_cfg(True),
        )
        t.record_ai_response(AI_RESPONSE, ts=100.0, prompt=PROMPT)

        payload = None
        for i, ts in enumerate([100.5, 101.0, 101.5]):
            payload = await t.on_danmaku("开心", ts=ts, session_id="s1")

        assert payload is not None
        assert payload["response_chosen"] == AI_RESPONSE
        assert payload["response_rejected"] != ""
        assert payload["source"] == "live_danmaku"
        assert payload["session_id"] == "s1"
        assert payload["metadata"]["danmaku_sentiment"] == "positive"
        assert payload["metadata"]["window_counts"]["positive"] == 3
        # 推送被调用且携带相同 payload
        assert captured and captured[-1]["response_chosen"] == AI_RESPONSE
        _assert_valid_payload(payload)


class TestNegativeBurst:
    @pytest.mark.asyncio
    async def test_negative_burst_rejected_is_ai_response(self):
        captured = []
        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=lambda payload: captured.append(payload),
            get_config=_make_cfg(True),
        )
        t.record_ai_response(AI_RESPONSE, ts=200.0, prompt=PROMPT)

        for ts in [200.5, 201.0, 201.5]:
            await t.on_danmaku("糟糕", ts=ts, session_id="s1")

        assert captured
        payload = captured[-1]
        assert payload["response_rejected"] == AI_RESPONSE
        assert payload["response_chosen"] != ""
        assert payload["metadata"]["danmaku_sentiment"] == "negative"
        _assert_valid_payload(payload)

    @pytest.mark.asyncio
    async def test_negative_burst_prefers_previous_round_as_alternative(self):
        """负向占优且存在上一轮不同回复时，response_chosen 取历史对比样本而非占位模板。"""
        captured = []
        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=lambda payload: captured.append(payload),
            get_config=_make_cfg(True),
        )
        previous = "这是上一轮更稳妥的回复"
        t.record_ai_response(previous, ts=200.0, prompt=PROMPT)
        t.record_ai_response(AI_RESPONSE, ts=260.0, prompt=PROMPT)

        for ts in [260.5, 261.0, 261.5]:
            await t.on_danmaku("糟糕", ts=ts, session_id="s1")

        assert captured
        payload = captured[-1]
        assert payload["response_rejected"] == AI_RESPONSE
        assert payload["response_chosen"] == previous
        _assert_valid_payload(payload)


class TestNoResponse:
    @pytest.mark.asyncio
    async def test_no_ai_response_not_triggered(self, tracker):
        assert await tracker.on_danmaku("开心", ts=10.0) is None
        assert tracker._window == []


class TestQuietDegrade:
    @pytest.mark.asyncio
    async def test_auto_push_false_skips_push(self):
        captured = []
        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=lambda payload: captured.append(payload),
            get_config=_make_cfg(False),  # auto_push 关闭
        )
        t.record_ai_response(AI_RESPONSE, ts=300.0, prompt=PROMPT)

        for ts in [300.5, 301.0, 301.5]:
            await t.on_danmaku("开心", ts=ts)

        assert captured == []  # 不推送

    @pytest.mark.asyncio
    async def test_tuner_unreachable_silent_degrade(self):
        called = []

        async def raising_push(payload):
            called.append(payload)
            raise ConnectionError("tuner down")

        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=raising_push,
            get_config=_make_cfg(True),
        )
        t.record_ai_response(AI_RESPONSE, ts=400.0, prompt=PROMPT)

        for ts in [400.5, 401.0, 401.5]:
            await t.on_danmaku("开心", ts=ts)

        assert called  # 尝试推送但不可达
        # 不抛异常（静默降级）——测试通过即证明未向上传播


class TestWindowOutside:
    @pytest.mark.asyncio
    async def test_danmaku_outside_10s_window_not_triggered(self):
        captured = []
        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=lambda payload: captured.append(payload),
            get_config=_make_cfg(True),
        )
        t.record_ai_response(AI_RESPONSE, ts=500.0, prompt=PROMPT)

        # 窗口外（>10s）的弹幕即使爆发也不触发
        for ts in [511.0, 511.5, 512.0]:
            await t.on_danmaku("开心", ts=ts)

        assert captured == []
        assert t._window == []  # 窗口外弹幕未计入


class TestFingerprintBound:
    def test_reported_fingerprints_is_bounded_deque(self):
        # _reported_fingerprints 应为有界 deque（仅保留最近指纹），防止长期运行无界增长
        from collections import deque

        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=lambda payload: None,
            get_config=_make_cfg(True),
        )
        assert isinstance(t._reported_fingerprints, deque)


class TestFingerprintRegisterBeforePush:
    """M：指纹先登记后推送——并发双报防护，push 失败宁可丢反馈也不重报。"""

    @pytest.mark.asyncio
    async def test_push_failure_still_registers_fingerprint(self):
        # push 抛异常被 _safe_push 吞掉后，指纹已登记 → 同 prompt/response 不再重报
        import asyncio

        async def failing_push(payload):
            raise ConnectionError("tuner down")

        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=failing_push,
            get_config=_make_cfg(True),
        )
        t.record_ai_response(AI_RESPONSE, ts=600.0, prompt=PROMPT)

        # 未达爆发阈值（默认 3）的弹幕直接 None，不登记指纹
        assert await t.on_danmaku("开心", ts=600.5) is None
        assert await t.on_danmaku("开心", ts=601.0) is None

        # 第 3 条达到阈值 → 构造 payload 返回，push 静默降级（failing_push 被吞）
        third = await t.on_danmaku("开心", ts=601.5)
        assert isinstance(third, dict) and third["source"] == "live_danmaku"

        for ts in [602.0, 602.5]:
            # 指纹已登记（先于 push）→ 查重命中，不再重报
            assert await t.on_danmaku("开心", ts=ts) is None

        fingerprint = t._fingerprint()
        assert fingerprint in t._reported_fingerprints  # 已登记

    @pytest.mark.asyncio
    async def test_concurrent_burst_reports_once(self):
        # 并发弹幕同窗口爆发：登记先行使第二次进入时查重命中 → 仅报一次
        import asyncio

        pushed = []

        async def slow_push(payload):
            await asyncio.sleep(0.01)  # 制造 await 窗口
            pushed.append(payload)

        t = LiveFeedbackTracker(
            emotion_analyzer=EmotionAnalyzer(),
            push_func=slow_push,
            get_config=_make_cfg(True),
        )
        t.record_ai_response(AI_RESPONSE, ts=700.0, prompt=PROMPT)

        results = await asyncio.gather(
            *[t.on_danmaku("开心", ts=700.5 + i * 0.001) for i in range(3)]
        )
        payloads = [r for r in results if r is not None]
        assert len(payloads) == 1  # 只报一次
        assert len(pushed) == 1
        assert t._reported_fingerprints.count(t._fingerprint()) == 1
        # 默认 maxlen=2000；追加超过上限时旧指纹被淘汰、长度保持有界
        for i in range(2100):
            t._reported_fingerprints.append(f"fp-{i}")
        assert len(t._reported_fingerprints) == t._reported_fingerprints.maxlen == 2000
        assert "fp-0" not in t._reported_fingerprints
        assert "fp-2099" in t._reported_fingerprints