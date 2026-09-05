"""人脸注册工具（LLM 工具调用注册人脸，spec add-vlm-frame-filter-face-match T3）。

register_face_profile 从最近视觉帧缓存（server.core.vision.frame_cache，T4 视觉
链路 camera 源覆盖写入）取当前 camera 会话最近一帧，交 FaceProfileService 提取
最大人脸入档；供主 LLM 在用户说"记住我/记一下这个人"时调用。注册结果以工具
回执同步返回，不在后台改写（对齐 register_voiceprint 的中文错误语义风格）。
"""
from __future__ import annotations

from typing import Any, Dict

from server.core.tools.registry import tool_registry
from server.core.vision.frame_cache import get_recent_frame

# 服务不可用时的中文安装提示（与路由 _UNAVAILABLE_DETAIL 口径一致）
_UNAVAILABLE_ERROR = (
    "人脸服务不可用：请检查 face_match 配置（local 模式需安装 insightface、"
    "onnxruntime，或改用 external 模式并配置 endpoint）"
)


async def _handler(name: str) -> Dict[str, Any]:
    """register_face_profile 工具 handler：用最近 camera 帧注册人脸档案。

    参数 name：要注册的人脸档案名。无可用帧（尚无 camera 画面）时返回明确
    中文错误，不发起注册；服务层延迟 import（T2 实体交付后即生效）。
    """
    from server.services.face_profile_service import (
        FaceServiceUnavailable,
        get_face_profile_service,
    )

    frame = get_recent_frame()
    if not frame:
        return {
            "success": False,
            "error": "当前没有可用的摄像头画面，请先打开摄像头并对准要记住的人，再让我记住。",
            "tool_name": "register_face_profile",
        }

    try:
        # 帧原样透传（dataURL/base64 通用解码由服务层负责）
        summary = await get_face_profile_service().register(name, frame)
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
            "tool_name": "register_face_profile",
        }
    except FaceServiceUnavailable:
        return {
            "success": False,
            "error": _UNAVAILABLE_ERROR,
            "tool_name": "register_face_profile",
        }
    except Exception as e:  # noqa: BLE001 落盘 IO / 其它兜底
        return {
            "success": False,
            "error": f"人脸注册失败：{e}",
            "tool_name": "register_face_profile",
        }

    registered_name = summary.get("name", name)
    return {
        "success": True,
        "name": registered_name,
        "faces_detected": summary.get("faces_detected", 0),
        "message": f"已记住「{registered_name}」的样子。",
        "tool_name": "register_face_profile",
    }


def register_face_tool() -> None:
    """注册 register_face_profile 工具（幂等）。"""
    tool_registry.register(
        name="register_face_profile",
        description=(
            "记住眼前的人。用户说出类似\"记住我/记一下这个人，他叫XX\"的请求时调用，"
            "用当前摄像头画面中的人脸建立档案，参数 name 为这个人的名字。"
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "要记住的人的名字"}},
            "required": ["name"],
        },
        function=_handler,
        enabled=True,
        version="1.0.0",
        category="general",
        tags=["face"],
        examples=["记住我，我叫小张 → register_face_profile(name='小张')"],
    )
