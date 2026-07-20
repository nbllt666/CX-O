"""CX-O-SERVER 多模态管线模块（模块8 迁移版）。

RADIX-Lite 多模态预处理管线（MultimodalPipeline），CX-O 扩展版：
    - 5 模态预处理：文本 / 角色卡 / 图片 / 视频 / 音频
    - 统一产出 MultimodalArtifact（含 native_decode_used 字段）
    - 图片模态支持 PaddleOCR + vLLM vision 双通道，vision 不可用时降级
    - 视频/音频模态通过 vLLM 原生 API 解码（仅当 LLM provider=vllm 时启用）

迁移来源: c:\\CX-O\\CXHMS\\modules\\模块8_多模态管线\\（3 模态版）
CX-O 扩展: 新增 video/audio 模态 + _vllm_native_worker + _get_llm_provider helper

对应契约（严格匹配签名，rules-3 §二 signature_match）:
    - 接口: public/interface_stub/multimodal_pipeline.pyi
    - 数据: public/schema/multimodal_artifact.schema.json
    - 配置: public/config_template/radix_config.json（multimodal_pipeline + vllm 段）
    - 运行时配置: server/config.py 的 MultimodalPipelineConfig（B6 扩展节）

@version 1.1.0  # CX-O 扩展版（新增 video/audio + vllm_native_worker）
"""

from .multimodal_pipeline import (
    CharacterCardFields,
    MultimodalArtifact,
    MultimodalPipeline,
    OCRBlock,
)

__all__ = [
    "MultimodalPipeline",
    "MultimodalArtifact",
    "OCRBlock",
    "CharacterCardFields",
]
