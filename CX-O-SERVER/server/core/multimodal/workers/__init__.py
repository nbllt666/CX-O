"""CX-O-SERVER 多模态管线 workers 子包（模块8 迁移版）。

逻辑与数据分离（rules-0 §三 sorting.logic_data_separated）:
    - 数据模型（MultimodalArtifact / OCRBlock / CharacterCardFields）定义在
      父包 multimodal_pipeline.py，与接口契约 .pyi 对齐。
    - 预处理逻辑（编码检测 / PNG 解析 / OCR / vision HTTP / vLLM 原生解码）
      下沉到本子包各 worker。

各 worker 返回构造 MultimodalArtifact 所需的原料 dict，由 MultimodalPipeline 主类
装配 Pydantic 模型。这样避免循环导入，且逻辑与数据边界清晰。

CX-O 扩展（v1.1.0）: 新增 VLLMNativeWorker 处理 video/audio 模态的原生解码。
"""

from .character_card_worker import CharacterCardWorker
from .image_worker import ImageWorker
from .text_worker import TextWorker
from .vllm_native_worker import VLLMNativeWorker

__all__ = [
    "TextWorker",
    "CharacterCardWorker",
    "ImageWorker",
    "VLLMNativeWorker",
]
