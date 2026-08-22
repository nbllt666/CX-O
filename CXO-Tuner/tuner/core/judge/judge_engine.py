"""LLM-as-a-Judge 裁判引擎（pairwise）。

用第三方 LLM（OpenAI 兼容 /v1/chat/completions）对同一条 prompt 的两个候选回复做
三维打分对比，并返回 {chosen_index, score_left, score_right, dimensions, reasoning}
的 JSON 判定结果。

设计要点：
  - 懒加载：requests 仅在真正调用时 import；构造 JudgeEngine 零网络副作用。
  - 严格 JSON 解析 + 回退（词/位置匹配）；解析失败给出可读错误，不裸抛。
  - _compare 恒返回 JudgeResult（内部捕获异常并写入 error 字段），便于上层管道
    逐条容错继续，不被单条样本卡死。

真实 LLM 调用不在本离线环境实跑，测试全部通过 mock `_call_llm` 验证。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tuner.config import TunerConfig

# 当 config.judge_model 为空时的默认裁判模型
DEFAULT_JUDGE_MODEL = "Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4"

# 三维评分维度键
DIMENSION_KEYS = ("persona", "emotional_value", "logic_fact")

_SYSTEM_PROMPT = (
    "你是严格的回复质量裁判。请从以下三个维度为同一条用户提问的两条候选回复分别评分（0-10，可含一位小数）：\n"
    "1. persona（人设贴合度）：回复是否贴合给定的角色人设与性格。\n"
    "2. emotional_value（情绪价值）：回复是否提供情感共鸣、温度与陪伴感。\n"
    "3. logic_fact（逻辑与事实）：回复是否逻辑自洽、事实准确。\n"
    "综合三维评分选出整体更优的回复：chosen_index 取 0（选择候选 A）或 1（选择候选 B）。\n"
    "必须严格输出单个 JSON 对象，不要输出任何 JSON 以外的文字。JSON 字段如下：\n"
    '{"chosen_index": 0或1, "score_left": 0-10, "score_right": 0-10, '
    '"dimensions": {"persona": 0-10, "emotional_value": 0-10, "logic_fact": 0-10}, '
    '"reasoning": "简要理由"}'
)


class JudgeError(RuntimeError):
    """裁判引擎错误基类。"""


class JudgeCallError(JudgeError):
    """上游 LLM 调用失败（网络 / 超时 / 非 2xx / 响应结构异常）。"""


class JudgeParseError(JudgeError):
    """裁判输出无法解析为约定 JSON。携带可读说明。"""


@dataclass
class JudgeResult:
    """一次 pairwise 裁判判定结果。

    chosen_index：0 表示选择 left（候选 A），1 表示选择 right（候选 B）；
    解析失败时为 None。error 非空表示本次判定失败。
    """

    chosen_index: Optional[int]
    score_left: float = 0.0
    score_right: float = 0.0
    dimensions: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    error: Optional[str] = None
    raw: Optional[str] = None


class JudgeEngine:
    """LLM-as-a-Judge 裁判引擎（OpenAI 兼容接口）。"""

    def __init__(
        self,
        config: TunerConfig,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.judge_model = (config.judge_model or "").strip() or DEFAULT_JUDGE_MODEL
        # 默认从 config.vllm_url 推导裁判端点（vLLM OpenAI 兼容服务）
        base = (endpoint if endpoint is not None else getattr(config, "vllm_url", "")) or ""
        self.endpoint = base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- 对外入口 -------------------------------------------------------------
    def _compare(
        self,
        left_response: str,
        right_response: str,
        prompt: str,
        character_card_hint: Optional[str] = None,
    ) -> JudgeResult:
        """比较两条候选回复，返回 JudgeResult（永不抛异常）。"""
        messages = self._build_messages(left_response, right_response, prompt, character_card_hint)
        try:
            content = self._call_llm(messages)
        except JudgeCallError as exc:
            return JudgeResult(
                chosen_index=None, error=f"裁判模型调用失败: {exc}", raw=None
            )
        try:
            chosen, sl, sr, dims, reason = self._parse_verdict(content)
        except JudgeParseError as exc:
            return JudgeResult(chosen_index=None, error=str(exc), raw=content)
        return JudgeResult(
            chosen_index=chosen, score_left=sl, score_right=sr,
            dimensions=dims, reasoning=reason, raw=content,
        )

    # -- 提示词构造 -------------------------------------------------------------
    def _build_messages(
        self,
        left_response: str,
        right_response: str,
        prompt: str,
        character_card_hint: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        user = ""
        if character_card_hint and character_card_hint.strip():
            user += f"【角色人设提示】\n{character_card_hint.strip()}\n\n"
        user += (
            f"【用户提问】\n{prompt}\n\n"
            f"【候选回复 A（左）】\n{left_response}\n\n"
            f"【候选回复 B（右）】\n{right_response}\n\n"
            "请输出评分 JSON。"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    # -- 懒加载 LLM 调用 -------------------------------------------------------
    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """调用 OpenAI 兼容 /v1/chat/completions，返回 assistant 文本。

        requests 在此处懒加载。所有失败归一为 JudgeCallError。
        """
        if not self.endpoint:
            raise JudgeCallError(
                f"裁判端点未配置（config.vllm_url 为空），无法访问模型 '{self.judge_model}'"
            )
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise JudgeCallError("缺少 requests 库，无法调用裁判模型") from exc

        url = f"{self.endpoint}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.judge_model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 512,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except json.JSONDecodeError as exc:  # 非 JSON 响应体
            raise JudgeCallError("裁判服务返回了非 JSON 响应") from exc
        except Exception as exc:
            raise JudgeCallError(f"{type(exc).__name__}: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise JudgeCallError("裁判响应缺少 choices[0].message.content 字段") from exc

    # -- JSON 解析与回退 --------------------------------------------------------
    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any]:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise JudgeParseError("裁判输出中未找到 JSON 对象")
        raw = content[start : end + 1]
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JudgeParseError(f"裁判输出 JSON 解析失败: {exc}") from exc
        if not isinstance(obj, dict):
            raise JudgeParseError("裁判输出 JSON 顶层类型必须为对象")
        return obj

    @staticmethod
    def _coerce_index(value: Any) -> Optional[int]:
        if value in (0, 1) or value in (False, True):
            return int(value)
        try:
            iv = int(value)
        except (TypeError, ValueError):
            return None
        return iv if iv in (0, 1) else None

    @staticmethod
    def _coerce_score(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_dimensions(value: Any) -> Dict[str, Optional[float]]:
        if not isinstance(value, dict):
            return {k: None for k in DIMENSION_KEYS}
        return {k: JudgeEngine._coerce_score(value.get(k)) for k in DIMENSION_KEYS}

    @staticmethod
    def _match_word_chosen(content: str) -> Optional[int]:
        """坏 JSON / 非 JSON 时的词回退：识别 left/right/0/1 方向的优选指示。"""
        lower = content.lower()
        # 若输出形如(解析失败的)JSON 对象，字段名会被误判为方向，视为不可判定
        if any(k in content for k in ('"score_left"', '"score_right"', '"dimensions"', '"reasoning"', '"chosen_index"')):
            return None
        # 明确的 chosen_index 文本指示
        m = re.search(r"chosen[_ ]?index['\":=]?\s*([01])", lower)
        if m:
            return int(m.group(1))
        has_better = any(
            k in lower for k in ("better", "winner", "chosen", "preferred", "best", "superior", "更优", "更好", "更出色", "更佳")
        )
        if not has_better:
            return None
        right = ("right" in lower) or ("右边" in content) or ("右侧" in content)
        left = ("left" in lower) or ("左边" in content) or ("左侧" in content)
        if right and not left:
            return 1
        if left and not right:
            return 0
        return None

    def _parse_verdict(self, content: str):
        """严格 JSON 解析；失败走 score 推断与词回退；全部失败抛 JudgeParseError。

        Returns:
            (chosen_index, score_left, score_right, dimensions, reasoning)
        """
        obj: Optional[Dict[str, Any]] = None
        try:
            obj = self._extract_json(content)
        except JudgeParseError:
            obj = None
        if isinstance(obj, dict):
            dims = self._coerce_dimensions(obj.get("dimensions"))
            reasoning = str(obj.get("reasoning") or "")
            ci = self._coerce_index(obj.get("chosen_index"))
            if ci is not None:
                sl = self._coerce_score(obj.get("score_left")) or 0.0
                sr = self._coerce_score(obj.get("score_right")) or 0.0
                return ci, sl, sr, dims, reasoning
            sl = self._coerce_score(obj.get("score_left"))
            sr = self._coerce_score(obj.get("score_right"))
            if sl is not None and sr is not None and sl != sr:
                return (0, sl, sr, dims, reasoning) if sl > sr else (1, sl, sr, dims, reasoning)
        ci = self._match_word_chosen(content)
        if ci is not None:
            return ci, 0.0, 0.0, {k: None for k in DIMENSION_KEYS}, ""
        snippet = _truncate(content or "", 200)
        raise JudgeParseError(
            "裁判输出无法解析为 {chosen_index, score_left, score_right, dimensions, reasoning}。"
            f"原始输出（截断）: {snippet}"
        )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"