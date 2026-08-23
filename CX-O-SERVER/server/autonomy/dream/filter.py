"""CX-O-Dream 梦境确定性内容闸门（server/autonomy/dream/filter.py）。

D7_DREAM_FILTER 的引擎内实现：以正则/lucidity 阈值做确定性拦截，
判定优先确定性规则，不引入 LLM 兜底（避免过滤本身产生新幻觉，spec
"D7_DREAM_FILTER 确定性闸门"）。仅登记 "D7_DREAM_FILTER" 至
DecisionCore.DECISION_POINTS 做语义对齐与追溯，不进入 D1-D6 决策流程。

拦截规则（按序判定，命中即拒）:
    a. 事实性断言：content 命中 FACTUAL_PATTERNS（"你昨天/你说过/你做了"+具体事件）→ factual_hallucination
    b. 触碰 permanent 记忆或 importance_score >= 0.95 的关联记忆（红线 R2）→ permanent_touch
    c. lucidity_score < config.min_lucidity → low_lucidity
    d. 通过 → approved

对应契约: public/interface_stub/dream.pyi（filter_candidate 签名）
"""

import re

# 事实性断言模式：第二人称事实锚点 + 后续至少一个字符的具体事件描述。
# 梦境为联想虚构（is_ground_truth=false），不得断言用户真实经历。
FACTUAL_PATTERNS = (
    re.compile(r"你昨天.+"),
    re.compile(r"你刚才.+"),
    re.compile(r"你说过.+"),
    re.compile(r"你曾经.+"),
    re.compile(r"你做了.+"),
    re.compile(r"我记得你.+"),
)

# 红线 R2 阈值：关联记忆 importance_score >= 0.95 视为高重要性，禁止梦境触碰
_PERMANENT_IMPORTANCE_THRESHOLD = 0.95


class DreamFilter:
    """梦境候选确定性内容闸门。

    判定优先确定性规则，不引入 LLM 兜底（避免过滤本身产生新幻觉）。
    """

    def filter_candidate(
        self,
        candidate: dict,
        associated_memories_meta: list,
        config,
    ) -> dict:
        """过滤单条梦境候选。

        Args:
            candidate: 候选字典，含 content / lucidity_score
            associated_memories_meta: 关联记忆元数据列表（引擎侧组装），
                每项含 id / importance_score / permanent / content
            config: 配置（含 min_lucidity，如 DreamConfig）

        Returns:
            {"approved": bool, "decision": "approved"|"rejected", "reason": str|None}
        """
        content = (candidate.get("content") or "").strip()
        lucidity = candidate.get("lucidity_score", 0.0)

        # a. 事实性断言拦截
        if self._has_factual_assertion(content):
            return {
                "approved": False,
                "decision": "rejected",
                "reason": "factual_hallucination",
            }

        # b. 红线 R2：触碰 permanent 或高重要性关联记忆
        if self._touches_protected_memory(associated_memories_meta):
            return {
                "approved": False,
                "decision": "rejected",
                "reason": "permanent_touch",
            }

        # c. 低清醒度拦截
        if lucidity < config.min_lucidity:
            return {
                "approved": False,
                "decision": "rejected",
                "reason": "low_lucidity",
            }

        # d. 通过
        return {"approved": True, "decision": "approved", "reason": None}

    @staticmethod
    def _has_factual_assertion(content: str) -> bool:
        """content 命中任一事实性断言模式（锚点 + 后续具体事件描述）。"""
        if not content:
            return False
        return any(pattern.search(content) for pattern in FACTUAL_PATTERNS)

    @staticmethod
    def _touches_protected_memory(associated_memories_meta: list) -> bool:
        """任一关联记忆为 permanent 或 importance_score >= 0.95（红线 R2）。"""
        for meta in associated_memories_meta or []:
            if meta.get("permanent"):
                return True
            importance = meta.get("importance_score")
            if importance is not None and importance >= _PERMANENT_IMPORTANCE_THRESHOLD:
                return True
        return False
