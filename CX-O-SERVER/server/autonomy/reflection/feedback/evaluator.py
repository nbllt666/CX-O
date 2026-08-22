"""CX-O-Autonomy 反思层·效果评估器（P1-T7）。

FeedbackEvaluator 对单次自主行动结果（action_result，含 action/result 等字段）
做简单效果评估：把 result 映射为 0.0-1.0 的 score 与 positive / neutral /
negative 信号，并在注入可调用 tuner_provider 且结果为 success 时提交偏好信号。

行为语义：
- score 映射：success=1.0、failed=0.0、blocked=0.4、skipped=0.5、未知=0.5
  （对齐 server/autonomy/models.py AuditResult 枚举）
- signal 映射：score >= 0.8 → positive；score <= 0.3 → negative；其余 → neutral
- submitted：仅当 tuner_provider 可调用且 result 为 success 且提交成功时为 True，
  否则为 False；provider 支持同步/异步回调（awaitable 自动 await），提交失败
  记录日志并返回 False，不向上冒泡
- P3-T2 接入真实 Tuner：本模块提供 submit_to_tuner(feedback: dict) 默认提交辅助
  （POST 到 Tuner /api/v1/feedback，body 对齐 FeedbackIn，source 用枚举内 "judge"
  并在 metadata 标注 origin="autonomy"），以及 make_tuner_provider() 桥接工厂，
  供 setup_autonomy 注入真实 provider；Tuner 不可达 / HTTP 4xx/5xx 时优雅降级
  submitted=False，不冒泡。

本模块无文件 IO，禁止相对路径。
"""

from __future__ import annotations

import inspect
import os
from typing import Any, Callable, Dict, Optional

from server.core.logging_config import get_contextual_logger
from server.core.utils import get_shared_http_client, iso_now

logger = get_contextual_logger(__name__)

# 结果 → 得分映射（对齐 AuditResult 枚举）
_SCORE_BY_RESULT: Dict[str, float] = {
    "success": 1.0,
    "failed": 0.0,
    "blocked": 0.4,
    "skipped": 0.5,
}
# 未知/缺失结果的兜底得分
_DEFAULT_SCORE = 0.5

# Tuner 地址解析：环境 CXO_TUNER_URL → 配置 evolution.host → 缺省
_DEFAULT_TUNER_URL = "http://localhost:8300"
_TUNER_ENV_KEY = "CXO_TUNER_URL"
_TUNER_FEEDBACK_PATH = "/api/v1/feedback"


def _score_to_signal(score: float) -> str:
    """把得分映射为信号：score>=0.8 positive；score<=0.3 negative；其余 neutral。"""
    if score >= 0.8:
        return "positive"
    if score <= 0.3:
        return "negative"
    return "neutral"


def resolve_tuner_url() -> str:
    """解析 CXO-Tuner 服务基础 URL。

    优先级：
        1. 环境变量 CXO_TUNER_URL
        2. server.config settings.config.evolution.host（CXOTunerConfig.host）
        3. 缺省 http://localhost:8300

    Returns:
        str: 去掉末尾斜杠的 Tuner 基础 URL
    """
    env_url = os.environ.get(_TUNER_ENV_KEY, "").strip()
    if env_url:
        return env_url.rstrip("/")
    try:
        from server.config import get_settings  # type: ignore

        settings = get_settings()
        unified = getattr(settings, "config", None)
        if unified is not None:
            evolution = getattr(unified, "evolution", None)
            host = getattr(evolution, "host", None)
            if host:
                return str(host).rstrip("/")
    except Exception as e:  # noqa: BLE001
        logger.debug("读取 Tuner 配置失败（%s），使用缺省地址", e)
    return _DEFAULT_TUNER_URL


def build_tuner_feedback(signal: str, action_result: Dict[str, Any]) -> Dict[str, Any]:
    """构造对齐 FeedbackIn（cxo_tuner_feedback.schema.json）的偏好反馈 body。

    自主评估来源统一用枚举内 source="judge"，并在 metadata 标注 origin="autonomy"
    与 action / signal（不修改 public/schema 枚举）。prompt / response_chosen /
    response_rejected 优先取 action_result 内已有文本，缺失时构造合成偏好样本
    （chosen 为成功行动描述、rejected 为未执行/低质对照），保证三条必填字段
    均为非空字符串，可通过 Tuner jsonschema 校验。

    Args:
        signal: 效果信号（positive / neutral / negative）
        action_result: 行动结果字典（含 action/result，可选 prompt/response_chosen/
            response_rejected/session_id/metadata）

    Returns:
        dict: 对齐 FeedbackIn 的 body（含 timestamp 与 quality_score）
    """
    action = str(action_result.get("action", ""))
    result = str(action_result.get("result", ""))
    score = _SCORE_BY_RESULT.get(result, _DEFAULT_SCORE)

    prompt = str(action_result.get("prompt") or f"[autonomy] action={action}")
    response_chosen = str(
        action_result.get("response_chosen")
        or f"autonomy 行动 {action} 正常完成（result={result}）"
    )
    response_rejected = str(
        action_result.get("response_rejected")
        or f"autonomy 行动 {action} 未执行或低质对照（result={result}）"
    )
    metadata: Dict[str, Any] = dict(action_result.get("metadata") or {})
    metadata["origin"] = "autonomy"
    metadata["action"] = action
    metadata["signal"] = signal

    body: Dict[str, Any] = {
        "prompt": prompt,
        "response_chosen": response_chosen,
        "response_rejected": response_rejected,
        "source": "judge",
        "timestamp": iso_now(),
        "quality_score": score,
        "metadata": metadata,
    }
    if action_result.get("session_id") is not None:
        body["session_id"] = str(action_result["session_id"])
    return body


async def submit_to_tuner(feedback: Dict[str, Any]) -> Dict[str, Any]:
    """POST 偏好反馈到 CXO-Tuner /api/v1/feedback（best-effort，不冒泡）。

    body 对齐 FeedbackIn：缺省补 source="judge" / timestamp（ISO 8601）/
    metadata.origin="autonomy"；prompt / response_chosen / response_rejected 缺省
    或为空时不发请求直接返回未提交（Tuner jsonschema 必填非空）。HTTP 4xx/5xx、
    连接失败、超时均视为未提交并记录日志，返回 {"submitted": False, "error": ...}，
    不向上冒泡。

    Args:
        feedback: 对齐 FeedbackIn 的反馈字典（或可被补全的最小字典）

    Returns:
        dict: {"submitted": True, "response": ...} 或 {"submitted": False, "error": ...}
    """
    try:
        body = dict(feedback or {})
        # 缺省补全：source / timestamp / metadata.origin / quality_score
        body.setdefault("source", "judge")
        body.setdefault("timestamp", iso_now())
        body.setdefault("quality_score", 0.5)  # 缺省按 schema 中性 0.5 处理
        metadata: Dict[str, Any] = dict(body.get("metadata") or {})
        metadata.setdefault("origin", "autonomy")
        body["metadata"] = metadata

        # 必填非空校验（对齐 cxo_tuner_feedback.schema.json required + minLength 1）
        missing = [
            key
            for key in ("prompt", "response_chosen", "response_rejected")
            if not str(body.get(key) or "").strip()
        ]
        if missing:
            logger.warning("Tuner 反馈缺少必填字段（不提交）: %s", missing)
            return {"submitted": False, "error": f"missing_fields={missing}"}

        url = resolve_tuner_url() + _TUNER_FEEDBACK_PATH
        client = get_shared_http_client()
        resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            logger.warning(
                "Tuner 反馈提交被拒（HTTP %s）: %s",
                resp.status_code,
                (getattr(resp, "text", "") or "")[:200],
            )
            return {
                "submitted": False,
                "error": f"tuner_http_{resp.status_code}",
                "status_code": resp.status_code,
            }
        data: Dict[str, Any] = {}
        try:
            data = resp.json() if resp.content else {}
        except Exception:  # noqa: BLE001
            data = {}
        return {"submitted": True, "response": data}
    except Exception as e:  # noqa: BLE001
        logger.warning("Tuner 反馈提交失败（不冒泡）: %s", e)
        return {"submitted": False, "error": str(e)}


def make_tuner_provider() -> Callable:
    """构造 FeedbackEvaluator 可用的默认 tuner_provider（桥接 signal + action_result）。

    provider 签名对齐 FeedbackEvaluator 既有约定：
        tuner_provider(signal: str, action_result: dict) -> dict
    内部经 build_tuner_feedback 构造 FeedbackIn body，再调用 submit_to_tuner 提交；
    返回 submit_to_tuner 的 {"submitted": ...} 结果，供评估器判定 submitted。

    Returns:
        Callable: 可同步/异步调用的 provider（本实现为 async 函数）
    """

    async def _provider(signal: str, action_result: Dict[str, Any]) -> Dict[str, Any]:
        feedback = build_tuner_feedback(signal, action_result)
        return await submit_to_tuner(feedback)

    return _provider


class FeedbackEvaluator:
    """单次行动效果评估器：简单评分 + 可选偏好信号提交。

    Args:
        tuner_provider: Tuner 偏好信号提交回调，签名
            tuner_provider(signal: str, action_result: dict) -> Any，可同步或异步；
            为 None 时不提交（本阶段 submitted=False）。provider 返回 dict 时以
            其 "submitted" 字段判定提交成败（如 make_tuner_provider 桥接的
            submit_to_tuner 结果），否则无异常即视为成功。
    """

    def __init__(self, tuner_provider: Optional[Callable] = None) -> None:
        """初始化评估器：保存 Tuner 偏好信号提交回调。"""
        self.tuner_provider: Optional[Callable] = tuner_provider

    async def evaluate(self, action_result: Dict[str, Any]) -> Dict[str, Any]:
        """评估一次行动结果。

        Args:
            action_result: 行动结果字典，含 action/result 等字段（result 取值
                对齐 AuditResult：success/failed/blocked/skipped）

        Returns:
            评估字典：
            - action:     行动名（action_result 的 action）
            - result:     行动结果（action_result 的 result）
            - score:      0.0-1.0 简单效果评分
            - signal:     positive / neutral / negative
            - submitted:  是否已提交偏好信号（仅 provider 可调用 + success 且
                          提交成功时为 True，否则 False）
        """
        action = str(action_result.get("action", ""))
        result = str(action_result.get("result", ""))
        score = _SCORE_BY_RESULT.get(result, _DEFAULT_SCORE)
        signal = _score_to_signal(score)

        submitted = False
        provider = self.tuner_provider
        if provider is not None and callable(provider) and result == "success":
            submitted = await self._submit_signal(provider, signal, action_result)
        return {
            "action": action,
            "result": result,
            "score": score,
            "signal": signal,
            "submitted": submitted,
        }

    async def _submit_signal(
        self, provider: Callable, signal: str, action_result: Dict[str, Any]
    ) -> bool:
        """调用 tuner_provider 提交偏好信号；失败记录日志并返回 False（不冒泡）。

        provider 返回 dict 时以 "submitted" 字段为准（兼容 submit_to_tuner 桥接，
        其内部对 HTTP 4xx/5xx / 连接失败返回 submitted=False 而非抛异常）；否则
        无异常即视为提交成功。
        """
        try:
            outcome = provider(signal=signal, action_result=action_result)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if isinstance(outcome, dict):
                return bool(outcome.get("submitted", True))
            return True
        except Exception as e:
            logger.error("偏好信号提交失败: %s", e)
            return False
