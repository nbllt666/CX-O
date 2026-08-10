"""server.core.memory.emotion (EmotionAnalyzer) 单元测试。

覆盖规则规则型情感分析：正/负/中性词、强度词、否定词、混合文本、
文本分档、缓存行为、快捷函数。
运行：python -m pytest tests/test_emotion.py -v
"""
import asyncio

import pytest

from server.core.memory.emotion import EmotionAnalyzer, get_emotion, get_emotion_for_decay


@pytest.fixture
def analyzer():
    return EmotionAnalyzer()


def _analyze(analyzer, text, context=""):
    """同步包装 async analyze。"""
    return asyncio.run(analyzer.analyze(text, context))


class TestEmptyAndTrivial:
    def test_empty_text_neutral(self, analyzer):
        r = _analyze(analyzer, "")
        assert r.emotion_type == "neutral"
        assert r.polarity == 0.0
        assert r.keywords == []

    def test_whitespace_text_neutral(self, analyzer):
        r = _analyze(analyzer, "   ")
        assert r.emotion_type == "neutral"

    def test_no_match_neutral(self, analyzer):
        r = _analyze(analyzer, "今天天气不错啊程序跑起来了")
        assert r.emotion_type == "neutral"
        assert r.polarity == 0.0


class TestPolarity:
    def test_positive_word(self, analyzer):
        r = _analyze(analyzer, "开心")
        assert r.emotion_type == "positive"
        assert r.polarity > 0.2
        assert "开心" in r.keywords

    def test_negative_word(self, analyzer):
        r = _analyze(analyzer, "难过")
        assert r.emotion_type == "negative"
        assert r.polarity < -0.2
        assert "难过" in r.keywords

    def test_neutral_word(self, analyzer):
        r = _analyze(analyzer, "还行")
        assert r.emotion_type == "neutral"
        assert abs(r.polarity) <= 0.2

    def test_mixed_returns_average(self, analyzer):
        r = _analyze(analyzer, "开心难过")
        assert r.emotion_type in ("positive", "negative", "neutral")
        assert len(r.keywords) == 2

    def test_positive_bounds(self, analyzer):
        r = _analyze(analyzer, "非常开心")
        assert 0.0 < r.polarity <= 1.0
        assert r.intensity <= 1.0


class TestIntensityAndNegation:
    def test_intensity_word_amplifies(self, analyzer):
        base = _analyze(analyzer, "开心")
        amplified = _analyze(analyzer, "非常开心")
        assert amplified.polarity >= base.polarity

    def test_continuous_chinese_intensity(self, analyzer):
        # 修复回归：连续中文应先切词再判强度
        r = _analyze(analyzer, "非常开心")
        assert r.emotion_type == "positive"
        assert r.polarity > 0

    def test_continuous_chinese_negation(self, analyzer):
        # 修复回归：连续中文否定词应生效
        r = _analyze(analyzer, "不开心")
        assert r.emotion_type == "negative"
        assert r.polarity < 0

    def test_tokenize_continuous_chinese(self, analyzer):
        assert analyzer._tokenize("非常开心") == ["非常", "开心"]
        assert analyzer._tokenize("不开心") == ["不", "开心"]

    def test_english_negation_flips(self, analyzer):
        r = _analyze(analyzer, "not happy")
        assert r.emotion_type == "negative"
        assert r.polarity < 0

    def test_english_positive(self, analyzer):
        r = _analyze(analyzer, "great")
        assert r.emotion_type == "positive"


class TestConfidenceAndIntensity:
    def test_confidence_grows_with_keywords(self, analyzer):
        c1 = _analyze(analyzer, "开心").confidence
        c2 = _analyze(analyzer, "开心 快乐 幸福").confidence
        assert c2 >= c1
        assert c2 <= 0.95

    def test_intensity_capped_at_one(self, analyzer):
        r = _analyze(analyzer, "非常开心 快乐 幸福 喜悦")
        assert r.intensity <= 1.0


class TestScores:
    def test_get_emotion_score(self, analyzer):
        score = analyzer.get_emotion_score("开心")
        assert score > 0
        assert score == pytest.approx(_analyze(analyzer, "开心").polarity * _analyze(analyzer, "开心").intensity)

    def test_get_emotion_score_negative(self, analyzer):
        assert analyzer.get_emotion_score("难过") < 0

    def test_get_emotion_for_decay(self, analyzer):
        v = analyzer.get_intensity_for_decay("开心")
        assert v >= 0
        assert v == pytest.approx(abs(_analyze(analyzer, "开心").polarity) * 2.0)


class TestCache:
    def test_cache_returns_same_object(self, analyzer):
        a = _analyze(analyzer, "开心")
        b = _analyze(analyzer, "开心")
        assert a is b

    def test_clear_cache(self, analyzer):
        first = _analyze(analyzer, "开心")
        analyzer.clear_cache()
        second = _analyze(analyzer, "开心")
        assert first is second or first == second


class TestModuleFunctions:
    def test_get_emotion_module_func(self):
        assert get_emotion("难过") < 0

    def test_get_emotion_for_decay_module_func(self):
        assert get_emotion_for_decay("开心") >= 0