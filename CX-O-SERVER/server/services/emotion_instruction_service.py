"""LLM 自然语言情感指令服务（Task 4）。

严格匹配 `public/interface_stub/emotion_instruction_service.pyi` 的签名，
源真理为三层契约（emotion_instruction.schema.json + qwen3_tts_error_codes +
speech_synthesis_request.schema.json 的 tts_instruction 降维投影）。

职责（按 spec Task 4 冻结决策——LLM 直接和消息一起生成自然语言指令）：
- 在语音编排前从 LLM 回复文本中剥离出独立 ``tts_instruction``，与 ``reply_text`` 分离。
- 内嵌指令格式：``<tts_instruction>自然语言情感/韵律表达</tts_instruction>``，
  内容可为纯文本或 JSON（``{"text": "...", "intensity": 0.x, "confidence": 0.x}``）。
- 结构化解析：支持纯文本、Markdown 围栏 JSON、裸 JSON；非法 JSON 回退。
- 约束：长度 maxLength 200、敏感/注入内容拦截、intensity/confidence 收敛到 [0,1]。
- 置信度校验：低置信度回退中性指令（neutral=true）。
- 旧 ``[emotion:*]`` 与 Orpheus XML 标签仅作迁移边界兼容输入（source=legacy_migration），
  不再作为新 Provider 协议。
- 可选 LLM 生成器兜底：未发现内嵌指令时，若注入生成器则调用其生成（超时/异常回退中性）。

抛错边界（与 qwen3_tts_error_codes.EMOTION_INSTRUCTION_INVALID 区分，见契约）：
- 生成/解析路径回退：非法 JSON/超时/低置信度/服务不可用 → 不抛错，返回 neutral=true 中性指令。
- 显式校验抛错：调用方在 Orchestrator 入口传入非法字段（超长/敏感内容/非法结构）时抛
  ``EmotionInstructionInvalidError``。本服务仅负责"本服务生成的指令"的解析与回退。

编码规范：文件路径用 os.path.dirname(os.path.abspath(__file__)) 解析；配置经
get_settings() 统一访问；异步用 async/await，禁止子线程 asyncio+aiohttp。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from server.qwen3_tts_provider import (
    EmotionInstructionInvalidError,
    InvalidRequestError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "EmotionInstruction",
    "generate_instruction",
    "convert_legacy_marker",
    "strip_instruction",
    "set_instruction_generator",
    "get_supported_legacy_markers",
]

# 指令长度上限（契约 emotion_instruction.schema.json text.maxLength=200）
MAX_INSTRUCTION_LENGTH = 200
# 可选 LLM 生成器超时（秒）
LLM_GENERATOR_TIMEOUT = 5.0

# 内嵌指令标记正则：<tts_instruction>...</tts_instruction>
_TTS_INSTRUCTION_RE = re.compile(r"<tts_instruction\s*>([\s\S]*?)</tts_instruction>")

# 旧 [emotion:name] 标记正则（迁移边界）
_LEGACY_EMOTION_RE = re.compile(r"\[emotion:([^\]]+)\]")
# Orpheus XML 情感标签正则：<emotion>...</emotion>（迁移边界）
_ORPHEUS_XML_RE = re.compile(r"<([a-z_]+)>([\s\S]*?)</\1>")

# 旧情感名 → Qwen3 自然语言表达映射（迁移边界兼容）
_LEGACY_EMOTION_TO_NL = {
    "happy": "用开心、愉快的语气说",
    "sad": "用悲伤、低沉的语气说",
    "angry": "用愤怒、激动的语气说",
    "surprised": "用惊讶、意外的语气说",
    "fear": "用恐惧、紧张的语气说",
    "disgust": "用厌恶、反感的语气说",
    "neutral": "用平静、自然的语气说",
    "excited": "用兴奋、跃动的语气说",
    "calm": "用沉稳、安定的语气说",
    "whisper": "用轻声细语、私密低语的语气说",
    "shout": "用大声喊叫、强烈爆发的语气说",
    "laugh": "用大笑、开怀的语气说",
    "cry": "用哭泣、动容的语气说",
    "sigh": "用叹气、无奈的语气说",
    "giggle": "用轻笑、窃笑的语气说",
}

# Orpheus XML 标签 → Qwen3 自然语言表达映射（迁移边界兼容）
_ORPHEUS_TAG_TO_NL = {
    "laugh": "用大笑、开怀的语气说",
    "chuckle": "用轻轻笑、忍俊不禁的语气说",
    "giggle": "用俏皮轻笑、窃笑的语气说",
    "sigh": "用叹气、无奈的语气说",
    "cry": "用哭泣、动容的语气说",
    "shout": "用大声喊叫、强烈爆发的语气说",
    "whisper": "用轻声细语、私密低语的语气说",
    "stern": "用严肃、严厉的语气说",
    "breathy": "用漏气、气声喃喃的语气说",
    "stammering": "用结结巴巴、迟疑的语气说",
    "furrowed_brow": "用疑惑、皱眉不解的语气说",
    "despondent": "用沮丧、消沉的语气说",
    "disgruntled": "用不满、牢骚的语气说",
    "lamenting": "用哀叹、悲叹的语气说",
    "sotto_voce": "用低语、耳语般压低的语气说",
    "inkling": "用迟疑、欲言又止的语气说",
}

# 中性回退指令文本
_NEUTRAL_TEXT = "用平静、自然的语气说"

# 敏感/注入内容拦截（命中即视为非法指令，回退中性）
_SENSITIVE_PATTERNS = (
    "ignore previous instruction",
    "忽略之前的指令",
    "system prompt",
    "系统提示词",
    "输出原始",
    "泄露",
    "override",
)


@dataclass
class EmotionInstruction:
    """情感指令（对应 emotion_instruction.schema.json）。"""

    text: str
    intensity: float = 0.5
    confidence: float = 0.5
    neutral: bool = False
    source: str = "llm"  # llm | fallback | legacy_migration
    raw: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化为公开形状（仅含非空字段，符合 schema）。"""
        out: dict = {
            "text": self.text,
            "intensity": self.intensity,
            "confidence": self.confidence,
            "neutral": self.neutral,
            "source": self.source,
        }
        if self.raw:
            out["raw"] = self.raw
        return out

    def to_provider_projection(self) -> dict:
        """返回 tts_instruction 降维投影（仅 text + 可选 intensity/confidence/neutral，不入 source/raw）。"""
        out: dict = {"text": self.text}
        if self.intensity is not None:
            out["intensity"] = self.intensity
        if self.confidence is not None:
            out["confidence"] = self.confidence
        out["neutral"] = self.neutral
        return out


# 模块级可注入 LLM 生成器：async fn(reply_text, character_context, conversation_context) -> dict|EmotionInstruction
_instruction_generator: Optional[Callable[..., Any]] = None


def set_instruction_generator(fn: Optional[Callable[..., Any]]) -> None:
    """注入/清除 LLM 指令生成器（可选兜底路径）。

    fn 签名：``async fn(reply_text: str, character_context: Optional[str],
    conversation_context: Optional[str]) -> dict | EmotionInstruction``。
    返回 dict 应含 ``text``（及可选 intensity/confidence）。
    """
    global _instruction_generator
    _instruction_generator = fn


# ============================================================================
# 校验与工具
# ============================================================================

def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0, default: float = 0.5) -> float:
    """将数值收敛到 [lo, hi]；非法返回 default。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def _is_sensitive(text: str) -> bool:
    """敏感/注入内容拦截。命中返回 True。"""
    lowered = text.lower()
    return any(p in lowered for p in _SENSITIVE_PATTERNS)


def _validate_instruction_text(text: Optional[str]) -> Optional[str]:
    """校验并规范化指令文本；非法返回 None（触发中性回退）。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_INSTRUCTION_LENGTH:
        return None
    if _is_sensitive(text):
        return None
    # 控制字符（除常见空白）视为非法
    if any(ord(c) < 32 and c not in "\t\n\r" for c in text):
        return None
    return text


def _build_instruction(
    text: str,
    intensity: float = 0.5,
    confidence: float = 0.5,
    neutral: bool = False,
    source: str = "llm",
    raw: Optional[str] = None,
) -> EmotionInstruction:
    """按契约构建 EmotionInstruction，intensity/confidence 收敛到 [0,1]。"""
    return EmotionInstruction(
        text=text,
        intensity=_clamp(intensity),
        confidence=_clamp(confidence),
        neutral=bool(neutral),
        source=source,
        raw=raw,
    )


def _neutral_fallback() -> EmotionInstruction:
    """返回中性回退指令（neutral=true，source=fallback）。"""
    return _build_instruction(_NEUTRAL_TEXT, intensity=0.3, confidence=0.0, neutral=True, source="fallback")


# ============================================================================
# 内嵌指令解析
# ============================================================================

def _parse_instruction_content(content: str) -> Optional[Tuple[str, float, float, float]]:
    """解析 <tts_instruction> 块内容，返回 (text, intensity, confidence, neutral)。

    支持纯文本 / Markdown 围栏 JSON / 裸 JSON。非法返回 None（触发中性回退）。
    """
    content = content.strip()
    if not content:
        return None

    # 尝试 JSON 解析（先剥 Markdown 围栏）
    json_candidate = content
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if fence:
        json_candidate = fence.group(1).strip()
    try:
        data = json.loads(json_candidate)
        if isinstance(data, dict):
            text = _validate_instruction_text(data.get("text"))
            if text is None:
                return None
            intensity = _clamp(data.get("intensity"), default=0.5)
            confidence = _clamp(data.get("confidence"), default=0.5)
            neutral = bool(data.get("neutral", False))
            return (text, intensity, confidence, 1.0 if neutral else 0.0)
    except (json.JSONDecodeError, TypeError, ValueError):
        # JSON 形内容（以 { 或 [ 开头）解析失败 → 视为非法结构，回退中性，
        # 不得把残缺 JSON 当作纯文本指令。
        if json_candidate.strip().startswith(("{", "[")):
            return None

    # 纯文本
    text = _validate_instruction_text(content)
    if text is None:
        return None
    return (text, 0.5, 0.5, 0.0)


def _extract_embedded_instruction(reply_text: str) -> Optional[Tuple[str, float, float, float]]:
    """从回复文本中提取首个 <tts_instruction> 块并解析。"""
    match = _TTS_INSTRUCTION_RE.search(reply_text)
    if not match:
        return None
    return _parse_instruction_content(match.group(1))


def strip_instruction(reply_text: str) -> str:
    """从回复文本中剥离 <tts_instruction> 标记，返回干净的 reply_text。

    仅移除指令标记本身，其余文本原样保留（"文本不改写"保证）。
    """
    return _TTS_INSTRUCTION_RE.sub("", reply_text).strip()


# ============================================================================
# 旧标签迁移边界
# ============================================================================

def get_supported_legacy_markers() -> List[str]:
    """返回支持迁移的旧情感名称（[emotion:name] 与 Orpheus XML 标签）。"""
    return sorted(set(_LEGACY_EMOTION_TO_NL) | set(_ORPHEUS_TAG_TO_NL))


def _find_legacy_marker(reply_text: str) -> Optional[str]:
    """在回复文本中查找首个旧情感标记（[emotion:x] 或 Orpheus XML <x>）。

    返回原始匹配子串（供 convert_legacy_marker 二次解析），而非合成键。
    """
    m = _LEGACY_EMOTION_RE.search(reply_text)
    if m:
        return m.group(0)
    m = _ORPHEUS_XML_RE.search(reply_text)
    if m:
        return m.group(0)
    return None


def convert_legacy_marker(marker: str) -> EmotionInstruction:
    """迁移边界：将旧 [emotion:*] 或 Orpheus XML 标签转换为自然语言指令（source=legacy_migration）。

    Args:
        marker: 旧标签字符串，如 "[emotion:happy]" 或 "<laugh>...</laugh>"。

    Returns:
        转换后的 EmotionInstruction；无法识别的标签返回中性指令（source=fallback）。
    """
    if not isinstance(marker, str) or not marker.strip():
        return _neutral_fallback()

    nl_text: Optional[str] = None
    m = _LEGACY_EMOTION_RE.search(marker)
    if m:
        name = m.group(1).strip().lower()
        nl_text = _LEGACY_EMOTION_TO_NL.get(name)
    else:
        m = _ORPHEUS_XML_RE.search(marker)
        if m:
            name = m.group(1).strip().lower()
            nl_text = _ORPHEUS_TAG_TO_NL.get(name)

    if nl_text is None:
        return _neutral_fallback()
    return _build_instruction(nl_text, intensity=0.5, confidence=0.5, neutral=False, source="legacy_migration", raw=marker.strip())


# ============================================================================
# 主入口
# ============================================================================

async def generate_instruction(
    reply_text: str,
    character_context: Optional[str] = None,
    conversation_context: Optional[str] = None,
) -> EmotionInstruction:
    """生成自然语言 tts_instruction（Task 4 主入口）。

    流程：
    1. 解析回复文本内嵌 ``<tts_instruction>`` 块（LLM 直接和消息一起生成的路径）。
    2. 无内嵌指令时，检测旧 ``[emotion:*]`` / Orpheus XML 标签 → 迁移转换。
    3. 仍未命中且注入了 LLM 生成器 → 调用生成（超时/异常回退中性）。
    4. 全部未命中 → 返回中性指令（neutral=true）。

    Args:
        reply_text: LLM 原始回复文本（可能含内嵌指令标记）。
        character_context: 角色/人设上下文（可选，供 LLM 生成器兜底使用）。
        conversation_context: 对话上下文（可选，供 LLM 生成器兜底使用）。

    Returns:
        EmotionInstruction；生成/解析失败时返回 neutral=true 中性指令（不抛错）。
    """
    # 1. 内嵌指令（LLM 与消息一起生成的默认路径）
    parsed = _extract_embedded_instruction(reply_text)
    if parsed is not None:
        text, intensity, confidence, neutral_flag = parsed
        return _build_instruction(
            text,
            intensity=intensity,
            confidence=confidence,
            neutral=(neutral_flag == 1.0),
            source="llm",
            raw=reply_text[:200],
        )

    # 2. 旧标签迁移边界
    legacy = _find_legacy_marker(reply_text)
    if legacy is not None:
        return convert_legacy_marker(legacy)

    # 3. 可选 LLM 生成器兜底
    if _instruction_generator is not None:
        try:
            result = await asyncio.wait_for(
                _instruction_generator(reply_text, character_context, conversation_context),
                timeout=LLM_GENERATOR_TIMEOUT,
            )
            if isinstance(result, EmotionInstruction):
                return result
            if isinstance(result, dict):
                text = _validate_instruction_text(result.get("text"))
                if text is not None:
                    return _build_instruction(
                        text,
                        intensity=_clamp(result.get("intensity"), default=0.5),
                        confidence=_clamp(result.get("confidence"), default=0.5),
                        neutral=bool(result.get("neutral", False)),
                        source="llm",
                        raw=reply_text[:200],
                    )
        except asyncio.TimeoutError:
            logger.warning("LLM 指令生成器超时，回退中性指令")
        except Exception as e:  # noqa: BLE001 - 生成器异常统一回退
            logger.warning(f"LLM 指令生成器异常，回退中性指令: {e}")

    # 4. 中性回退
    return _neutral_fallback()


def validate_explicit_instruction(text: str) -> None:
    """Orchestrator 入口对调用方传入的显式指令做契约校验，非法抛 EmotionInstructionInvalidError。

    与 generate_instruction 的"本服务生成则回退"边界区分：调用方显式传入的非法字段在此抛错。
    """
    if not isinstance(text, str) or not text.strip():
        raise InvalidRequestError("tts_instruction 缺失或为空")
    if len(text) > MAX_INSTRUCTION_LENGTH:
        raise EmotionInstructionInvalidError(f"情感指令超长（上限 {MAX_INSTRUCTION_LENGTH}）")
    if _is_sensitive(text):
        raise EmotionInstructionInvalidError("情感指令含敏感/注入内容")