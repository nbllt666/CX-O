"""LLM 自然语言情感指令服务接口契约存根（零实现，仅签名）。

源真理: public/schema/emotion_instruction.schema.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。

职责：在提示词组装/语音编排前生成独立 tts_instruction，与 reply_text 分离；
具备长度、置信度、敏感内容与非法字段校验；非法 JSON/超时/低置信度/服务不可用
回退中性指令。旧 [emotion:*]/Orpheus XML 标签仅在迁移边界转换，不作为新 Provider 协议。
"""
from __future__ import annotations

from typing import Optional

from qwen3_tts_provider import EmotionInstructionInvalidError

__all__ = [
    "EmotionInstruction",
    "generate_instruction", "convert_legacy_marker",
]


class EmotionInstruction:
    """情感指令（对应 emotion_instruction.schema.json）。"""
    text: str
    intensity: float
    confidence: float
    neutral: bool
    source: str  # llm | fallback | legacy_migration


def generate_instruction(
    reply_text: str,
    character_context: Optional[str] = None,
    conversation_context: Optional[str] = None,
) -> EmotionInstruction:
    """生成自然语言 tts_instruction。

    抛错边界（与 qwen3_tts_error_codes.EMOTION_INSTRUCTION_INVALID 区分）：
    - 生成路径回退：LLM 非法 JSON / 超时 / 低置信度 / 服务不可用 → 不抛错，返回 neutral=true 中性指令。
    - 显式校验抛错：调用方传入的非法字段（超长/敏感内容/非法结构）在 Orchestrator 入口校验时抛
      EmotionInstructionInvalidError。二者以"非法字段是否由本服务生成"划分边界，避免遗漏到实现阶段。
    """
    ...


def convert_legacy_marker(marker: str) -> EmotionInstruction:
    """迁移边界：将旧 [emotion:*] 或 Orpheus XML 标签转换为自然语言指令（source=legacy_migration）。"""
    ...