"""反馈清洗：jsonschema 校验、质量分过滤、去重指纹。

对齐 public/schema/cxo_tuner_feedback.schema.json。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

import jsonschema

# 契约校验默认路径：.../CX-O/public/schema（相对本文件 __file__ 解析）
_SCHEMA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *(os.pardir,) * 4, "public", "schema")
)
_FEEDBACK_SCHEMA_PATH = os.path.join(_SCHEMA_DIR, "cxo_tuner_feedback.schema.json")

# 质量分过滤阈值：quality_score < 0.3 丢弃
QUALITY_THRESHOLD = 0.3

_SOURCE_VALUES = ("live_danmaku", "judge", "distillation")


class InvalidFeedbackError(ValueError):
    """反馈不满足 cxo_tuner_feedback.schema.json 契约。对应 HTTP 422。"""


def _fmt_validation_error(exc: Any) -> str:
    path = ".".join(str(p) for p in exc.absolute_path) or "root"
    return f"data 校验失败 @ {path}: {exc.message}"


class FeedbackCleaner:
    """对齐 cxo_tuner_feedback.schema.json 的清洗器。"""

    def __init__(self, schema_path: Optional[str] = None) -> None:
        self._schema_path = schema_path or _FEEDBACK_SCHEMA_PATH
        self._schema_cache: Optional[Optional[dict]] = None

    def _schema(self) -> Optional[dict]:
        if self._schema_cache is None:
            if os.path.isfile(self._schema_path):
                try:
                    with open(self._schema_path, "r", encoding="utf-8") as fh:
                        self._schema_cache = json.load(fh)
                    return self._schema_cache
                except Exception:
                    self._schema_cache = False
                    return None
            self._schema_cache = False
            return None
        return self._schema_cache or None

    def validate(self, data: dict) -> None:
        """jsonschema 契约校验。非法时抛 InvalidFeedbackError。"""
        if not isinstance(data.get("prompt"), str) or not data.get("prompt").strip():
            raise InvalidFeedbackError("prompt 不允许为空")
        if not isinstance(data.get("response_chosen"), str) or not data.get("response_chosen").strip():
            raise InvalidFeedbackError("response_chosen 不允许为空")
        if not isinstance(data.get("response_rejected"), str) or not data.get("response_rejected").strip():
            raise InvalidFeedbackError("response_rejected 不允许为空")
        if data.get("response_chosen") == data.get("response_rejected"):
            raise InvalidFeedbackError("response_chosen 与 response_rejected 内容必须不同")
        if data.get("source") not in _SOURCE_VALUES:
            raise InvalidFeedbackError(f"source 必须是 {_SOURCE_VALUES} 之一")

        schema = self._schema()
        if schema is None:
            # 契约文件缺失时退化为字段级校验（已覆盖必填/枚举/非空）
            return
        try:
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.exceptions.ValidationError as exc:
            raise InvalidFeedbackError(_fmt_validation_error(exc))

    def is_low_quality(self, quality_score: Optional[float]) -> bool:
        """quality_score < 0.3 判定为低质量需丢弃。缺省按中性处理，不丢弃。"""
        if quality_score is None:
            return False
        try:
            return not (float(quality_score) >= QUALITY_THRESHOLD)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def fingerprint(prompt: str, chosen: str, rejected: str) -> str:
        """同 prompt+chosen+rejected 去重指纹。"""
        raw = f"{prompt}\x00{chosen}\x00{rejected}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()