"""文本模态 worker。

逻辑与数据分离（rules-0 §三 sorting.logic_data_separated）：本模块只负责文本
预处理逻辑（编码检测 + NFKC 归一化 + strip），不承载数据模型定义。返回构造
MultimodalArtifact 所需的原料 dict，由 MultimodalPipeline 主类装配 Pydantic 模型。

对应契约:
    - public/interface_stub/multimodal_pipeline.pyi :: _text_worker
    - public/schema/multimodal_artifact.schema.json :: type=text

@version 1.0.0
"""

import logging
import os
import unicodedata
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TextWorker:
    """文本模态预处理 worker。

    处理流程:
        1. 判定 source_ref 是文件路径还是原始文本内容
        2. 若为文件路径 → 读取原始字节 → chardet 编码检测 → 解码
        3. NFKC 归一化（unicode.normalize）
        4. strip 空白
        5. 返回原料 dict（不含 artifact_id / created_at，由主类装配）
    """

    def __init__(self, task_timeout_seconds: int = 120) -> None:
        """初始化文本 worker。

        Args:
            task_timeout_seconds: 单任务超时（秒），保留参数以与管线配置对齐。
        """
        self._timeout = task_timeout_seconds

    # ------------------------------------------------------------------ #
    # 公开方法
    # ------------------------------------------------------------------ #

    def process(self, source_ref: str) -> Dict[str, Any]:
        """执行文本预处理，返回 MultimodalArtifact 原料 dict。

        Args:
            source_ref: 文本内容或文件路径。若 os.path.isfile(source_ref) 为真，
                视为文件路径并读取字节做编码检测；否则视为原始文本内容。

        Returns:
            dict 含字段: text_content / extra_metadata / confidence / vision_degraded

        Raises:
            FileNotFoundError: source_ref 指向文件路径但文件不存在（404）
            ValueError: 编码检测失败 / 解码失败（422 PARSE_FAILED）
        """
        if not source_ref:
            raise ValueError("source_ref 不能为空（422 PARSE_FAILED）")

        # 判定文件路径 vs 原始文本
        if os.path.isfile(source_ref):
            text, encoding = self._read_file(source_ref)
        else:
            # 原始文本内容：假定已为 str，无需解码
            text = source_ref
            encoding = "utf-8"

        # NFKC 归一化 + strip
        normalized_text = unicodedata.normalize("NFKC", text).strip()

        logger.info(
            "text_worker 完成: encoding=%s, len=%d", encoding, len(normalized_text)
        )

        return {
            "text_content": normalized_text,
            "extra_metadata": {
                "encoding": encoding,
                "normalized": True,
            },
            "confidence": 1.0,
            "vision_degraded": False,
        }

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _read_file(self, path: str) -> tuple:
        """读取文件并检测编码，返回 (text, encoding)。

        Args:
            path: 文件绝对路径

        Returns:
            (解码后文本, 检测到的编码名)

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 编码检测失败 / 解码失败（422）
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"文本文件不存在（404）: {path}")

        with open(path, "rb") as f:
            raw_bytes = f.read()

        encoding = self._detect_encoding(raw_bytes)

        try:
            text = raw_bytes.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError) as e:
            # 检测到的编码无法解码，回退 utf-8 replace
            logger.warning("编码 %s 解码失败，回退 utf-8 replace: %s", encoding, e)
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                encoding = "utf-8"
            except Exception as fallback_err:  # pragma: no cover - 极端路径
                raise ValueError(
                    f"文本解码失败（422 PARSE_FAILED）: {fallback_err}"
                ) from fallback_err

        return text, encoding

    @staticmethod
    def _detect_encoding(raw_bytes: bytes) -> str:
        """使用 chardet 检测字节流编码。

        chardet 不可用时降级为 utf-8/gbk 依次尝试；全部失败 raise ValueError。

        Args:
            raw_bytes: 原始字节流

        Returns:
            编码名称字符串

        Raises:
            ValueError: 编码检测失败（422 PARSE_FAILED）
        """
        # 优先 chardet
        try:
            import chardet  # type: ignore

            result = chardet.detect(raw_bytes)
            enc = (result or {}).get("encoding")
            if enc:
                return enc
            logger.warning("chardet 未返回编码，降级 utf-8/gbk 尝试")
        except ImportError:
            logger.warning("chardet 未安装，降级 utf-8/gbk 尝试")

        # 降级：utf-8 → gbk
        for fallback_enc in ("utf-8", "gbk"):
            try:
                raw_bytes.decode(fallback_enc, errors="strict")
                return fallback_enc
            except UnicodeDecodeError:
                continue

        raise ValueError(
            "编码检测失败（422 PARSE_FAILED）：chardet 不可用且 utf-8/gbk 均解码失败"
        )
