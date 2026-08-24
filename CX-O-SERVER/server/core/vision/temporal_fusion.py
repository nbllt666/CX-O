"""TemporalFusion —— 时序对齐多模态融合（视觉/语音/心率/OCR 联合叙事）。

背景（方案四 P2）：主动视觉进入「视频时代」后，视觉、语音、生理信号在 **时间轴**
这个共同坐标系上「合奏」。各模态各带自身时间戳，本模块把它们对齐到同一 clip
时间窗口 ``[startTs, endTs]``，再喂给 VLM 做联合理解，产出比单模态更准的叙事。

模态来源与时间戳锚点：
    - ``vision``   : 视觉片段（前端打包上传，``clip_ts`` 锚点）→ payload 常含描述文本
    - ``speech``   : 语音 ASR（``utterance_ts``，含 emotion/event）→ payload 常为转写文本
    - ``heartrate``: 心率广播（``hr_ts``）
    - ``ocr``      : 屏幕关键帧 OCR（``frame_ts``）→ payload 常为识别文字

设计约束（对齐 rules-0 §三 / 本仓库现有 vision 模块风格）：
    - 逻辑与数据分离：数据模型（TemporalStream / FusedContext）定义在顶部，逻辑下沉为方法。
    - 日志用 ``logging.getLogger(__name__)``（保留 INFO/WARNING）。
    - 配置读取复用 ``server.config get_settings``（对齐 video_understanding 的 ``_get_config()``）。
    - **本模块不引入真实 VLM 调用即可闭合**：``fuse`` 依赖一个可注入的
      ``understand_fn(fused_prompt)`` 回调；未提供时做**确定性组装**（把多流信息合并进
      content，合理降级），保证可测、不阻塞主链路。真实 VLM 接入留给后续。

降级策略（关键：清零/缺失模态优雅降级，不抛异常、不阻断）：
    - ``vision_enhanced.temporal_fusion_enabled=false`` 或缺少 heartrate 流时，
      ``fuse`` 退化为**双流**（只用 vision+speech），content 标注「（仅视觉+语音）」。
    - ``understand_fn`` 未提供或抛异常时，回退确定性组装（非空 content）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.config import get_settings
from server.core.vision.video_understanding import NarrativeSummary

logger = logging.getLogger(__name__)


#: 参与时间融合的模态枚举（约束 TemporalStream.modality 取值）
VALID_MODALITIES = ("vision", "speech", "heartrate", "ocr")
#: 双流退化仍保留的两个模态（视觉为主干 + 语音补充）
_DUAL_MODALITIES = ("vision", "speech")
#: 双流退化时 content 中标注的降级说明
_DUAL_STREAM_TAG = "（仅视觉+语音）"
#: 完整融合时 content 中标注的融合说明
_FUSED_TAG = "（多模态时间融合）"
#: payload 文本化后的单条截断长度，避免 prompt/摘要被超长 payload 撑爆
_PAYLOAD_TEXT_LIMIT = 200


@dataclass
class TemporalStream:
    """一路带时间戳的模态流条目。

    Attributes:
        modality: 模态类型（'vision' | 'speech' | 'heartrate' | 'ocr'）。
        ts: 该条目的时间戳（秒，落在 clip 时间轴 ``[startTs, endTs]`` 上）。
        payload: 该条目负载（任意类型，按模态约定不同：文本、dict 等）。
    """

    modality: str
    ts: float
    payload: Any


@dataclass
class FusedContext:
    """按 clip 时间窗口对齐后的统一上下文。

    Attributes:
        window: clip 时间窗口 ``{"startTs": float, "endTs": float}``。
        per_modality: 按模态分组的时序序列（每路均为按 ts 升序的 ``list[TemporalStream]``）。
        sorted_events: 窗口内全部条目按 (ts, modality) 升序展平的统一时间轴。
    """

    window: Dict[str, float] = field(default_factory=dict)
    per_modality: Dict[str, List[TemporalStream]] = field(default_factory=dict)
    sorted_events: List[TemporalStream] = field(default_factory=list)


class TemporalFusion:
    """时序对齐多模态融合器。

    :meth:`align` 负责把多路带时间戳的模态流对齐到同一 clip 时间窗口；
    :meth:`fuse` 负责喂 VLM 联合理解（可注入 ``understand_fn``），缺 heartrate 或
    ``temporal_fusion_enabled=false`` 时退化为视觉+语音双流。
    """

    # ------------------------------------------------------------------ #
    # 配置读取（对齐仓库方式：server/config.py get_settings → UnifiedConfig）
    # ------------------------------------------------------------------ #
    def _get_config(self) -> Any:
        """读取全局配置单例。测试可通过 monkeypatch 本模块的 ``get_settings`` 覆盖。"""
        return get_settings().config

    def _temporal_fusion_enabled(self) -> bool:
        """读取 ``vision_enhanced.temporal_fusion_enabled``（缺失字段回退 False）。"""
        try:
            cfg = self._get_config()
            return bool(getattr(cfg.vision_enhanced, "temporal_fusion_enabled", False))
        except Exception as exc:  # noqa: BLE001 —— 配置异常按双流降级处理
            logger.warning("TemporalFusion: 读取 temporal_fusion_enabled 失败（%s），按双流降级", exc)
            return False

    # ------------------------------------------------------------------ #
    # 对齐
    # ------------------------------------------------------------------ #
    def align(
        self,
        streams: List[TemporalStream],
        window: Optional[Tuple[float, float]] = None,
    ) -> FusedContext:
        """把多路模态流对齐到同一 clip 时间窗口。

        按窗口 ``[startTs, endTs]``（闭区间）过滤各模态在窗口内的条目，再按模态分组、
        每组内按 ts 升序排序；同时把窗口内全部条目展平为按 (ts, modality) 升序的
        统一时间轴 ``sorted_events``。

        Args:
            streams: 待对齐的模态流列表（可为空）。
            window: clip 时间窗口 ``(startTs, endTs)``；``None`` 表示不按窗口过滤。

        Returns:
            FusedContext：含 window / per_modality / sorted_events。窗口无条目也能返回
            合理空结果，不抛异常。
        """
        # 归一化窗口：None → (负无穷, 正无穷) 即不过滤；确保闭区间一致性
        start, end = (window if window is not None else (float("-inf"), float("inf")))

        filtered: List[TemporalStream] = []
        for s in streams or []:
            try:
                ts = float(getattr(s, "ts", 0.0))
            except (TypeError, ValueError):
                ts = 0.0
            if start <= ts <= end:
                filtered.append(
                    TemporalStream(
                        modality=str(getattr(s, "modality", "")),
                        ts=ts,
                        payload=getattr(s, "payload", None),
                    )
                )

        per_modality: Dict[str, List[TemporalStream]] = {}
        for s in filtered:
            per_modality.setdefault(s.modality, []).append(s)
        for evts in per_modality.values():
            evts.sort(key=lambda x: x.ts)

        sorted_events = sorted(filtered, key=lambda x: (x.ts, str(x.modality)))

        window_dict = {"startTs": start, "endTs": end}
        return FusedContext(
            window=window_dict,
            per_modality=per_modality,
            sorted_events=sorted_events,
        )

    # ------------------------------------------------------------------ #
    # 融合
    # ------------------------------------------------------------------ #
    def fuse(
        self,
        fused: FusedContext,
        base_narrative: Optional[NarrativeSummary] = None,
        understand_fn: Optional[Callable] = None,
    ) -> NarrativeSummary:
        """联合理解多流上下文，产出综合叙事。

        流程：
            1. 读 ``temporal_fusion_enabled``；False 或缺 heartrate 流 → **双流退化**。
            2. 否则联合理解：
               - 提供 ``understand_fn`` → 调用它（prompt 由本模块组装）；调用失败也回退确定性组装。
               - 未提供 ``understand_fn`` → 确定性组装（多流合并进 content，合理降级）。
        任何路径都不抛异常、不因缺失模态而阻断。

        Args:
            fused: :meth:`align` 产出的对齐上下文。
            base_narrative: 可选的视觉主干叙事摘要（VisionUnderstanding 产出），用于承载
                events/clip_ts/source 等元信息；为 ``None`` 时由本方法从 fused 推导默认值。
            understand_fn: 可注入的 LLM 联合理解回调 ``callable(prompt: str)``，返回
                ``str`` / ``NarrativeSummary`` / 含 ``content`` 的 dict（内部归一化）。

        Returns:
            NarrativeSummary：综合叙事（视觉为主干，语音/心率/OCR 为补充）。
        """
        enabled = self._temporal_fusion_enabled()
        has_heartrate = bool((fused.per_modality or {}).get("heartrate"))

        if not enabled or not has_heartrate:
            return self._fuse_dual(
                fused=fused,
                base_narrative=base_narrative,
                reason="enabled=false" if not enabled else "缺少心率流",
            )

        # ---- 完整融合（含心率）路径 ----
        if understand_fn is not None:
            try:
                prompt = self._build_joint_prompt(fused)
                result = understand_fn(prompt)
                return self._narrative_from_result(
                    result=result,
                    fused=fused,
                    base_narrative=base_narrative,
                )
            except Exception as exc:  # noqa: BLE001 —— 真实 VLM 失败回退确定性组装
                logger.warning("TemporalFusion: understand_fn 调用失败（%s），回退确定性组装", exc)

        return self._fuse_deterministic(fused=fused, base_narrative=base_narrative)

    # ------------------------------------------------------------------ #
    # 内部组装
    # ------------------------------------------------------------------ #
    def _fuse_dual(
        self,
        fused: FusedContext,
        base_narrative: Optional[NarrativeSummary],
        reason: str,
    ) -> NarrativeSummary:
        """双流退化：只用 vision+speech（只叠加语音，不做心率）。

        content 标注「（仅视觉+语音）」。即便两流都缺失，也产出非空、可消费的摘要，
        不抛异常（满足「清零/缺失模态优雅降级」）。
        """
        blocks: List[str] = []
        blocks.append(_DUAL_STREAM_TAG)
        vision_blocks = self._serialize_modality(
            (fused.per_modality or {}).get("vision", [])
        )
        speech_blocks = self._serialize_modality(
            (fused.per_modality or {}).get("speech", [])
        )
        if vision_blocks:
            blocks.append(f"视觉：{'，'.join(vision_blocks)}")
        if speech_blocks:
            blocks.append(f"语音：{'，'.join(speech_blocks)}")
        if len(blocks) == 1:  # 两流均无可用内容
            blocks.append("（无可用视觉/语音流，已按双流降级）")

        logger.info(
            "TemporalFusion: 双流退化 reason=%s vision=%d speech=%d hr=%d",
            reason,
            len((fused.per_modality or {}).get("vision", [])),
            len((fused.per_modality or {}).get("speech", [])),
            len((fused.per_modality or {}).get("heartrate", [])),
        )
        return self._make_narrative(
            content="；".join(blocks),
            fused=fused,
            base_narrative=base_narrative,
            degraded=True,
        )

    def _fuse_deterministic(
        self,
        fused: FusedContext,
        base_narrative: Optional[NarrativeSummary],
    ) -> NarrativeSummary:
        """确定性组装（未提供 understand_fn 或真实 VLM 失败时的兜底）。

        视觉为主干，语音/心率/OCR 按时间轴补充，content 标注「（多模态时间融合）」。
        各模态缺失时跳过对应段，不阻塞。
        """
        blocks: List[str] = [_FUSED_TAG]
        entries = (fused.per_modality or {})

        vision_blocks = self._serialize_modality(entries.get("vision", []))
        speech_blocks = self._serialize_modality(entries.get("speech", []))
        hr_blocks = self._serialize_modality(entries.get("heartrate", []))
        ocr_blocks = self._serialize_modality(entries.get("ocr", []))

        if vision_blocks:
            blocks.append(f"视觉（主干）：{'，'.join(vision_blocks)}")
        if speech_blocks:
            blocks.append(f"语音：{'，'.join(speech_blocks)}")
        if hr_blocks:
            blocks.append(f"心率：{'，'.join(hr_blocks)}")
        if ocr_blocks:
            blocks.append(f"屏幕OCR：{'，'.join(ocr_blocks)}")
        if len(blocks) == 1:  # 全流均无可序列化内容
            blocks.append("（无可用模态流，已按确定性组装降级）")

        logger.info(
            "TemporalFusion: 确定性组装 vision=%d speech=%d hr=%d ocr=%d",
            len(entries.get("vision", [])),
            len(entries.get("speech", [])),
            len(entries.get("heartrate", [])),
            len(entries.get("ocr", [])),
        )
        return self._make_narrative(
            content="；".join(blocks),
            fused=fused,
            base_narrative=base_narrative,
            degraded=False,
        )

    def _narrative_from_result(
        self,
        result: Any,
        fused: FusedContext,
        base_narrative: Optional[NarrativeSummary],
    ) -> NarrativeSummary:
        """把 understand_fn 的产物归一化为 NarrativeSummary。

        兼容返回 str / NarrativeSummary / 含 ``content`` 的 dict / 其他可字符串化对象。
        """
        if isinstance(result, NarrativeSummary):
            return result
        if isinstance(result, str):
            content = result.strip() or "（多模态时间融合）"
            return self._make_narrative(
                content=content,
                fused=fused,
                base_narrative=base_narrative,
                degraded=False,
            )
        if isinstance(result, dict) and result.get("content"):
            content = str(result["content"]).strip()
            return self._make_narrative(
                content=content,
                fused=fused,
                base_narrative=base_narrative,
                degraded=False,
            )
        # 兜底：可字符串化对象
        return self._make_narrative(
            content=str(result) or "（多模态时间融合）",
            fused=fused,
            base_narrative=base_narrative,
            degraded=False,
        )

    def _build_joint_prompt(self, fused: FusedContext) -> str:
        """组装交给 VLM 的联合理解 prompt（时间轴序列 + 各模态时间序列）。"""
        lines: List[str] = [
            "你是时序多模态叙事理解器。综合以下 clip 窗口内的视觉/语音/心率/OCR",
            "信息，产出以视觉为主干、其余模态为补充的完整叙事。",
        ]
        win = fused.window or {}
        lines.append(f"clip 时间窗口：[{win.get('startTs', 0.0):.1f}s, {win.get('endTs', 0.0):.1f}s]")
        lines.append("\n统一时间轴事件：")
        for s in fused.sorted_events:
            lines.append(f"- t={s.ts:.1f}s [{s.modality}] {self._payload_text(s.payload)}")
        for mod in ("vision", "speech", "heartrate", "ocr"):
            rows = (fused.per_modality or {}).get(mod, [])
            if rows:
                lines.append(f"\n{mod} 时间序列：")
                for s in rows:
                    lines.append(f"  t={s.ts:.1f}s {self._payload_text(s.payload)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # 纯工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _serialize_modality(events: List[TemporalStream]) -> List[str]:
        """把某一路模态的时间序列文本化（按 ts 升序，一条一文本）。"""
        out: List[str] = []
        for s in events or []:
            text = TemporalFusion._payload_text(s.payload)
            if text:
                out.append(f"[t={s.ts:.1f}s]{text}")
        return out

    @staticmethod
    def _payload_text(payload: Any) -> str:
        """把任意 payload 安全文本化。

        优先提取常见文本字段（text/content/transcript/description/vision_description），
        否则退化为 str(payload)；超长截断，避免污染 prompt/摘要。
        """
        if payload is None:
            return ""
        if isinstance(payload, str):
            text = payload
        elif isinstance(payload, dict):
            text = ""
            for key in ("text", "content", "transcript", "description", "vision_description"):
                if payload.get(key):
                    text = str(payload[key])
                    break
            if not text:
                text = str(payload)
        else:
            text = str(payload)
        text = text.strip()
        if len(text) > _PAYLOAD_TEXT_LIMIT:
            text = text[:_PAYLOAD_TEXT_LIMIT] + "…"
        return text

    @staticmethod
    def _make_narrative(
        content: str,
        fused: FusedContext,
        base_narrative: Optional[NarrativeSummary],
        degraded: bool,
    ) -> NarrativeSummary:
        """把组装后的 content 与 fused/base 元信息合成最终 NarrativeSummary。"""
        win = fused.window or {}
        clip_ts = float(win.get("startTs", 0.0) or 0.0)
        base = base_narrative if base_narrative is not None else None

        events = list(base.events) if base is not None and base.events else ["video_clip"]
        emotion = base.emotion if base is not None and base.emotion else "中性"
        source = base.source if base is not None and base.source else ""
        event_type = base.event_type if base is not None and base.event_type else "video_clip"
        ocr_blocks = list(base.ocr_blocks) if base is not None and base.ocr_blocks else []
        if base is not None and base.clip_ts:
            clip_ts = base.clip_ts

        return NarrativeSummary(
            content=content,
            events=events,
            emotion=emotion,
            clip_ts=clip_ts,
            source=source,
            event_type=event_type,
            confidence=float(getattr(base, "confidence", 1.0) if base else 1.0),
            native_used=bool(getattr(base, "native_used", False) if base else False),
            degraded=degraded,
            ocr_blocks=ocr_blocks,
        )


__all__ = [
    "TemporalStream",
    "FusedContext",
    "TemporalFusion",
    "VALID_MODALITIES",
]