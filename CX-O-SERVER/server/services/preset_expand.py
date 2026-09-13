"""动作预设引用展开服务（spec enhance-emotion-tts-and-action-presets Task 4.2）。

LLM 输出 ``[action:预设名]`` 引用该 agent 已注册的动作预设时，在消息下发/落库前
展开为预设 tags 依序拼接的原始标签序列（如 ``[emotion:happy][action:wave]``），
前端按普通标签驱动动作/表情动画；未命中时原样透传（前端按容错分级处理：命中
manifest 动作名则触发动画，完全未知类型保留原文）。

防环（一层展开）：re.sub 的替换文本不会被重新扫描，预设 tags 内若再含
``[action:其他引用]`` 将原样保留——不递归展开，杜绝恶意/误配预设自引用导致的
无限展开或组合爆炸。

接入点（下发/落库前调用 expand_action_presets）：
- WebSocket 聊天：server/handlers/chat.py（message/stream/multimodal）
- HTTP 聊天：server/api/routers/chat.py（POST /chat、/chat/stream 落库点）
- 实时语音：server/handlers/audio.py（插话 agent_reply 下发、_record_context 落库）
- 网关聊天：server/core/websocket/handlers.py（chat/stream 落库点）

异常风格：任何失败（agent_id 非法、服务异常）静默回退原文本，绝不阻断聊天主流程。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# [action:预设名] 引用匹配：名称部分不含方括号（嵌套方括号不是合法标签形态）。
# 与前端 tagParser 的 [type:param] 标签形态对齐；前后允许保留原有空白由 \s* 吃掉。
_ACTION_REF_RE = re.compile(r"\[\s*action:([^\[\]]+?)\s*\]")


def expand_action_presets(text: str, agent_id: Optional[str]) -> str:
    """将文本中的 ``[action:预设名]`` 引用展开为该 agent 动作预设的原始标签序列。

    Args:
        text: LLM 回复文本（可能含动作预设引用）。
        agent_id: 当前 Agent 标识。缺失/非法时不展开（原样返回）。

    Returns:
        展开后的文本。规则：
        - 引用命中该 agent 动作预设 → 替换为预设 tags 依序拼接（一层，不递归）；
        - 未命中 / agent_id 缺失 / 服务异常 → 原样透传（不报错）；
        - 文本不含 ``[action:`` 时零开销直返（聊天热路径快速短路）。
    """
    if not text or not agent_id or not _ACTION_REF_RE.search(text):
        # 无引用 / agent 缺失：零展开直返（聊天热路径快速短路）
        return text
    try:
        from server.services import preset_service  # 惰性导入避免环依赖

        def _replace(match: "re.Match[str]") -> str:
            name = match.group(1).strip()
            if not name:
                return match.group(0)
            try:
                preset = preset_service.get_action_preset(agent_id, name)
            except Exception as e:  # noqa: BLE001 - 单个引用查询失败按未命中透传
                logger.warning(f"查询动作预设失败（原样透传）: agent={agent_id!r} name={name!r} -> {e}")
                return match.group(0)
            if not preset:
                # 未命中：原样透传（前端触发动作动画或按容错分级剥离）
                return match.group(0)
            tags = preset.get("tags") or []
            # 防环：替换文本不会被 re.sub 重新扫描，tags 内再含 [action:x] 不递归展开
            return "".join(str(t) for t in tags)

        return _ACTION_REF_RE.sub(_replace, text)
    except Exception as e:  # noqa: BLE001 - 展开整体失败降级为原文本
        logger.warning(f"动作预设展开失败（原样透传）: agent={agent_id!r} -> {e}")
        return text
