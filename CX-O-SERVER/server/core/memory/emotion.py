"""记忆情感分析——基于文本的情感极性与强度分析。

默认使用摘要模型（LLM）进行情感分析，LLM 不可用或解析失败时回退到本地规则词典。
"""
import json
from dataclasses import dataclass
from typing import List

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class EmotionResult:
    """情感分析结果：极性、强度、类型、置信度与命中的关键词。"""
    polarity: float
    intensity: float
    emotion_type: str
    confidence: float
    keywords: List[str]


class EmotionAnalyzer:
    """文本情感分析器，基于内置的中/英文情感词典做贪心切词与极性/强度/类型判定，可选接入 LLM 模式。"""
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

    # 预构建的词典（按长度降序），用于贪心最长匹配切词
    _VOCAB = None

    @classmethod
    def _build_vocab(cls) -> List[str]:
        """构建并按长度降序排序的词典（最长匹配优先）。"""
        if cls._VOCAB is not None:
            return cls._VOCAB
        vocab = set()
        for d in (
            cls.POSITIVE_PATTERNS,
            cls.NEGATIVE_PATTERNS,
            cls.NEUTRAL_PATTERNS,
            cls.INTENSITY_WORDS,
        ):
            vocab.update(d.keys())
        vocab.update(cls.NEGATION_WORDS)
        cls._VOCAB = sorted(vocab, key=len, reverse=True)
        return cls._VOCAB

    def _tokenize(self, text: str) -> List[str]:
        """词典贪心切词。

        修复：原 `re.findall` 的「字母数字或中文字符连续匹配」会把连续中文
        （如「非常开心」）当作单个 token，导致强度词/否定词对中文复合短语
        永不生效。改为基于情感词典的贪心最长匹配 + 英文单词按字母数字切分。
        """
        text = text.lower()
        tokens: List[str] = []
        i = 0
        n = len(text)
        vocab = self._build_vocab()
        while i < n:
            ch = text[i]
            if ch.isascii() and ch.isalnum():
                j = i
                while j < n and text[j].isascii() and text[j].isalnum():
                    j += 1
                tokens.append(text[i:j])
                i = j
                continue
            for kw in vocab:
                if text.startswith(kw, i):
                    tokens.append(kw)
                    i += len(kw)
                    break
            else:
                i += 1
        return tokens

    def __init__(self, use_llm: bool = False, llm_client=None):
        """初始化情感分析器（可选启用 LLM 模式）。"""
        self.use_llm = use_llm
        self.llm_client = llm_client
        self._cache = {}

    def set_llm_client(self, llm_client):
        """注入摘要模型客户端并启用 LLM 情感分析模式。"""
        self.llm_client = llm_client
        self.use_llm = True

    async def analyze(self, text: str, context: str = "") -> EmotionResult:
        """分析文本情感。

        配置了 LLM 客户端时优先走摘要模型分析，否则或失败时回退规则词典。
        """
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

    async def _analyze_with_llm(self, text: str, context: str = "") -> EmotionResult:
        """使用摘要模型（LLM）进行情感分析，输出结构化 JSON 结果。

        LLM 调用或解析失败时回退到规则词典分析，保证分析流程稳定可用。
        """
        context_part = f"\n对话上下文（供参考）：\n{context}" if context.strip() else ""
        prompt = (
            "你是情感分析助手。请仅分析用户文本的情感倾向，输出严格 JSON 格式，不要输出任何额外文字。\n"
            f"用户文本：{text}\n"
            f"{context_part}\n"
            '输出格式：{"polarity":浮点数(-1到1), "intensity":浮点数(0到1), '
            '"emotion_type":"positive|negative|neutral", "confidence":浮点数(0到1), '
            '"keywords":["关键词1","关键词2"]}\n'
            "其中 polarity 为情感极性（正数积极、负数消极），intensity 为情感强度，"
            "emotion_type 为情感类型，confidence 为分析置信度，keywords 为命中的情感关键词列表。"
        )
        try:
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}], stream=False
            )
            content = response.content if hasattr(response, "content") else str(response)
            data = self._parse_llm_json(content)
            raw_polarity = float(data.get("polarity") or 0.0)
            confidence = float(data.get("confidence") or 0.5)
            return EmotionResult(
                polarity=max(-1.0, min(1.0, raw_polarity)),
                intensity=float(data.get("intensity") or 0.0),
                emotion_type=str(data.get("emotion_type") or "neutral"),
                confidence=max(0.0, min(1.0, confidence)),
                keywords=[str(k) for k in data.get("keywords", [])][:10],
            )
        except Exception as e:
            logger.warning(f"LLM 情感分析失败，回退规则分析: {e}")
            return self._analyze_with_rules(text)

    @staticmethod
    def _parse_llm_json(content: str) -> dict:
        """从 LLM 输出中提取 JSON 对象（容忍 markdown 代码块等包裹）。"""
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`").strip()
            if content.startswith("json"):
                content = content[4:].strip()
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            content = content[start : end + 1]
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("LLM 输出不是 JSON 对象")
        return data

    def _analyze_with_rules(self, text: str) -> EmotionResult:
        text = text.lower()
        words = self._tokenize(text)

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

    async def get_emotion_score(self, text: str) -> float:
        """返回文本情感极性分，即 polarity 与 intensity 的乘积。"""
        result = await self.analyze(text)
        return result.polarity * result.intensity

    async def get_intensity_for_decay(self, text: str) -> float:
        """返回用于记忆衰减的情感强度值，即情感极性绝对值的两倍。"""
        result = await self.analyze(text)
        return abs(result.polarity) * 2.0

    def clear_cache(self):
        """清空情感分析的文本缓存。"""
        self._cache.clear()
        logger.info("情感分析缓存已清除")


emotion_analyzer = EmotionAnalyzer()


def set_emotion_llm_client(client) -> None:
    """为全局情感分析器注入摘要模型客户端，启用 LLM 情感分析。"""
    emotion_analyzer.set_llm_client(client)


async def get_emotion_for_decay(text: str) -> float:
    """分析文本的情感强度值，供记忆衰减流程使用。"""
    return await emotion_analyzer.get_intensity_for_decay(text)
