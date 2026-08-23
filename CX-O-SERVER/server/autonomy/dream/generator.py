"""CX-O-Dream 联想生成（server/autonomy/dream/generator.py）。

调用 model_router.get_client(config.model)（默认 summary 模型，不占用主模型槽位），
温度 config.dream_temperature（默认 0.9），输出结构化 JSON 候选
{content, emotion_shift, associated_entities}，单次会话产出 config.candidates_per_session 条。

JSON 健壮性：剥离 ```json 代码块、取首个合法 JSON 对象；单条解析失败重试一次，
仍失败则丢弃该条并记告警日志，不中断整次会话（spec "联想生成（summary 模型）"）。

模型不可用降级（spec "模型不可用降级"）：
- model_router 为 None / get_client 抛异常 / client 为 None → 返回空列表 + 告警
- 单条模型调用异常/返回 error → 该条重试后丢弃，会话继续
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from server.autonomy.dream.config import DreamConfig

logger = logging.getLogger(__name__)

# 确定性启发式 lucidity 的取值区间（内容无关，仅与素材/内容一致即可）
_LUCIDITY_MIN = 0.3
_LUCIDITY_MAX = 0.95

_SYSTEM_PROMPT = (
    "你是潜意识联想引擎。基于用户提供的近期素材与情绪基调，进行第一人称的梦境联想。"
    "输出必须是联想、意象、情绪化的非事实陈述，禁止断言用户的真实经历。"
    "只输出一个 JSON 对象，字段为："
    '{"content": 联想内容, "emotion_shift": {"valence": 情绪效价, "arousal": 唤醒度}, '
    '"associated_entities": [关联实体数组], "lucidity_score": 清醒度}。'
    "不要输出任何多余文字或解释。"
)


@dataclass
class DreamCandidate:
    """一条梦境联想候选（生成器输出，供 D7 闸门过滤）。"""

    content: str
    emotion_shift: Dict[str, float]
    associated_entities: List[str]
    lucidity_score: float
    session_id: str


class DreamGenerator:
    """梦境联想生成器（summary 模型）。"""

    def __init__(self, model_router=None, config=None):
        self._model_router = model_router
        self._config = config or DreamConfig()

    async def generate(self, snapshot) -> List[DreamCandidate]:
        """基于素材快照生成一批梦境候选。

        Args:
            snapshot: DreamMaterialSnapshot（或具备 memories / isolated_entities /
                emotion_baseline 属性的对象）

        Returns:
            DreamCandidate 列表；模型不可用或全部失败时返回空列表（不抛异常）
        """
        count = max(int(self._config.candidates_per_session), 0)
        if count <= 0:
            return []
        if self._model_router is None:
            logger.warning("梦境生成：模型路由器不可用，本次会话降级为空列表")
            return []
        try:
            client = self._model_router.get_client(self._config.model)
        except Exception as e:
            logger.warning(f"梦境生成：获取模型客户端 {self._config.model} 失败: {e}")
            return []
        if client is None:
            logger.warning(f"梦境生成：模型客户端 {self._config.model} 不可用，降级为空列表")
            return []

        session_id = uuid.uuid4().hex
        prompt = self._build_prompt(snapshot)
        candidates: List[DreamCandidate] = []
        for index in range(count):
            candidate = await self._generate_one(client, prompt, session_id)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _generate_one(
        self, client, prompt: str, session_id: str
    ) -> Optional[DreamCandidate]:
        """生成单条候选：首次 + 重试一次，仍失败丢弃（不中断会话）。"""
        for attempt in (1, 2):
            text = await self._call_model(client, prompt)
            obj = self._parse_candidate(text)
            if obj is not None:
                return self._to_candidate(obj, session_id)
            if attempt == 1:
                logger.warning("梦境生成：候选 JSON 解析失败，重试一次")
        logger.warning("梦境生成：候选重试后仍解析失败，丢弃该条（不中断会话）")
        return None

    async def _call_model(self, client, prompt: str) -> Optional[str]:
        """调用模型客户端，返回文本内容；调用异常/错误返回 None。"""
        try:
            response = await client.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                temperature=self._config.dream_temperature,
            )
        except Exception as e:
            logger.warning(f"梦境生成：模型调用异常: {e}")
            return None
        if response is None:
            return None
        if getattr(response, "error", None):
            logger.warning(f"梦境生成：模型返回错误: {response.error}")
            return None
        return getattr(response, "content", "") or ""

    def _build_prompt(self, snapshot) -> str:
        memories = getattr(snapshot, "memories", None) or []
        entities = getattr(snapshot, "isolated_entities", None) or []
        baseline = getattr(snapshot, "emotion_baseline", None) or 0.0

        memory_lines = []
        for mem in memories:
            if isinstance(mem, dict):
                content = str(mem.get("content") or "")
                created = str(mem.get("created_at") or "")
            else:
                content = str(mem or "")
                created = ""
            line = f"- [{created}] {content}".strip()
            memory_lines.append(line)
        memory_summary = "\n".join(memory_lines) if memory_lines else "（无近期边缘素材）"
        entity_summary = "、".join(str(e) for e in entities) if entities else "（无孤立实体）"

        return (
            "以下是你潜意识联想的素材摘要与情绪基调。请以第一人称潜意识联想，"
            "输出 {n} 条互不重复的梦境候选，每条严格为一个 JSON 对象"
            "（不要输出任何多余文字）：\n"
            "【边缘记忆素材】\n{mem}\n"
            "【孤立实体】\n{ent}\n"
            "【情绪基调】emotion_baseline = {emo}\n"
            "要求：第一人称潜意识联想、非事实陈述、意象化与情绪化。"
        ).format(
            n=self._config.candidates_per_session,
            mem=memory_summary,
            ent=entity_summary,
            emo=baseline,
        )

    @staticmethod
    def _parse_candidate(text: Optional[str]) -> Optional[Dict]:
        if not text:
            return None
        obj = _extract_json_object(text)
        if not isinstance(obj, dict) or not str(obj.get("content") or "").strip():
            return None
        return obj

    @staticmethod
    def _to_candidate(obj: Dict, session_id: str) -> DreamCandidate:
        content = str(obj.get("content") or "").strip()
        emotion_shift = obj.get("emotion_shift")
        if not isinstance(emotion_shift, dict):
            emotion_shift = {}
        try:
            valence = float(emotion_shift.get("valence") or 0.0)
        except (TypeError, ValueError):
            valence = 0.0
        try:
            arousal = float(emotion_shift.get("arousal") or 0.0)
        except (TypeError, ValueError):
            arousal = 0.0
        entities = obj.get("associated_entities")
        if not isinstance(entities, list):
            entities = []
        entities = [str(e) for e in entities]
        return DreamCandidate(
            content=content,
            emotion_shift={"valence": valence, "arousal": arousal},
            associated_entities=entities,
            lucidity_score=_lucidity_score(obj, content),
            session_id=session_id,
        )


def _extract_json_object(text: str) -> Any:
    """剥离代码块后，取首个合法 JSON 对象（容错解析）。

    兼容：整体即 JSON、```json 代码块包裹、前后含说明文字。
    """
    fence = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1)
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (ValueError, TypeError):
        pass
    # 扫描取首个合法 JSON 对象（兼容前/后有多余说明文字）
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if ch in "{[":
            try:
                obj, end = decoder.raw_decode(text, idx)
                if isinstance(obj, dict):
                    return obj
                idx = end
                continue
            except ValueError:
                pass
        idx += 1
    return None


def _lucidity_score(obj: Dict, content: str) -> float:
    """lucidity_score：优先取 JSON 中显式值；缺失时用内容哈希做确定性启发式。"""
    raw = obj.get("lucidity_score")
    if raw is not None:
        try:
            val = float(raw)
            if 0.0 <= val <= 1.0:
                return round(val, 3)
        except (TypeError, ValueError):
            pass
    digest = hashlib.sha256((content or "").encode("utf-8")).digest()
    ratio = digest[0] / 255.0
    return round(_LUCIDITY_MIN + ratio * (_LUCIDITY_MAX - _LUCIDITY_MIN), 3)
