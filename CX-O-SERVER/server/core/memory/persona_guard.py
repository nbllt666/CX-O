"""人格保护闸门：判定记忆是否允许被记忆管理 agent 遗忘（软删除）。

核心原则：遗忘 ≠ 删除。人格核心（永久记忆）、高情感印记与高频再激活的
记忆承载人格连续性，受闸门保护不可被 agent 工具遗忘；如需彻底清除只能
通过 REST API 显式硬删参数（soft_delete=false）操作，情感类记忆可考虑
归档（archive）作为替代。
"""

from typing import Any, Dict

from server.config import get_settings


def evaluate_persona_guard(memory: Dict[str, Any]) -> Dict[str, Any]:
    """评估给定记忆是否允许被遗忘（软删除）。

    判定规则（按顺序）：
    1. ``permanent`` 为真（1/True）→ 拒绝：人格核心记忆不可被 agent 遗忘；
    2. ``emotion_score`` ≥ persona_guard_emotion_threshold，或
       ``reactivation_count`` ≥ persona_guard_reactivation_threshold →
       拒绝：情感印记/高频再激活记忆受保护，建议归档替代；
    3. 其余 → 放行。

    阈值在每次调用时从配置读取（不做模块级缓存），便于测试中 monkeypatch。

    Args:
        memory: 记忆 dict。``emotion_score`` / ``reactivation_count`` 缺失
            或为 None 时按 0 处理。

    Returns:
        Dict[str, Any]: ``{"allowed": bool, "reason": str}``；放行时 reason
        为空字符串。
    """
    # None / 缺失字段安全处理：统一按 0 参与比较
    permanent = memory.get("permanent")
    emotion_score = memory.get("emotion_score") or 0.0
    reactivation_count = memory.get("reactivation_count") or 0

    # 规则1：永久记忆属于人格核心，记忆管理助手不可遗忘
    if bool(permanent):
        return {
            "allowed": False,
            "reason": (
                "该记忆属于人格核心（永久记忆），记忆管理助手不可遗忘；"
                "如需处理请通过 REST API 显式硬删参数（soft_delete=false）操作"
            ),
        }

    # 规则2：高情感印记 / 高频再激活记忆受人格保护（阈值每次调用时读取配置）
    settings = get_settings()
    memory_config = settings.config.memory
    emotion_threshold = memory_config.persona_guard_emotion_threshold
    reactivation_threshold = memory_config.persona_guard_reactivation_threshold

    emotion_protected = emotion_score >= emotion_threshold
    reactivation_protected = reactivation_count >= reactivation_threshold

    if emotion_protected or reactivation_protected:
        protected_reasons = []
        if emotion_protected:
            protected_reasons.append(
                f"情感印记（{emotion_score}）达到保护阈值（{emotion_threshold}）"
            )
        if reactivation_protected:
            protected_reasons.append(
                f"再激活次数（{reactivation_count}）达到保护阈值（{reactivation_threshold}）"
            )
        return {
            "allowed": False,
            "reason": (
                "；".join(protected_reasons)
                + "。此类记忆承载人格连续性，受人格保护不可遗忘；可考虑归档（archive）作为替代"
            ),
        }

    # 规则3：其余记忆放行
    return {"allowed": True, "reason": ""}
