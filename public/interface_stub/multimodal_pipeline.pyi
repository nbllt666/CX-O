"""MultimodalPipeline 接口契约存根。

定义 RADIX-Lite 多模态管线的预处理接口 + worker 调度签名。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

5 模态（CX-O 扩展版，新增 video/audio 走 vLLM 原生解码）：
  - text: 文本（编码检测 + NFKC 归一化）
  - character_card: 角色卡（PNG tEXt "chara" chunk → base64 → JSON → 字段标准化）
  - image: 图片（PaddleOCR + vLLM vision 双通道，可降级）
  - video: 视频（vLLM 原生视频解码，仅当 LLM provider=vllm 时启用；否则降级）
  - audio: 音频（vLLM 原生音频解码，仅当 LLM provider=vllm 时启用；否则降级）

统一产出 MultimodalArtifact。视频/音频模态通过 _vllm_native_worker 处理，
检测 LLM provider，若为 vllm 则通过 vLLM API 直接投递原生视频/音频，否则降级路径。

@version 1.0.0
@see public/schema/multimodal_artifact.schema.json
@see public/config_template/radix_config.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
# CX-O 扩展版（新增 video/audio 模态）

class MultimodalArtifact(BaseModel):
    """多模态预处理产物。字段与 multimodal_artifact.schema.json 一致。"""
    artifact_id: str
    type: str  # enum: text / character_card / image / video / audio
    source: str
    text_content: str
    native_decode_used: bool = False  # 是否使用 vLLM 原生解码（仅 video/audio 模态有意义）
    extra_metadata: Dict[str, Any] = {}
    confidence: float = 1.0
    vision_degraded: bool = False
    processing_time_ms: Optional[int] = None
    created_at: str


class OCRBlock(BaseModel):
    """OCR 文本块。"""
    text: str
    bbox: List[float]  # [x1, y1, x2, y2]


class CharacterCardFields(BaseModel):
    """角色卡字段（标准化后）。"""
    name: str
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""


class MultimodalPipeline:
    """MultimodalPipeline 接口契约。

    worker 池（独立进程组），3 模态预处理。
    接管 parser.py 下沉的解析能力。
    """

    def preprocess(
        self,
        source_type: str,
        source_ref: str,
    ) -> MultimodalArtifact:
        """统一预处理入口。

        根据 source_type 分发到对应 worker，产出统一 MultimodalArtifact。
        CX-O 扩展：video/audio 模态路由到 _vllm_native_worker，仅当 LLM provider=vllm 时
        走 vLLM 原生解码；否则降级路径（vision_degraded=True, native_decode_used=False）。

        Args:
            source_type: 模态类型（text/character_card/image/video/audio）
            source_ref: 数据源引用（文件路径/URL/文本内容）

        Returns:
            MultimodalArtifact: 预处理产物

        Raises:
            ValueError: source_type 不在枚举中（422）
            FileNotFoundError: source_ref 指向的文件不存在（404）
            RuntimeError: 解析失败 / OCR 引擎异常 / vLLM 原生解码失败（500）
            ConnectionError: vLLM vision/native 不可用（503，触发降级路径）
        """
        ...

    def _text_worker(self, source_ref: str) -> MultimodalArtifact:
        """内部方法：文本模态 worker。

        编码检测（chardet）+ NFKC 归一化 + strip。

        Args:
            source_ref: 文本内容或文件路径

        Returns:
            MultimodalArtifact（type=text, confidence=1.0）

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: 编码检测失败（422）
        """
        ...

    def _character_card_worker(self, source_ref: str) -> MultimodalArtifact:
        """内部方法：角色卡模态 worker。

        Pillow PNG tEXt "chara" chunk → base64 decode → JSON → 字段标准化。

        Args:
            source_ref: PNG 文件路径或 JSON 文件路径

        Returns:
            MultimodalArtifact（type=character_card, extra_metadata=CharacterCardFields）

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: PNG tEXt chunk 缺失 / JSON 解析失败（422）
            RuntimeError: Pillow 解码异常（500）
        """
        ...

    def _image_worker(self, source_ref: str) -> MultimodalArtifact:
        """内部方法：图片模态 worker（双通道）。

        PaddleOCR 通道产出 OCR 文本块 + vLLM vision 通道产出视觉描述。
        vision 不可用时降级为仅 OCR（vision_degraded=True）。

        Args:
            source_ref: 图片文件路径

        Returns:
            MultimodalArtifact（type=image, extra_metadata={ocr_blocks, vision_description}）

        Raises:
            FileNotFoundError: 文件不存在（404）
            RuntimeError: PaddleOCR 引擎异常 / 图片解码失败（500）
            ConnectionError: vLLM vision 不可用（503，触发降级）
        """
        ...

    def _ocr_worker(self, image_path: str) -> List[OCRBlock]:
        """内部方法：PaddleOCR worker。

        Args:
            image_path: 图片路径

        Returns:
            OCR 文本块列表

        Raises:
            RuntimeError: PaddleOCR 引擎异常（500）
        """
        ...

    def _vision_worker(self, image_path: str) -> str:
        """内部方法：vLLM vision worker。

        Args:
            image_path: 图片路径

        Returns:
            视觉描述文本

        Raises:
            ConnectionError: vLLM vision 端点不可用（503）
            RuntimeError: vision 推理失败（500）
        """
        ...

    def _vllm_native_worker(
        self,
        source_ref: str,
        modality: str,
    ) -> MultimodalArtifact:
        """内部方法（CX-O 扩展）：vLLM 原生视频/音频解码 worker。

        检测 LLM provider 配置：
        - 若 provider=vllm：通过 vLLM OpenAI 兼容 API 直接投递原生视频/音频文件，
          vLLM 内部解码后返回文本描述/转录。native_decode_used=True, vision_degraded=False。
        - 若 provider!=vllm 或 vLLM 端点不可达：降级路径，返回占位文本 + 降级标记。
          native_decode_used=False, vision_degraded=True, confidence=0.5。

        Args:
            source_ref: 视频或音频文件路径/URL
            modality: 模态类型（video/audio）

        Returns:
            MultimodalArtifact:
              - 原生路径：type=video/audio, text_content=vLLM 产出文本,
                native_decode_used=True, vision_degraded=False, confidence=vLLM 置信度
              - 降级路径：type=video/audio, text_content=降级提示文本,
                native_decode_used=False, vision_degraded=True, confidence=0.5

        Raises:
            ValueError: modality 不在 video/audio 枚举中（422）
            FileNotFoundError: source_ref 指向的文件不存在（404）
            ConnectionError: vLLM 端点不可用（503，触发降级路径，非阻断）
            RuntimeError: vLLM 原生解码失败 / 视频音频文件损坏（422/500）
        """
        ...

    def _merge_ocr_vision(
        self,
        ocr_blocks: List[OCRBlock],
        vision_description: str,
    ) -> MultimodalArtifact:
        """内部方法：合并 OCR + vision 通道结果。

        Args:
            ocr_blocks: OCR 文本块
            vision_description: vision 描述

        Returns:
            合并后的 MultimodalArtifact
        """
        ...
