"""人脸档案 REST 端点（spec add-vlm-frame-filter-face-match T3）。

对外暴露的人脸档案管理与状态查询接口，挂在 /api 前缀下：

  - GET    /api/face/profiles           人脸档案列表（脱敏，不含特征向量）
  - POST   /api/face/profiles           注册/更新人脸档案（body: {name, image}）
  - DELETE /api/face/profiles/{name}    删除人脸档案
  - GET    /api/face/status             人脸服务状态
  - POST   /api/face/match              人脸匹配（诊断用，body: {image}）

业务逻辑委托给 server.services.face_profile_service（经 get_face_profile_service()
工厂获取，延迟 import——T2 并行交付后 import 即生效），本模块只做入参校验与
异常 → HTTP 状态码映射（对齐 server/api/routers/voiceprint.py 的口径，鉴权
同样不加额外依赖）：

  - 字段缺失 / name 超界 / image 为空   → 422（Pydantic 校验）
  - 图像超 20MB                        → 413（与 voiceprint 同口径）
  - 服务层 ValueError                  → 400
  - FaceServiceUnavailable             → 503（中文 detail 含安装提示）
  - 其它内部异常                       → 500（错误文案收敛，详情留日志）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.core.logging_config import get_contextual_logger

router = APIRouter(prefix="/face", tags=["face"])
logger = get_contextual_logger(__name__)

# 上传防呆：单次请求图像（解码后）大小上限 20MB（与 voiceprint.py 同口径）
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 503 提示文案：面向部署者的中文安装指引（local provider 依赖 insightface/onnxruntime）
_UNAVAILABLE_DETAIL = (
    "人脸服务不可用：请检查 face_match 配置（local 模式需安装 insightface、"
    "onnxruntime，或改用 external 模式并配置 endpoint）"
)


class RegisterProfileRequest(BaseModel):
    """注册/更新人脸档案请求：name 为档案名（1-64 字符），image 为 dataURL 或 base64 图像串。"""

    name: str = Field(min_length=1, max_length=64, description="人脸档案名，1-64 字符")
    image: str = Field(min_length=1, description="图像内容，dataURL 或 base64 编码")


class MatchRequest(BaseModel):
    """人脸匹配（诊断）请求：image 为 dataURL 或 base64 图像串。"""

    image: str = Field(min_length=1, description="图像内容，dataURL 或 base64 编码")


def _check_image_size(image: str) -> None:
    """图像大小防呆：dataURL/base64 原串长度预检（4/3 膨胀 + padding 余量），超限抛 413。

    dataURL/base64 解码本身交服务层处理，路由只做大小与非空（Pydantic 422）校验。
    """
    if len(image) > _MAX_UPLOAD_BYTES * 4 // 3 + 4:
        raise HTTPException(status_code=413, detail="图像文件过大")


@router.get("/profiles")
async def list_profiles():
    """返回全部人脸档案摘要（脱敏：仅 name/created_at，不含特征向量本体）。"""
    from server.services.face_profile_service import (
        FaceServiceUnavailable,
        get_face_profile_service,
    )

    try:
        profiles = await get_face_profile_service().list_profiles()
    except FaceServiceUnavailable:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"人脸档案列表查询失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="人脸服务处理失败")
    return {"profiles": profiles}


@router.post("/profiles", status_code=201)
async def register_profile(payload: RegisterProfileRequest):
    """注册/更新人脸档案（重名覆盖）。入参非法 → 422；图像过大 → 413；服务不可用 → 503。"""
    from server.services.face_profile_service import (
        FaceServiceUnavailable,
        get_face_profile_service,
    )

    _check_image_size(payload.image)
    try:
        # image 原样透传（dataURL/base64 通用解码由服务层负责）
        summary = await get_face_profile_service().register(payload.name, payload.image)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FaceServiceUnavailable:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"人脸档案注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="人脸服务处理失败")
    return {"profile": summary}


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    """删除指定人脸档案；删除成功 → 200，不存在 → 404。"""
    from server.services.face_profile_service import (
        FaceServiceUnavailable,
        get_face_profile_service,
    )

    try:
        deleted = await get_face_profile_service().delete_profile(name)
    except FaceServiceUnavailable:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"人脸档案删除失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="人脸服务处理失败")
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该人脸档案")
    return {"status": "success", "name": name}


@router.get("/status")
def status():
    """人脸服务状态：enabled/provider/ready/profile_count（契约同步方法，透传不触发模型加载）。"""
    from server.services.face_profile_service import (
        FaceServiceUnavailable,
        get_face_profile_service,
    )

    try:
        return get_face_profile_service().get_status()
    except FaceServiceUnavailable:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"人脸状态查询失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="人脸服务处理失败")


@router.post("/match")
async def match(payload: MatchRequest):
    """人脸匹配（诊断用）：返回图像中各人脸对档案的命中列表。"""
    from server.services.face_profile_service import (
        FaceServiceUnavailable,
        get_face_profile_service,
    )

    _check_image_size(payload.image)
    try:
        matches = await get_face_profile_service().match(payload.image)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FaceServiceUnavailable:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE_DETAIL)
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"人脸匹配失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="人脸服务处理失败")
    return {"matches": matches}
