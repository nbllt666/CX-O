import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class EmotionResult:
    polarity: float
    intensity: float
    emotion_type: str
    confidence: float
    keywords: List[str]


class EmotionAnalyzer:
    POSITIVE_PATTERNS = {
        "高兴": 0.9,
        "开心": 0.9,
        "快乐": 0.9,
        "喜悦": 0.85,
        "满意": 0.7,
        "喜欢": 0.8,
        "热爱": 0.95,
        "感谢": 0.75,
        "美好": 0.8,
        "棒": 0.85,
        "优秀": 0.85,
        "精彩": 0.8,
        "幸福": 0.9,
        "温暖": 0.75,
        "感动": 0.8,
        "惊喜": 0.85,
        "兴奋": 0.9,
        "骄傲": 0.8,
        "希望": 0.7,
        "期待": 0.65,
        "爱": 0.9,
        "happy": 0.85,
        "great": 0.8,
        "wonderful": 0.9,
    }

    NEGATIVE_PATTERNS = {
        "难过": 0.85,
        "悲伤": 0.9,
        "痛苦": 0.9,
        "失望": 0.75,
        "沮丧": 0.8,
        "生气": 0.9,
        "愤怒": 0.95,
        "讨厌": 0.8,
        "害怕": 0.8,
        "恐惧": 0.85,
        "担忧": 0.7,
        "焦虑": 0.8,
        "后悔": 0.75,
        "遗憾": 0.7,
        "无奈": 0.7,
        "烦躁": 0.75,
        "糟糕": 0.85,
        "sad": 0.85,
        "angry": 0.9,
        "bad": 0.7,
    }

    NEUTRAL_PATTERNS = {
        "正常": 0.0,
        "一般": 0.0,
        "普通": 0.0,
        "还行": 0.1,
        "还好": 0.1,
        "可以": 0.1,
        "fine": 0.1,
    }

    INTENSITY_WORDS = {
        "非常": 1.5,
        "特别": 1.4,
        "极其": 1.6,
        "相当": 1.3,
        "很": 1.2,
        "挺": 1.1,
        "稍微": 0.6,
        "有点": 0.5,
        "really": 1.5,
        "very": 1.3,
        "extremely": 1.6,
    }

    NEGATION_WORDS = {"不", "没", "无", "非", "未", "别", "not", "no", "never"}

    def __init__(self, use_llm: bool = False, llm_client=None):
        self.use_llm = use_llm
        self.llm_client = llm_client
        self._cache = {}

    def set_llm_client(self, llm_client):
        self.llm_client = llm_client
        self.use_llm = True

    async def analyze(self, text: str, context: str = "") -> EmotionResult:
        if not text or not text.strip():
            return EmotionResult(
                polarity=0.0, intensity=0.0, emotion_type="neutral", confidence=0.5, keywords=[]
            )

        cache_key = f"{text[:100]}:{context[:50]}" if context else text[:100]
        if cache_key in self._cache:
            return self._cache[cache_key]

        if self.use_llm and self.llm_client:
            result = await self._analyze_with_llm(text, context)
        else:
            result = self._analyze_with_rules(text)

        self._cache[cache_key] = result
        return result

    def _analyze_with_rules(self, text: str) -> EmotionResult:
        text = text.lower()
        words = re.findall(r"[\w\u4e00-\u9fff]+", text)

        total_score = 0.0
        matched_keywords = []
        negation_active = False
        intensity_multiplier = 1.0

        for i, word in enumerate(words):
            if word in self.NEGATION_WORDS:
                negation_active = True
                continue

            if word in self.INTENSITY_WORDS:
                intensity_multiplier = self.INTENSITY_WORDS[word]
                continue

            score = 0.0
            emotion_type = "neutral"

            if word in self.POSITIVE_PATTERNS:
                score = self.POSITIVE_PATTERNS[word]
                emotion_type = "positive"
            elif word in self.NEGATIVE_PATTERNS:
                score = -self.NEGATIVE_PATTERNS[word]
                emotion_type = "negative"
            elif word in self.NEUTRAL_PATTERNS:
                score = self.NEUTRAL_PATTERNS[word]
            else:
                continue

            if negation_active:
                score = -score * 0.8
                negation_active = False

            total_score += score * intensity_multiplier
            matched_keywords.append(word)
            intensity_multiplier = 1.0

        if matched_keywords:
            avg_score = total_score / len(matched_keywords)
        else:
            avg_score = 0.0

        polarity = max(-1.0, min(1.0, avg_score))
        intensity = min(1.0, abs(polarity) * (1 + len(matched_keywords) * 0.1))

        if polarity > 0.2:
            emotion_type = "positive"
        elif polarity < -0.2:
            emotion_type = "negative"
        else:
            emotion_type = "neutral"

        confidence = min(0.95, 0.5 + len(matched_keywords) * 0.1)

        return EmotionResult(
            polarity=round(polarity, 4),
            intensity=round(intensity, 4),
            emotion_type=emotion_type,
            confidence=round(confidence, 4),
            keywords=matched_keywords[:10],
        )

    def get_emotion_score(self, text: str) -> float:
        result = self._analyze_with_rules(text)
        return result.polarity * result.intensity

    def get_intensity_for_decay(self, text: str) -> float:
        result = self._analyze_with_rules(text)
        return abs(result.polarity) * 2.0

    def clear_cache(self):
        self._cache.clear()
        logger.info("情感分析缓存已清除")


emotion_analyzer = EmotionAnalyzer()


def get_emotion(text: str) -> float:
    return emotion_analyzer.get_emotion_score(text)


def get_emotion_for_decay(text: str) -> float:
    return emotion_analyzer.get_intensity_for_decay(text)
