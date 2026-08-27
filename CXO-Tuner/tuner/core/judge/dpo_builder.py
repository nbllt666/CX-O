"""历史对话→DPO 自动构建管道。

接收会话历史样本（list of {prompt, responses: list[str]}，来自 CX-O 会话导出端点），
对同一 prompt 的多个候选回复做 pairwise judge 比较，选出 chosen/rejected，产出
DPO 记录（source=judge，judge_model 与 judge_reasoning 入 metadata）写入
DatasetStore，并记录审计明细（judge 明细列表）供日志/审计。

样本约定：
  - responses 少于 2 条的样本跳过（无法形成正负对）；
  - 多响应样本逐一两两比较，累计每条的胜场与得分，得分最高的作为 chosen、
    得分最低的作为 rejected；
  - 最终 chosen 与 rejected 相同（全部平局）或判定全部失败时跳过。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tuner.core.collector.dataset import DatasetStore
from tuner.core.judge.judge_engine import JudgeEngine, JudgeResult

DIMENSION_KEYS = ("persona", "emotional_value", "logic_fact")


@dataclass
class BuildDpoResult:
    """一次批量构建的结果摘要。"""

    built: int = 0
    skipped: int = 0
    total: int = 0
    audit: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "built": self.built,
            "skipped": self.skipped,
            "total": self.total,
            "audit_items": len(self.audit),
        }


class DpoBuilder:
    """历史对话→DPO 自动构建器。"""

    def __init__(self, store: DatasetStore, judge_engine: JudgeEngine) -> None:
        self.store = store
        self.judge = judge_engine

    # -- 入口 -------------------------------------------------------------------
    def build(
        self,
        samples: List[Dict[str, Any]],
        character_card_hint: Optional[str] = None,
    ) -> BuildDpoResult:
        """从会话历史样本批量构建 DPO 记录。

        Args:
            samples: list of {"prompt": str, "responses": list[str], "session_id": str?}
            character_card_hint: 可选的角色人设提示，注入裁判 prompt。

        Returns:
            BuildDpoResult（含 built/skipped/total 与审计明细）。
        """
        result = BuildDpoResult(total=len(samples))
        for sample in samples or []:
            prompt = (sample.get("prompt") or "") if isinstance(sample, dict) else ""
            responses = sample.get("responses") or [] if isinstance(sample, dict) else []
            session_id = sample.get("session_id") if isinstance(sample, dict) else None

            if not isinstance(prompt, str) or not prompt.strip() or not isinstance(responses, list) or len(responses) < 2:
                result.skipped += 1
                result.audit.append(
                    {"prompt": prompt, "skip_reason": "样本缺失或候选回复不足 2 条"}
                )
                continue

            if self._build_one(prompt, responses, character_card_hint, session_id, result):
                result.built += 1
            else:
                result.skipped += 1
        return result

    # -- 单样本构建 ---------------------------------------------------------------
    def _build_one(
        self,
        prompt: str,
        responses: List[str],
        character_card_hint: Optional[str],
        session_id: Optional[str],
        result: BuildDpoResult,
    ) -> bool:
        """对单个样本做 pairwise 比较，选出 chosen/rejected；成功返回 True。

        判定期间产生的每条 judge 明细追加到 result.audit。
        """
        n = len(responses)
        wins = [0] * n          # 作为 winner 的次数
        agg_scores = [0.0] * n  # 作为 winner 拿到的得分累计
        samples_meta: List[Dict[str, Any]] = []
        all_failed = True

        for i in range(n):
            for j in range(i + 1, n):
                verdict = self.judge._compare(responses[i], responses[j], prompt, character_card_hint)
                detail = self._pair_audit(i, j, verdict)
                samples_meta.append(detail)
                result.audit.append(detail)
                if verdict.chosen_index is None:
                    continue  # 该 pair 判定失败，跳过
                all_failed = False
                if verdict.chosen_index == 0:
                    winner, loser = i, j
                    score = verdict.score_left
                else:
                    winner, loser = j, i
                    score = verdict.score_right
                wins[winner] += 1
                agg_scores[winner] += score
                detail["winner_index"] = winner

        if all_failed:
            return False

        chosen = max(range(n), key=lambda k: (wins[k], agg_scores[k]))
        rejected = min(range(n), key=lambda k: (wins[k], agg_scores[k]))
        if chosen == rejected:
            result.audit.append(
                {"prompt": prompt, "skip_reason": "judge 平局，无法区分 chosen/rejected"}
            )
            return False

        chosen_text = responses[chosen]
        rejected_text = responses[rejected]
        fp = self._fingerprint(prompt, chosen_text, rejected_text)

        if self.store.find_by_fingerprint(fp):
            result.audit.append(
                {"prompt": prompt, "skip_reason": "duplicate", "chosen_index": chosen, "rejected_index": rejected}
            )
            return False  # 去重幂等，不重复入库

        reasoning = self._join_reasoning(samples_meta)
        metadata: Dict[str, Any] = {
            "judge_model": self.judge.judge_model,
            "judge_reasoning": reasoning,
        }
        rec = self.store.add_record(
            fingerprint=fp,
            prompt=prompt,
            chosen=chosen_text,
            rejected=rejected_text,
            source="judge",
            anchor=False,
            session_id=session_id,
            judge_model=self.judge.judge_model,
            metadata=metadata,
        )
        result.audit.append(
            {
                "prompt": prompt,
                "built": True,
                "chosen_index": chosen,
                "rejected_index": rejected,
                "record_id": rec.id,
            }
        )
        return True

    # -- 工具 -------------------------------------------------------------------
    @staticmethod
    def _pair_audit(left_index: int, right_index: int, verdict: JudgeResult) -> Dict[str, Any]:
        return {
            "left_index": left_index,
            "right_index": right_index,
            "chosen_index": verdict.chosen_index,
            "score_left": verdict.score_left,
            "score_right": verdict.score_right,
            "dimensions": verdict.dimensions,
            "reasoning": verdict.reasoning,
            "error": verdict.error,
        }

    @staticmethod
    def _fingerprint(prompt: str, chosen: str, rejected: str) -> str:
        raw = f"{prompt}\x00{chosen}\x00{rejected}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _join_reasoning(samples_meta: List[Dict[str, Any]]) -> str:
        parts = []
        for d in samples_meta:
            if d.get("reasoning"):
                parts.append(f"[{d.get('left_index')}v{d.get('right_index')}] {d.get('reasoning')}")
        return "; ".join(parts) if parts else ""