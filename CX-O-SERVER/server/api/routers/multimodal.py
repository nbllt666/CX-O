"""MultimodalPipeline 多模态预处理路由（CX-O 迁移版 B2.6）。

挂接 RADIX-Lite MultimodalPipeline 的多模态预处理 API 端点。

端点清单:
    - POST /api/multimodal/preprocess        统一预处理入口（5 模态分发）
    - GET  /api/multimodal/artifact/{artifact_id}  查询 artifact 元数据（占位）
    - GET  /api/multimodal/provider           查询当前 LLM provider（调试用）
    - GET  /api/multimodal/health             多模态管线健康检查

对应契约:
    - 接口契约: public/interface_stub/multimodal_pipeline.pyi :: preprocess
    - 数据契约: public/schema/multimodal_artifact.schema.json
    - 配置契约: public/config_template/radix_config.json（multimodal_pipeline 段）

@version 1.1.0  # CX-O 扩展版
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.core.multimodal import MultimodalArtifact, MultimodalPipeline

router = APIRouter()
logger = get_contextual_logger(__name__)

# 模块级懒加载 MultimodalPipeline 单例
_pipeline_instance: Optional[MultimodalPipeline] = None


def _get_pipeline() -> MultimodalPipeline:
    """懒加载 MultimodalPipeline 实例（模块级单例）。"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = MultimodalPipeline()
    return _pipeline_instance


def _reset_pipeline() -> None:
    """重置 pipeline 单例（测试用）。"""
    global _pipeline_instance
    _pipeline_instance = None


def _map_multimodal_exception(exc: Exception) -> None:
    """将 MultimodalPipeline 异常映射为 HTTP 异常。

    ValueError→422, FileNotFoundError→404, ConnectionError→503, RuntimeError→500,
    TimeoutError→504, 其他→500。
    """
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConnectionError):
        raise HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, TimeoutError):
        raise HTTPException(status_code=504, detail=str(exc))
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=500, detail=str(exc))
    raise HTTPException(status_code=500, detail=f"内部错误: {exc}")


# --------------------------------------------------------------------------- #
# 请求 / 响应模型
# --------------------------------------------------------------------------- #


class PreprocessRequest(BaseModel):
    """多模态预处理请求（对应 .pyi preprocess 方法签名）。"""

    source_type: str  # text / character_card / image / video / audio
    source_ref: str


class ArtifactResponse(BaseModel):
    """MultimodalArtifact 响应（对应 multimodal_artifact.schema.json）。"""

    artifact_id: str
    type: str
    source: str
    text_content: str
    native_decode_used: bool = False
    extra_metadata: Dict[str, Any] = {}
    confidence: float = 1.0
    vision_degraded: bool = False
    processing_time_ms: Optional[int] = None
    created_at: str


class ProviderResponse(BaseModel):
    """LLM provider 查询响应（调试用）。"""

    provider: str
    vllm_native_enabled: bool
    enabled_modalities: list


# --------------------------------------------------------------------------- #
# 端点
# --------------------------------------------------------------------------- #


@router.post("/multimodal/preprocess", response_model=ArtifactResponse)
async def preprocess(request: PreprocessRequest):
    """统一多模态预处理入口。

    根据 source_type 分发到对应 worker：
        - text → _text_worker（编码检测 + NFKC 归一化）
        - character_card → _character_card_worker（PNG tEXt → JSON）
        - image → _image_worker（PaddleOCR + vLLM vision 双通道，可降级）
        - video → _vllm_native_worker（vLLM 原生视频解码，provider!=vllm 时降级）
        - audio → _vllm_native_worker（vLLM 原生音频解码，provider!=vllm 时降级）

    Args:
        request: 预处理请求（source_type + source_ref）

    Returns:
        MultimodalArtifact 响应

    Raises:
        HTTPException 422: source_type 不在枚举中 / source_ref 为空
        HTTPException 404: 文件不存在
        HTTPException 503: vLLM vision/native 端点不可用（触发降级，不阻断）
        HTTPException 500: 解析失败 / OCR 引擎异常 / vLLM 原生解码失败
        HTTPException 504: 预处理超时
    """
    pipeline = _get_pipeline()
    try:
        artifact = pipeline.preprocess(
            source_type=request.source_type,
            source_ref=request.source_ref,
        )
        return ArtifactResponse(**artifact.model_dump())
    except HTTPException:
        raise
    except Exception as exc:
        _map_multimodal_exception(exc)


@router.get("/multimodal/artifact/{artifact_id}")
async def artifact_query(artifact_id: str):
    """查询 artifact 元数据（占位端点）。

    MultimodalPipeline 当前为无状态管线，artifact 不持久化。本端点返回占位响应，
    供下游（如 DistillationService）查询接口对齐。后续若需持久化，可扩展为
    从 data/multimodal_artifacts/ 读取。

    Args:
        artifact_id: artifact UUID

    Returns:
        占位响应（artifact_id + status + hint）
    """
    return {
        "artifact_id": artifact_id,
        "status": "not_persisted",
        "hint": (
            "MultimodalPipeline 当前为无状态管线，artifact 不持久化。"
            "如需查询，请在 preprocess 后立即消费返回值。"
        ),
    }


@router.get("/multimodal/provider", response_model=ProviderResponse)
async def get_provider():
    """查询当前 LLM provider 与 vllm_native 配置（调试用）。

    用于排查 video/audio 模态是否会走 vLLM 原生路径。
    """
    pipeline = _get_pipeline()
    provider = pipeline._get_llm_provider()
    return ProviderResponse(
        provider=provider,
        vllm_native_enabled=pipeline._vllm_native_enabled,
        enabled_modalities=list(pipeline._enabled_modalities),
    )


@router.get("/multimodal/health")
async def multimodal_health():
    """多模态管线健康检查。

    检查 pipeline 是否可实例化 + 配置加载是否正常 + 当前 provider。
    """
    try:
        pipeline = _get_pipeline()
        provider = pipeline._get_llm_provider()
        return {
            "status": "healthy",
            "pipeline_initialized": True,
            "provider": provider,
            "vllm_native_enabled": pipeline._vllm_native_enabled,
            "enabled_modalities": list(pipeline._enabled_modalities),
            "worker_pool_size": pipeline._worker_pool_size,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "pipeline_initialized": False,
            "error": str(e),
        }
