"""server/autonomy/dream/filter.py（DreamFilter 确定性闸门）单测。

覆盖：
1. 三类拦截：factual_hallucination / permanent_touch / low_lucidity
2. 正常放行（approved, reason=None）
3. 边界：lucidity 恰等于 min_lucidity 放行；importance=0.94 放行、0.95 拦截
4. DECISION_POINTS 已登记 "D7_DREAM_FILTER"

运行：python -m pytest tests/test_dream_filter.py -q
"""
import pytest

from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.filter import DreamFilter, FACTUAL_PATTERNS
from server.core.decision.decision_core import DECISION_POINTS


def _make_candidate(content="梦见在海边捡到一颗会发光的石头", lucidity_score=0.8):
    """构造一条梦境候选（含 content / lucidity_score）。"""
    return {"content": content, "lucidity_score": lucidity_score}


def _make_meta(importance_score=0.4, permanent=False, memory_id=1, content="昨晚在公园散步"):
    """构造一条关联记忆元数据（引擎侧组装字段）。"""
    return {
        "id": memory_id,
        "importance_score": importance_score,
        "permanent": permanent,
        "content": content,
    }


def _run(candidate, memories, config=None):
    """执行过滤并返回结果。"""
    f = DreamFilter()
    return f.filter_candidate(candidate, memories, config or DreamConfig())


# ================================================================ 事实性断言拦截
class TestFactualAssertion:
    @pytest.mark.parametrize(
        "content",
        [
            "你昨天在海边散步时丢了钥匙",
            "你刚才说要去看那部新电影",
            "你说过你喜欢喝乌龙茶",
            "你曾经独自爬上过那座山",
            "你做了很复杂的晚餐",
            "我记得你小时候养过一只猫",
        ],
    )
    def test_factual_patterns_rejected(self, content):
        result = _run(_make_candidate(content=content), [])
        assert result == {
            "approved": False,
            "decision": "rejected",
            "reason": "factual_hallucination",
        }

    def test_anchor_without_event_not_rejected(self):
        # "你昨天" 等锚点后无具体事件描述 → 不命中，正常放行
        result = _run(_make_candidate(content="你昨天"), [])
        assert result["approved"] is True

    def test_no_factual_anchor_approved(self):
        # 无事实断言锚点的联想内容 → 不被当作 factual_hallucination 拦截
        result = _run(_make_candidate(content="梦见一片会发光的森林"), [])
        assert result["approved"] is True

    def test_factual_patterns_are_compiled_regex(self):
        # FACTUAL_PATTERNS 均为可执行正则
        assert len(FACTUAL_PATTERNS) >= 3
        assert all(hasattr(p, "search") for p in FACTUAL_PATTERNS)


# ================================================================ 红线 R2 拦截
class TestPermanentTouch:
    def test_permanent_memory_rejected(self):
        result = _run(
            _make_candidate(),
            [_make_meta(permanent=True)],
        )
        assert result == {
            "approved": False,
            "decision": "rejected",
            "reason": "permanent_touch",
        }

    def test_importance_095_rejected(self):
        result = _run(
            _make_candidate(),
            [_make_meta(importance_score=0.95)],
        )
        assert result["decision"] == "rejected"
        assert result["reason"] == "permanent_touch"

    def test_importance_above_095_rejected(self):
        result = _run(
            _make_candidate(),
            [_make_meta(importance_score=0.99)],
        )
        assert result["reason"] == "permanent_touch"

    def test_importance_094_approved(self):
        # 边界：0.94 < 0.95 → 放行
        result = _run(
            _make_candidate(),
            [_make_meta(importance_score=0.94)],
        )
        assert result["approved"] is True

    def test_multiple_meta_any_touch_rejected(self):
        result = _run(
            _make_candidate(),
            [
                _make_meta(importance_score=0.4, memory_id=1),
                _make_meta(permanent=True, memory_id=2),
            ],
        )
        assert result["reason"] == "permanent_touch"

    def test_empty_meta_approved(self):
        result = _run(_make_candidate(), [])
        assert result["approved"] is True


# ================================================================ 低清醒度拦截
class TestLowLucidity:
    def test_below_min_lucidity_rejected(self):
        result = _run(_make_candidate(lucidity_score=0.2), [])
        assert result == {
            "approved": False,
            "decision": "rejected",
            "reason": "low_lucidity",
        }

    def test_equal_min_lucidity_approved(self):
        # 边界：lucidity 恰等于 min_lucidity(0.3) → 放行
        result = _run(_make_candidate(lucidity_score=0.3), [])
        assert result["approved"] is True

    def test_above_min_lucidity_approved(self):
        result = _run(_make_candidate(lucidity_score=0.8), [])
        assert result["approved"] is True

    def test_custom_min_lucidity(self):
        # 自定义 min_lucidity=0.6：0.5 拦截
        cfg = DreamConfig(min_lucidity=0.6)
        result = _run(_make_candidate(lucidity_score=0.5), [], config=cfg)
        assert result["reason"] == "low_lucidity"
        # 0.6 恰等于阈值 → 放行
        result = _run(_make_candidate(lucidity_score=0.6), [], config=cfg)
        assert result["approved"] is True


# ================================================================ 正常放行
class TestApproved:
    def test_approved_shape(self):
        result = _run(_make_candidate(), [])
        assert result == {
            "approved": True,
            "decision": "approved",
            "reason": None,
        }


# ================================================================ DECISION_POINTS 登记
class TestDecisionPoints:
    def test_d7_dream_filter_registered(self):
        assert "D7_DREAM_FILTER" in DECISION_POINTS

    def test_d1_to_d6_preserved(self):
        # 仅登记 D7，D1-D6 枚举保持不动
        for point in ("D1_LOCATION", "D2_METADATA", "D3_ASK_USER",
                      "D4_REDISTILL", "D5_CROSS_VALIDATE", "D6_REJECT"):
            assert point in DECISION_POINTS
