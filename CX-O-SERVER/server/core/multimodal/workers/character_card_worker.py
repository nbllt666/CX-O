"""角色卡模态 worker。

逻辑与数据分离：本模块负责角色卡解析逻辑（PNG tEXt "chara" chunk → base64
decode → JSON parse → 字段标准化），不承载数据模型定义。返回构造
MultimodalArtifact 所需的原料 dict。

支持两种输入形态:
    1. PNG 角色卡文件路径（.png）→ Pillow 解析 tEXt chunk "chara"
    2. JSON 角色卡文件路径（.json）→ 直接解析 JSON
    3. 已 base64 编码的 chara 字符串（非文件路径）→ base64 decode → JSON

对应契约:
    - public/interface_stub/multimodal_pipeline.pyi :: _character_card_worker
    - public/schema/multimodal_artifact.schema.json :: type=character_card

@version 1.0.0
"""

import base64
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


# 角色卡标准字段名（与 .pyi CharacterCardFields 一致）
_CHARACTER_CARD_FIELD_NAMES = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
)


class CharacterCardWorker:
    """角色卡模态预处理 worker。

    处理流程:
        1. 判定 source_ref 类型：PNG 文件 / JSON 文件 / base64 字符串 / JSON 字符串
        2. PNG → Pillow 读取 tEXt chunk "chara" → base64 decode → JSON
        3. 字段标准化（缺失字段补默认空串）
        4. 返回原料 dict（含 text_content=JSON 序列化字段文本 + extra_metadata=字段）
    """

    def __init__(self, task_timeout_seconds: int = 120) -> None:
        """初始化角色卡 worker。

        Args:
            task_timeout_seconds: 单任务超时（秒）。
        """
        self._timeout = task_timeout_seconds

    # ------------------------------------------------------------------ #
    # 公开方法
    # ------------------------------------------------------------------ #

    def process(self, source_ref: str) -> Dict[str, Any]:
        """执行角色卡预处理，返回 MultimodalArtifact 原料 dict。

        Args:
            source_ref: PNG 文件路径 / JSON 文件路径 / base64 字符串 / JSON 字符串

        Returns:
            dict 含字段: text_content / extra_metadata / confidence / vision_degraded

        Raises:
            FileNotFoundError: source_ref 指向文件路径但文件不存在（404）
            ValueError: PNG tEXt chunk "chara" 缺失 / JSON 解析失败（422 PARSE_FAILED）
            RuntimeError: Pillow 解码异常（500）
        """
        if not source_ref:
            raise ValueError("source_ref 不能为空（422 PARSE_FAILED）")

        raw_json = self._extract_raw_json(source_ref)
        fields = self._normalize_fields(raw_json)

        # text_content: JSON 序列化后的字段文本（保证可读 + 可二次解析）
        text_content = json.dumps(fields, ensure_ascii=False, indent=2)

        logger.info(
            "character_card_worker 完成: name=%s, fields=%d",
            fields.get("name"),
            len(fields),
        )

        return {
            "text_content": text_content,
            "extra_metadata": fields,
            "confidence": 0.95,
            "vision_degraded": False,
        }

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _extract_raw_json(self, source_ref: str) -> Dict[str, Any]:
        """从 source_ref 提取原始 JSON dict。

        Args:
            source_ref: 文件路径 / base64 字符串 / JSON 字符串

        Returns:
            解析后的 JSON dict

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: 解析失败（422 PARSE_FAILED）
            RuntimeError: Pillow 解码异常（500）
        """
        # 形态 1: PNG 文件
        if os.path.isfile(source_ref) and source_ref.lower().endswith(".png"):
            return self._parse_png_character_card(source_ref)

        # 形态 2: JSON 文件
        if os.path.isfile(source_ref) and source_ref.lower().endswith(".json"):
            return self._parse_json_file(source_ref)

        # 形态 3: 文件路径但文件不存在 → FileNotFoundError
        if (
            source_ref.lower().endswith(".png")
            or source_ref.lower().endswith(".json")
        ) and not os.path.isfile(source_ref):
            raise FileNotFoundError(
                f"角色卡文件不存在（404）: {source_ref}"
            )

        # 形态 4: base64 字符串（非文件路径，含典型 base64 字符集且较长）
        if self._looks_like_base64(source_ref):
            return self._parse_base64_json(source_ref)

        # 形态 5: JSON 字符串
        return self._parse_json_string(source_ref)

    def _parse_png_character_card(self, png_path: str) -> Dict[str, Any]:
        """解析 PNG 角色卡：tEXt chunk "chara" → base64 decode → JSON。

        Args:
            png_path: PNG 文件绝对路径

        Returns:
            解析后的 JSON dict

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: tEXt chunk "chara" 缺失 / JSON 解析失败（422）
            RuntimeError: Pillow 解码异常（500）
        """
        if not os.path.exists(png_path):
            raise FileNotFoundError(f"PNG 角色卡文件不存在（404）: {png_path}")

        try:
            from PIL import Image  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Pillow 未安装（500 INTERNAL_ERROR），无法解析 PNG 角色卡。"
                "请运行: pip install Pillow"
            ) from e

        try:
            with Image.open(png_path) as img:
                # Pillow 将 PNG tEXt chunk 存入 img.info（旧版）或 img.text（新版）
                chara_b64 = None
                if hasattr(img, "text") and isinstance(img.text, dict):
                    chara_b64 = img.text.get("chara")
                if chara_b64 is None:
                    chara_b64 = img.info.get("chara")
        except Exception as e:
            raise RuntimeError(
                f"Pillow 解码 PNG 异常（500 INTERNAL_ERROR）: {e}"
            ) from e

        if not chara_b64:
            raise ValueError(
                "PNG tEXt chunk 'chara' 缺失（422 PARSE_FAILED）："
                f"文件 {png_path} 不含角色卡数据"
            )

        return self._parse_base64_json(chara_b64)

    def _parse_json_file(self, json_path: str) -> Dict[str, Any]:
        """解析 JSON 文件。

        Args:
            json_path: JSON 文件绝对路径

        Returns:
            解析后的 JSON dict

        Raises:
            FileNotFoundError: 文件不存在（404）
            ValueError: JSON 解析失败（422）
        """
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"JSON 角色卡文件不存在（404）: {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"JSON 解析失败（422 PARSE_FAILED）: {e}"
            ) from e

        if not isinstance(data, dict):
            raise ValueError(
                "JSON 角色卡根节点非 object（422 PARSE_FAILED）"
            )
        return data

    def _parse_base64_json(self, b64_str: str) -> Dict[str, Any]:
        """base64 decode → JSON parse。

        Args:
            b64_str: base64 编码字符串

        Returns:
            解析后的 JSON dict

        Raises:
            ValueError: base64 解码失败 / JSON 解析失败（422）
        """
        try:
            raw_bytes = base64.b64decode(b64_str, validate=False)
        except Exception as e:
            raise ValueError(
                f"base64 解码失败（422 PARSE_FAILED）: {e}"
            ) from e

        try:
            text = raw_bytes.decode("utf-8", errors="replace")
        except Exception as e:  # pragma: no cover
            raise ValueError(
                f"字符解码失败（422 PARSE_FAILED）: {e}"
            ) from e

        return self._parse_json_string(text)

    def _parse_json_string(self, text: str) -> Dict[str, Any]:
        """解析 JSON 字符串。

        Args:
            text: JSON 字符串

        Returns:
            解析后的 JSON dict

        Raises:
            ValueError: JSON 解析失败（422）
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"JSON 解析失败（422 PARSE_FAILED）: {e}"
            ) from e

        if not isinstance(data, dict):
            raise ValueError(
                "JSON 角色卡根节点非 object（422 PARSE_FAILED）"
            )
        return data

    @staticmethod
    def _normalize_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
        """字段标准化：缺失字段补默认空串，仅保留标准字段。

        与 .pyi CharacterCardFields 字段对齐:
            name / description / personality / scenario / first_mes / mes_example

        Args:
            raw: 原始 JSON dict

        Returns:
            标准化后的字段 dict（含全部 6 字段）

        Raises:
            ValueError: name 字段缺失或为空（422）
        """
        normalized: Dict[str, Any] = {}
        for field in _CHARACTER_CARD_FIELD_NAMES:
            value = raw.get(field, "")
            # 强制转 str + strip（角色卡字段应为文本）
            if value is None:
                value = ""
            normalized[field] = str(value).strip() if isinstance(value, str) else str(value)

        # name 必须非空（角色卡标识字段）
        if not normalized["name"]:
            raise ValueError(
                "角色卡 name 字段缺失或为空（422 PARSE_FAILED）"
            )

        return normalized

    @staticmethod
    def _looks_like_base64(s: str) -> bool:
        """启发式判断字符串是否为 base64 编码。

        Args:
            s: 待判定字符串

        Returns:
            True 表示可能是 base64 编码
        """
        if not s or len(s) < 16:
            return False
        # base64 字符集 + 可能含换行（Pillow tEXt 可能含换行）
        import string as _string

        allowed = set(_string.ascii_letters + _string.digits + "+/=\n\r")
        non_ws = s.replace("\n", "").replace("\r", "")
        if len(non_ws) < 16:
            return False
        # 至少 80% 字符在 base64 字符集内，且长度为 4 的倍数（去除换行后）
        in_set = sum(1 for c in non_ws if c in allowed)
        if in_set / len(non_ws) < 0.8:
            return False
        return len(non_ws) % 4 == 0
