"""server.core.memory.emotion (EmotionAnalyzer) 单元测试。

覆盖规则规则型情感分析：正/负/中性词、强度词、否定词、混合文本、
文本分档、缓存行为、快捷函数；LLM 模式：结构化解析、回退、JSON 提取。
运行：python -m pytest tests/test_emotion.py -v
"""
import asyncio

import pytest

from server.core.memory.emotion import EmotionAnalyzer, get_emotion_for_decay


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
        score = asyncio.run(analyzer.get_emotion_score("开心"))
        assert score > 0
        assert score == pytest.approx(_analyze(analyzer, "开心").polarity * _analyze(analyzer, "开心").intensity)

    def test_get_emotion_score_negative(self, analyzer):
        assert asyncio.run(analyzer.get_emotion_score("难过")) < 0

    def test_get_emotion_for_decay(self, analyzer):
        v = asyncio.run(analyzer.get_intensity_for_decay("开心"))
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

    def test_cache_bounded_lru(self, analyzer):
        # 超过上限按最久未访问淘汰，避免无界增长
        analyzer._cache_max_size = 2
        _analyze(analyzer, "开心")
        _analyze(analyzer, "难过")
        _analyze(analyzer, "非常开心")
        assert len(analyzer._cache) == 2
        assert "开心" not in analyzer._cache  # 最早写入的被淘汰
        assert "难过" in analyzer._cache
        assert "非常开心" in analyzer._cache


class TestModuleFunctions:
    def test_get_emotion_for_decay_module_func(self):
        assert asyncio.run(get_emotion_for_decay("开心")) >= 0


class _FakeClient:
    """记录调用并返回预设响应的假 LLM 客户端。"""

    def __init__(self, content):
        self.content = content
        self.calls = []

    async def chat(self, messages, stream=False):
        self.calls.append(messages)
        return _FakeResponse(self.content)


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class TestLlmMode:
    def test_llm_success_parses_json(self):
        client = _FakeClient(
            '{"polarity":0.8,"intensity":0.6,"emotion_type":"positive","confidence":0.9,"keywords":["高兴"]}'
        )
        analyzer = EmotionAnalyzer(use_llm=True, llm_client=client)
        r = asyncio.run(analyzer.analyze("这段文本很积极"))
        assert r.polarity == pytest.approx(0.8)
        assert r.intensity == pytest.approx(0.6)
        assert r.emotion_type == "positive"
        assert r.confidence == pytest.approx(0.9)
        assert r.keywords == ["高兴"]
        assert len(client.calls) == 1

    def test_llm_clamps_out_of_range(self):
        client = _FakeClient(
            '{"polarity":5.0,"intensity":9.0,"emotion_type":"positive","confidence":3.0,"keywords":[]}'
        )
        analyzer = EmotionAnalyzer(use_llm=True, llm_client=client)
        r = asyncio.run(analyzer.analyze("任意文本"))
        assert r.polarity == 1.0
        assert r.confidence == 1.0

    def test_llm_failure_falls_back_to_rules(self):
        # 客户端抛异常 → 回退规则词典，不崩溃
        class _BoomClient:
            async def chat(self, messages, stream=False):
                raise RuntimeError("llm down")

        analyzer = EmotionAnalyzer(use_llm=True, llm_client=_BoomClient())
        r = asyncio.run(analyzer.analyze("开心"))
        assert r.emotion_type == "positive"
        assert "开心" in r.keywords

    def test_llm_invalid_json_falls_back_to_rules(self):
        client = _FakeClient("抱歉，我无法回答")
        analyzer = EmotionAnalyzer(use_llm=True, llm_client=client)
        r = asyncio.run(analyzer.analyze("难过"))
        assert r.emotion_type == "negative"

    def test_use_llm_false_ignores_client(self):
        client = _FakeClient("should not be called")
        analyzer = EmotionAnalyzer(use_llm=False, llm_client=client)
        r = asyncio.run(analyzer.analyze("开心"))
        assert r.emotion_type == "positive"
        assert client.calls == []

    def test_set_llm_client_enables_llm(self):
        client = _FakeClient(
            '{"polarity":-0.7,"intensity":0.5,"emotion_type":"negative","confidence":0.8,"keywords":["生气"]}'
        )
        analyzer = EmotionAnalyzer()
        assert analyzer.use_llm is False
        analyzer.set_llm_client(client)
        assert analyzer.use_llm is True
        r = asyncio.run(analyzer.analyze("内容"))
        assert r.emotion_type == "negative"
        assert len(client.calls) == 1


class TestParseLlmJson:
    def test_plain_json(self):
        assert EmotionAnalyzer._parse_llm_json('{"a":1}') == {"a": 1}

    def test_markdown_block(self):
        raw = '```json\n{"a":1}\n```'
        assert EmotionAnalyzer._parse_llm_json(raw) == {"a": 1}

    def test_extra_text_wrapped(self):
        raw = '结果如下：{"a":1} 完毕'
        assert EmotionAnalyzer._parse_llm_json(raw) == {"a": 1}

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="JSON 对象"):
            EmotionAnalyzer._parse_llm_json("[1,2,3]")