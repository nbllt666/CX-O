"""帧筛选器 FrameFilter——独立小 VLM 三态判定（spec add-vlm-frame-filter-face-match T4.1）。

职责：
    对单帧画面执行「forward / summarize / discard」三态筛选判定，决定该帧是否
    转发给主对话 LLM、仅沉淀摘要记忆、还是直接筛除。判定由独立小 VLM 完成
    （OpenAI 兼容 ``/v1/chat/completions``），并把主模型会话的最近 N 条消息文本
    注入 prompt，使筛选模型感知"当前在聊什么"。

endpoint/model 回退链（决策点 #3）：
    1. 专属配置 ``vision_enhanced.filter_vlm_endpoint`` / ``filter_vlm_model``
       （各自非空优先）；
    2. 为空逐字段回退 ``multimodal_pipeline.vision_base_url`` / ``vision_model``；
    3. 仍为空 → (None, None) = 筛选层不可用 → 按 ``filter_fail_mode`` 降级。

降级语义（不抛异常、不阻塞）：
    配置落空 / 调用超时 / 连接失败 / HTTP 非 200 / JSON 不可解析时，按
    ``filter_fail_mode`` 返回兜底判定（passthrough=forward 保持直通语义 /
    discard=discard 省 token），``degraded=True``。

摘要沉淀：
    ``action=summarize`` 且 summary 非空时，构造轻量 ``NarrativeSummary``
    （event_type='frame_summary'）交 ``NarrativeVisionMemory.sediment`` 沉淀为
    source='vision' 的记忆；沉淀失败仅记日志，不影响判定返回。

隐私红线：
    帧图像仅存在于请求链路内存中，本模块不落盘、不写日志携带帧数据。

部署边界（单进程）：
    模块级单例 ``get_frame_filter()`` 与 NarrativeVisionMemory 依赖均为进程内态，
    与整服务单 worker 架构一致（见 vision 路由模块 docstring）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from server.config import get_settings

logger = logging.getLogger(__name__)

#: 合法三态判定
_VALID_ACTIONS = ("forward", "summarize", "discard")
#: 合法重要程度三档
_VALID_IMPORTANCE = ("low", "medium", "high")
#: 上下文单条消息截断长度（字符）
_CONTEXT_TRUNCATE_CHARS = 200
#: 上下文条数缺省值（配置读取失败时）
_DEFAULT_CONTEXT_MESSAGES = 6
#: 调用超时缺省值（秒，配置读取失败时）
_DEFAULT_TIMEOUT_SECONDS = 8.0
#: 会话无消息时的上下文占位文本
_NO_CONTEXT_TEXT = "（无近期对话）"


@dataclass
class FrameFilterDecision:
    """帧筛选三态判定结果（字段对齐 public/interface_stub/vision.pyi::FrameFilterDecision）。

    Attributes:
        action: 三态判定：forward 转发主 LLM / summarize 仅摘要沉淀 / discard 筛除。
        summary: 帧内容一句话摘要（VLM 三态均产出；降级时为空串）。
        reason: 判定理由（供审计与调试回溯；降级时为降级原因）。
        importance: 帧重要程度三档，缺省 medium。
        degraded: 是否降级产出（VLM 超时/解析失败等按 filter_fail_mode 兜底）。
    """

    action: str
    summary: str = ""
    reason: str = ""
    importance: str = "medium"
    degraded: bool = False


class _VLMCallError(Exception):
    """内部异常：筛选 VLM 调用失败（携带降级原因文本，由 filter_frame 捕获转降级）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _build_chat_url(endpoint: str) -> str:
    """把 base endpoint 归一为 OpenAI 兼容 chat/completions 完整 URL。

    专属配置可能带 ``/v1`` 后缀（如 ``http://host:8100/v1``），也可能不带
    （如 multimodal 回退通道的 ``http://host:8080``），统一归一避免 ``/v1/v1``。
    """
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


class FrameFilter:
    """独立小 VLM 帧筛选判定器。

    Args:
        context_manager: 可选 ContextManager 实例（测试注入用）；缺省懒加载
            ``server.dependencies.get_context_manager()``（服务未初始化时按
            无上下文处理，不抛异常）。
        memory: 可选 ``NarrativeVisionMemory`` 实例（测试注入用）；缺省懒加载单例。
    """

    def __init__(
        self,
        context_manager: Optional[Any] = None,
        memory: Optional[Any] = None,
    ) -> None:
        self._context_manager = context_manager
        self._memory = memory
        self._memory_instance: Optional[Any] = None  # 未注入时的懒加载实例

    # ------------------------------------------------------------------ #
    # 配置读取（延迟读取，热更新友好；单例不缓存配置）
    # ------------------------------------------------------------------ #
    def _read_config(self) -> Optional[Any]:
        """读取 vision_enhanced 配置段；读取失败返回 None（调用方走降级）。"""
        try:
            return get_settings().config.vision_enhanced
        except Exception as exc:  # noqa: BLE001
            logger.warning("FrameFilter: 读取 vision_enhanced 配置失败（%s），按不可用降级", exc)
            return None

    def _resolve_endpoint_model(self) -> Tuple[Optional[str], Optional[str]]:
        """解析筛选 VLM endpoint/model（专属配置→multimodal vision 回退→不可用）。"""
        ve = self._read_config()
        endpoint = str(getattr(ve, "filter_vlm_endpoint", "") or "").strip() if ve is not None else ""
        model = str(getattr(ve, "filter_vlm_model", "") or "").strip() if ve is not None else ""
        # 逐字段非空优先，空字段回退 multimodal vision 通道
        if not endpoint or not model:
            try:
                mm = get_settings().config.multimodal_pipeline
                fb_endpoint = str(getattr(mm, "vision_base_url", "") or "").strip()
                fb_model = str(getattr(mm, "vision_model", "") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("FrameFilter: 读取 multimodal_pipeline 回退配置失败（%s）", exc)
                fb_endpoint = fb_model = ""
            endpoint = endpoint or fb_endpoint
            model = model or fb_model
        if not endpoint or not model:
            return None, None
        return endpoint, model

    def _fail_mode(self, ve: Optional[Any]) -> str:
        """读取降级兜底模式（非法值回退 passthrough）。"""
        mode = str(getattr(ve, "filter_fail_mode", "passthrough") or "passthrough").strip().lower()
        if mode not in ("passthrough", "discard"):
            mode = "passthrough"
        return mode

    def _degraded_decision(self, ve: Optional[Any], reason: str) -> FrameFilterDecision:
        """按 filter_fail_mode 构造降级判定（passthrough=forward / discard=discard）。"""
        mode = self._fail_mode(ve)
        action = "discard" if mode == "discard" else "forward"
        return FrameFilterDecision(action=action, summary="", reason=reason, importance="medium", degraded=True)

    # ------------------------------------------------------------------ #
    # 上下文注入
    # ------------------------------------------------------------------ #
    def _get_context_manager(self) -> Optional[Any]:
        """获取 ContextManager：优先注入实例，缺省懒加载全局（失败返回 None 不抛）。"""
        if self._context_manager is not None:
            return self._context_manager
        try:
            from server.dependencies import get_context_manager

            cm = get_context_manager()
        except Exception:  # noqa: BLE001  服务未初始化/依赖缺失——按无上下文处理
            return None
        self._context_manager = cm
        return cm

    async def _fetch_context_text(self, session_id: str) -> str:
        """取该会话最近 filter_context_messages 条消息并文本化（单条截断 200 字符）。

        会话不存在 / 无消息 / 读取失败 → ``（无近期对话）``（读路径不自动建会话，
        对齐 chat 路由 C9 约定）。优先使用 ContextManager 的 async 变体。
        """
        ve = self._read_config()
        try:
            limit = int(getattr(ve, "filter_context_messages", _DEFAULT_CONTEXT_MESSAGES))
        except (TypeError, ValueError):
            limit = _DEFAULT_CONTEXT_MESSAGES

        messages: List[Dict[str, Any]] = []
        cm = self._get_context_manager()
        if cm is not None:
            try:
                if hasattr(cm, "get_recent_messages_async"):
                    messages = await cm.get_recent_messages_async(session_id, limit=limit)
                else:
                    messages = await asyncio.to_thread(cm.get_recent_messages, session_id, limit=limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("FrameFilter: 读取会话 %s 上下文失败（%s），按无上下文处理", session_id, exc)
                messages = []

        lines: List[str] = []
        for msg in messages or []:
            msg = msg or {}
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            role = str(msg.get("role") or "?").strip()
            if len(content) > _CONTEXT_TRUNCATE_CHARS:
                content = content[:_CONTEXT_TRUNCATE_CHARS] + "…"
            lines.append(f"{role}: {content}")
        if not lines:
            return _NO_CONTEXT_TEXT
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Prompt 构造
    # ------------------------------------------------------------------ #
    def _build_system_prompt(self, context_text: str) -> str:
        """系统 prompt：角色定义 + 会话上下文注入。"""
        return (
            "你是主动视觉系统的帧筛选判定器（独立小模型），负责判断当前画面帧"
            "是否值得转发给主对话模型、仅沉淀摘要、还是直接筛除。\n"
            "【当前对话近期上下文】\n"
            f"{context_text}\n"
            "请结合上述上下文判断画面与当前对话的相关性与信息价值。"
        )

    def _build_user_text(self, face_labels: Optional[List[str]], source: str) -> str:
        """用户 prompt 文本部分：face_labels + 判定规则 + JSON only 输出说明。"""
        lines = [f"请对当前这一帧画面（来源：{source}）执行三态判定。"]
        if face_labels:
            lines.append("画面中识别到：" + "；".join(face_labels))
        else:
            lines.append("画面中无人脸识别结果。")
        lines.append(
            "判定规则：\n"
            "- forward：画面与当前对话相关，或明显值得即时回应（需要主模型看图对话）；\n"
            "- summarize：画面有信息量但无需即时对话（仅沉淀摘要记忆）；\n"
            "- discard：画面静止/重复/无信息，直接筛除。\n"
            "只输出一个 JSON 对象，不要输出任何其他文字：\n"
            '{"action": "forward|summarize|discard", "summary": "一句话摘要", '
            '"reason": "简短理由", "importance": "low|medium|high"}'
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # VLM 调用（同步阻塞 requests 经线程包裹，避免卡事件循环）
    # ------------------------------------------------------------------ #
    async def _call_vlm(
        self,
        endpoint: str,
        model: str,
        system_text: str,
        user_text: str,
        image_b64: str,
        timeout: float,
    ) -> str:
        """调用筛选 VLM（OpenAI 兼容 /v1/chat/completions + image_url dataURL 形态）。

        Returns:
            助手回复原始文本。

        Raises:
            _VLMCallError: requests 缺失 / 超时 / 连接失败 / HTTP 非 200 / 响应格式无效。
        """
        try:
            import requests
        except ImportError as exc:
            raise _VLMCallError("requests 未安装，无法调用筛选 VLM") from exc

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_text},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_b64}},
                    ],
                },
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }
        url = _build_chat_url(endpoint)
        try:
            resp = await asyncio.to_thread(
                requests.post,
                url,
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.Timeout as exc:
            raise _VLMCallError(f"筛选 VLM 调用超时（{timeout}s）") from exc
        except requests.exceptions.ConnectionError as exc:
            raise _VLMCallError(f"筛选 VLM 连接失败: {url}") from exc
        except Exception as exc:  # noqa: BLE001
            raise _VLMCallError(f"筛选 VLM 调用异常: {exc.__class__.__name__}") from exc

        if resp.status_code != 200:
            raise _VLMCallError(f"筛选 VLM 返回 HTTP {resp.status_code}")
        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise _VLMCallError("筛选 VLM 响应格式无效（缺少 choices/message/content）") from exc
        if not isinstance(text, str) or not text.strip():
            raise _VLMCallError("筛选 VLM 返回内容为空")
        return text

    # ------------------------------------------------------------------ #
    # JSON 解析与校验
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_json(text: str) -> Optional[Any]:
        """解析 JSON（容忍 ```json 围栏）；不可解析返回 None。"""
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[A-Za-z]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    def _parse_decision(self, text: str) -> Optional[FrameFilterDecision]:
        """把 VLM 回复文本解析为判定；action 非法返回 None（调用方降级）。"""
        parsed = self._extract_json(text)
        if not isinstance(parsed, dict):
            return None
        action = str(parsed.get("action") or "").strip().lower()
        if action not in _VALID_ACTIONS:
            return None
        summary = str(parsed.get("summary") or "").strip()
        reason = str(parsed.get("reason") or "").strip()
        importance = str(parsed.get("importance") or "medium").strip().lower()
        if importance not in _VALID_IMPORTANCE:
            importance = "medium"
        if action == "summarize" and not summary:
            # summarize 但摘要为空：无法沉淀，降为 discard（非 VLM 故障，不算 degraded）
            action = "discard"
            reason = (reason + "；" if reason else "") + "summary 为空，已降为 discard"
        return FrameFilterDecision(
            action=action, summary=summary, reason=reason, importance=importance, degraded=False
        )

    # ------------------------------------------------------------------ #
    # 摘要沉淀
    # ------------------------------------------------------------------ #
    def _get_memory(self) -> Any:
        """获取 NarrativeVisionMemory：优先注入实例，缺省懒加载单例。"""
        if self._memory is not None:
            return self._memory
        if self._memory_instance is None:
            from server.core.vision.narrative_memory import NarrativeVisionMemory

            self._memory_instance = NarrativeVisionMemory()
        return self._memory_instance

    def _sediment_summary(self, summary: str, session_id: str, ts: Optional[float], source: str) -> None:
        """summarize 判定的摘要沉淀（构造轻量 NarrativeSummary 复用既有记忆链路）。

        try/except 全包：沉淀失败仅记日志，不抛异常不影响判定返回。
        """
        try:
            from server.core.vision.video_understanding import NarrativeSummary

            narrative = NarrativeSummary(
                content=summary,
                events=[],
                clip_ts=float(ts) if ts is not None else 0.0,
                source=source if source in ("camera", "screen") else "camera",
                event_type="frame_summary",
                confidence=0.6,
                native_used=False,
                degraded=False,
                ocr_blocks=[],
            )
            self._get_memory().sediment(narrative, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FrameFilter: 帧摘要沉淀失败（不影响判定返回）: %s", exc)

    # ------------------------------------------------------------------ #
    # 核心入口
    # ------------------------------------------------------------------ #
    async def filter_frame(
        self,
        image_b64: str,
        *,
        agent_id: str,
        session_id: str,
        source: str,
        ts: Optional[float] = None,
        face_labels: Optional[List[str]] = None,
    ) -> FrameFilterDecision:
        """对单帧执行三态筛选判定（主入口，全异步不阻塞事件循环）。

        Args:
            image_b64: 帧图像（dataURL 或 base64 原串，透传给 VLM）。
            agent_id: 会话归属 Agent ID（预留：档案归属与审计；上下文读取按 session_id）。
            session_id: 会话 ID（ContextManager 上下文读取与摘要沉淀归属）。
            source: 帧来源（camera | screen）。
            ts: 帧时间戳（秒，可空；沉淀时落 clip_ts）。
            face_labels: 可选人脸标签（来自面部匹配，如 ["小A", "未知人脸×1"]）。

        Returns:
            FrameFilterDecision；任何失败路径均按 filter_fail_mode 降级返回，不抛异常。
        """
        ve = self._read_config()
        endpoint, model = self._resolve_endpoint_model()
        if endpoint is None or model is None:
            logger.info("FrameFilter: 筛选 VLM 未配置（回退链落空），按 fail_mode 降级")
            return self._degraded_decision(
                ve, "筛选模型未配置（filter_vlm_endpoint/model 与 multimodal vision 回退链均落空）"
            )

        try:
            timeout = float(getattr(ve, "filter_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS))
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT_SECONDS

        context_text = await self._fetch_context_text(session_id)
        system_text = self._build_system_prompt(context_text)
        user_text = self._build_user_text(face_labels, source)

        try:
            text = await self._call_vlm(endpoint, model, system_text, user_text, image_b64, timeout)
        except _VLMCallError as exc:
            logger.warning("FrameFilter: %s，按 fail_mode 降级", exc.reason)
            return self._degraded_decision(ve, exc.reason)

        decision = self._parse_decision(text)
        if decision is None:
            # 日志只留原文片段，严禁携带帧数据（隐私红线）
            logger.warning("FrameFilter: 判定 JSON 解析失败，按 fail_mode 降级；回复片段: %s", text[:120])
            return self._degraded_decision(ve, "筛选 VLM 返回内容无法解析为有效 JSON 判定")

        if decision.action == "summarize":
            self._sediment_summary(decision.summary, session_id, ts, source)
        return decision


# ---------------------------------------------------------------------- #
# 模块级单例（配置延迟读取：单例不持有配置，每次判定时读取，热更新即时生效）
# ---------------------------------------------------------------------- #
_frame_filter: Optional[FrameFilter] = None


def get_frame_filter() -> FrameFilter:
    """获取帧筛选器模块级单例。"""
    global _frame_filter
    if _frame_filter is None:
        _frame_filter = FrameFilter()
    return _frame_filter
