"""LLM 自然语言情感指令服务接口契约存根（零实现，仅签名）。

源真理: public/schema/emotion_instruction.schema.json + server/services/emotion_instruction_service.py
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。
契约版本: 1.1.0（MINOR：EmotionInstruction 补 raw/speed/volume 字段，generate_instruction 补 async 标注，
补齐 strip_instruction/set_instruction_generator/get_supported_legacy_markers/validate_explicit_instruction 超集函数）

职责：在提示词组装/语音编排前生成独立 tts_instruction，与 reply_text 分离；
具备长度、置信度、敏感内容与非法字段校验；非法 JSON/超时/低置信度/服务不可用
回退中性指令。旧 [emotion:*]/Orpheus XML 标签仅在迁移边界转换，不作为新 Provider 协议。
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from qwen3_tts_provider import EmotionInstructionInvalidError, InvalidRequestError

__all__ = [
    "EmotionInstruction",
    "generate_instruction", "convert_legacy_marker",
    "strip_instruction", "set_instruction_generator",
    "get_supported_legacy_markers", "validate_explicit_instruction",
]


class EmotionInstruction:
    """情感指令（对应 emotion_instruction.schema.json）。"""

    text: str
    intensity: float = 0.5
    confidence: float = 0.5
    neutral: bool = False
    source: str = "llm"  # llm | fallback | legacy_migration
    raw: Optional[str] = None
    speed: float = 1.0   # 真实语速倍率（0.5~2.0）
    volume: float = 1.0  # 音量倍率（0.1~2.0）

    def to_dict(self) -> dict:
        """序列化为公开形状（仅含非空字段，符合 schema；raw 非空时才输出）。"""
        ...

    def to_provider_projection(self) -> dict:
        """返回 tts_instruction 降维投影（仅 text + 可选 intensity/confidence/neutral，不含 source/raw）。"""
        ...


async def generate_instruction(
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


def strip_instruction(reply_text: str) -> str:
    """从回复文本中剥离 <tts_instruction> 标记，返回干净的 reply_text（仅移除标记，文本不改写）。"""
    ...


def set_instruction_generator(fn: Optional[Callable[..., Any]]) -> None:
    """注入/清除 LLM 指令生成器（可选兜底路径）。

    fn 签名：``async fn(reply_text: str, character_context: Optional[str],
    conversation_context: Optional[str]) -> dict | EmotionInstruction``。
    """
    ...


def get_supported_legacy_markers() -> List[str]:
    """返回支持迁移的旧情感名称（[emotion:name] 与 Orpheus XML 标签并集，排序后）。"""
    ...


def validate_explicit_instruction(text: str) -> None:
    """Orchestrator 入口对调用方显式传入的指令做契约校验。

    Raises:
        InvalidRequestError: 指令缺失或为空（422）。
        EmotionInstructionInvalidError: 指令超长（上限 200）或含敏感/注入内容。
    """
    ...


def convert_legacy_marker(marker: str) -> EmotionInstruction:
    """迁移边界：将旧 [emotion:*] 或 Orpheus XML 标签转换为自然语言指令（source=legacy_migration）。"""
    ...