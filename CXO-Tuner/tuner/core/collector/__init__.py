"""Collector 编排层：把反馈清洗（cleaner）与数据集存储（DatasetStore）串起来。

submit_feedback 的完整行为：
  1. jsonschema 契约校验（对齐 cxo_tuner_feedback.schema.json）——非法抛
     InvalidFeedbackError（路由层转为 HTTP 422，不入库）；
  2. 质量分 < 0.3 的低质量样本丢弃——返回 accepted=False + reason="filtered"（HTTP 200）；
  3. 去重（prompt+chosen+rejected 指纹）——重复直接返回已有 id（幂等，不入库）；
  4. 写库——返回 accepted=True + reason="accepted"。
"""
from __future__ import annotations

from typing import Any, Dict

from tuner.core.collector.cleaner import FeedbackCleaner, InvalidFeedbackError
from tuner.core.collector.dataset import DatasetStore
from tuner.models import FeedbackIn, FeedbackResponse


class Collector:
    def __init__(self, cleaner: FeedbackCleaner, store: DatasetStore) -> None:
        self.cleaner = cleaner
        self.store = store

    def submit_feedback(self, feedback: FeedbackIn) -> FeedbackResponse:
        data: Dict[str, Any] = feedback.model_dump(exclude_unset=True)
        # 1. jsonschema 契约校验
        self.cleaner.validate(data)

        # 2. 质量分过滤（< 0.3 丢弃）
        if self.cleaner.is_low_quality(feedback.quality_score):
            return FeedbackResponse(feedback_id="", accepted=False, reason="filtered")

        # 3. 去重指纹
        fp = self.cleaner.fingerprint(
            feedback.prompt, feedback.response_chosen, feedback.response_rejected
        )
        if existing := self.store.find_by_fingerprint(fp):
            return FeedbackResponse(
                feedback_id=existing.id, accepted=False, reason="duplicate"
            )

        # 4. 写库
        rec = self.store.add_record(
            fingerprint=fp,
            prompt=feedback.prompt,
            chosen=feedback.response_chosen,
            rejected=feedback.response_rejected,
            source=feedback.source,
            anchor=False,
            quality_score=feedback.quality_score,
            session_id=feedback.session_id,
        )
        return FeedbackResponse(
            feedback_id=rec.id, accepted=True, reason="accepted"
        )

    def get_stats(self):
        return self.store.get_stats()