"""VideoUnderstanding —— 主动视觉视频理解管线（队列 consumer）。

职责（仅消费，不做记忆写入）：
    本模块作为 ``vision_clip_queue`` 的 consumer，把队列送来的视频片段喂给
    MultimodalPipeline（video 模态），产出「叙事性摘要」``NarrativeSummary``，
    供下游 NarrativeVisionMemory（Task8）做叙事记忆沉淀。

核心流程（``understand``）:
    1. 调用 ``MultimodalPipeline.preprocess('video', clip_path)`` 拿 artifact
       （视频模态仅当 ``llm.provider == "vllm"`` 且 vllm_native 启用时走 vLLM
       原生解码；否则在管线内降级为占位，native_decode_used=False）。
    2. 分支判定：
       - **原生路径**：基于 artifact 的文本（text_content，或
         extra_metadata.vision_description），组织成叙事化形态（过程/动作/因果/情绪）。
       - **降级单帧快照**（``vision_enhanced.require_vllm`` 且 provider != vllm，
         或 artifact.native_decode_used=False / vision_degraded）：尝试抽取 1-2 个
         关键帧做 OCR/描述，产出单帧快照型 summary，``degraded=True``。若环境无
         cv2/imageio/av 无法解帧，则退化为在 artifact 占位文字上节略，仍 non-blocking。
    3. 可选 OCR：``ocr_keyframe_enabled`` 且 source=screen 时，对关键帧走
       ``ImageWorker.ocr`` 读屏字并入 summary。无法解帧则跳过（ocr_blocks 为空），
       不阻塞主流程。
    4. 超时：以 ``multimodal_pipeline.task_timeout_seconds`` 作为单任务超时，
       超时抛 TimeoutError，由队列 ``finally`` 兜底清理临时片段。

设计对齐（rules-0 §三 sorting / 日志规范）:
    - 逻辑与数据分离：数据模型（NarrativeSummary）定义在本文件顶部，逻辑下沉为方法。
    - 日志用 ``logging.getLogger(__name__)``（保留 INFO/WARNING，含片段时间戳信息）。
    - 复用 ``multimodal_pipeline`` / ``workers.image_worker``，不重复造轮子。
    - 不实现记忆写入（下游 Task8 承载 NarrativeVisionMemory）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from server.config import get_settings

logger = logging.getLogger(__name__)

# 默认任务超时（秒）—— 由 multimodal_pipeline.task_timeout_seconds 覆盖
_DEFAULT_TASK_TIMEOUT_SECONDS = 120
#: 降级单帧快照最多抽取的关键帧数（环境支持解帧时）
_MAX_KEYFRAMES = 2
#: 允许对屏幕源做 OCR；摄像头源不做（读屏字仅对屏幕有意义）
_OCR_TARGET_SOURCE = "screen"


@dataclass
class NarrativeSummary:
    """视频片段的叙事性摘要（供下游叙事记忆沉淀消费）。

    Attributes:
        content: 叙事性文字摘要（过程/动作/因果/情绪的组成文本）。
        events: 提炼出的事件列表（至少含触发事件类型，缺省为 ["video_clip"]）。
        emotion: 情绪推断（当前无 LLM 二次调用，缺省中性，可被下游升级）。
        clip_ts: 片段触发时间戳（秒）。
        source: 片段来源（camera/screen）。
        event_type: 触发事件类型。
        confidence: 理解置信度（0-1，源自 artifact.confidence）。
        native_used: 是否走了 vLLM 原生视频解码。
        degraded: 是否降级（单帧快照/原生未用）。
        ocr_blocks: 关键帧 OCR 文本块（可选，未做则为空）。
    """

    content: str
    events: List[str] = field(default_factory=list)
    emotion: str = "中性"
    clip_ts: float = 0.0
    source: str = ""
    event_type: str = ""
    confidence: float = 1.0
    native_used: bool = False
    degraded: bool = False
    ocr_blocks: List[Dict[str, Any]] = field(default_factory=list)


class VideoUnderstanding:
    """视频理解管线（队列 consumer）。

    消费 ``vision_clip_queue``，产出 ``NarrativeSummary``。
    通过 ``register_as_consumer(queue)`` 注册到队列；consumer 也可用同步/异步函数，
    本类 ``consume`` 为异步函数（对齐 ``VisionClipQueue.set_consumer`` 的
    ``async consumer(item)`` 签名，见 clip_queue.py）。

    Args:
        pipeline: 可选 MultimodalPipeline 实例（测试注入用；缺省懒加载单例）。
        image_worker: 可选 ImageWorker 实例（测试注入用；缺省懒加载）。
    """

    def __init__(
        self,
        pipeline: Optional[Any] = None,
        image_worker: Optional[Any] = None,
    ) -> None:
        self._pipeline = pipeline
        self._image_worker = image_worker

    # ------------------------------------------------------------------ #
    # 懒加载依赖
    # ------------------------------------------------------------------ #
    @property
    def pipeline(self) -> Any:
        """懒加载 MultimodalPipeline（模块级单例，避免重复初始化耗时）。"""
        if self._pipeline is None:
            from server.core.multimodal.multimodal_pipeline import (
                MultimodalPipeline,
            )

            self._pipeline = MultimodalPipeline()
        return self._pipeline

    @property
    def image_worker(self) -> Any:
        """懒加载 ImageWorker（关键帧 OCR 用）。"""
        if self._image_worker is None:
            from server.core.multimodal.workers import ImageWorker

            self._image_worker = ImageWorker()
        return self._image_worker

    # ------------------------------------------------------------------ #
    # 配置读取（对齐仓库方式：server/config.py get_settings → UnifiedConfig）
    # ------------------------------------------------------------------ #
    def _get_config(self) -> Any:
        """读取全局配置单例。测试可通过 monkeypatch 本模块的 ``get_settings`` 覆盖。"""
        return get_settings().config

    def _task_timeout_seconds(self) -> int:
        """从 multimodal_pipeline.task_timeout_seconds 读取单任务超时。

        vision_enhanced 段不含超时字段，超时属于多模态管线配置（见 config.py
        MultimodalPipelineConfig.task_timeout_seconds）。读取失败回退默认 120s。
        """
        try:
            cfg = self._get_config()
            timeout = int(getattr(cfg.multimodal_pipeline, "task_timeout_seconds", 0))
            return timeout if timeout > 0 else _DEFAULT_TASK_TIMEOUT_SECONDS
        except Exception as exc:  # noqa: BLE001 —— 配置异常回退默认
            logger.warning("VideoUnderstanding: 读取任务超时失败（%s），回退默认 %ds", exc,
                           _DEFAULT_TASK_TIMEOUT_SECONDS)
            return _DEFAULT_TASK_TIMEOUT_SECONDS

    def _vision_enhanced(self) -> Dict[str, Any]:
        """读取 vision_enhanced 段关键开关（缺失字段回退默认）。"""
        try:
            ve = self._get_config().vision_enhanced
            return {
                "require_vllm": bool(getattr(ve, "require_vllm", True)),
                "ocr_keyframe_enabled": bool(getattr(ve, "ocr_keyframe_enabled", True)),
                "narrative_memory_enabled": bool(
                    getattr(ve, "narrative_memory_enabled", True)
                ),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("VideoUnderstanding: 读取 vision_enhanced 失败（%s），使用默认", exc)
            return {
                "require_vllm": True,
                "ocr_keyframe_enabled": True,
                "narrative_memory_enabled": True,
            }

    def _provider(self) -> str:
        """读取 LLM provider（小写）。"""
        try:
            provider = getattr(self._get_config().llm, "provider", "")
            return str(provider).lower().strip()
        except Exception:  # noqa: BLE001
            return "unknown"

    # ------------------------------------------------------------------ #
    # 核心：understand
    # ------------------------------------------------------------------ #
    async def understand(
        self,
        clip_path: str,
        event_meta: dict,
        source: str,
        ts: float,
    ) -> NarrativeSummary:
        """理解视频片段，产出叙事性摘要。

        Args:
            clip_path: 视频片段临时文件路径。
            event_meta: 事件元信息 dict（至少含 event_type）。
            source: 片段来源（'camera' | 'screen'）。
            ts: 事件触发时间戳（秒）。

        Returns:
            NarrativeSummary（原生/降级任一路径）。

        Raises:
            TimeoutError: 预处理超时（由队列 finally 兜底清理临时片段）。
            Exception: preprocess 抛出的其他异常（同样由队列兜底清理）。
        """
        timeout = self._task_timeout_seconds()
        ve = self._vision_enhanced()
        provider = self._provider()
        event_type = str((event_meta or {}).get("event_type") or "video_clip")
        ts_f = float(ts or 0.0)

        try:
            artifact = await self._preprocess_with_timeout(clip_path, timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"VideoUnderstanding: 视频理解超时（{timeout}s）：{clip_path}"
            )

        # 是否应走原生路径：require_vllm 且 provider=vllm 才要求原生；
        # 且 artifact 必须实际使用了原生解码且未被降级。
        wants_native = not (ve["require_vllm"] and provider != "vllm")
        native_used = bool(getattr(artifact, "native_decode_used", False)) and not bool(
            getattr(artifact, "vision_degraded", False)
        )
        degraded = not (wants_native and native_used)

        # 关键帧 OCR（可忽略缺失，不阻塞主流程）
        ocr_blocks: List[Dict[str, Any]] = []
        if ve["ocr_keyframe_enabled"] and source == _OCR_TARGET_SOURCE:
            ocr_blocks = await self._collect_keyframe_ocr(clip_path, ts_f, timeout)

        if degraded:
            summary = self._build_degraded_summary(
                artifact=artifact,
                clip_path=clip_path,
                event_type=event_type,
                source=source,
                ts=ts_f,
                ocr_blocks=ocr_blocks,
            )
        else:
            summary = self._build_narrative_summary(
                artifact=artifact,
                event_type=event_type,
                source=source,
                ts=ts_f,
                ocr_blocks=ocr_blocks,
            )

        logger.info(
            "VideoUnderstanding: 产出叙事摘要 source=%s event_type=%s degraded=%s "
            "confidence=%.2f ts=%.2f",
            source, event_type, summary.degraded, summary.confidence, ts_f,
        )
        return summary

    async def _preprocess_with_timeout(self, clip_path: str, timeout: int) -> Any:
        """以可配置超时调用 MultimodalPipeline.preprocess（同步阻塞 → 线程池）。"""
        return await asyncio.wait_for(
            asyncio.to_thread(self.pipeline.preprocess, "video", clip_path),
            timeout=timeout,
        )

    # ------------------------------------------------------------------ #
    # 关键帧 OCR（可跳过，不阻塞主流程）
    # ------------------------------------------------------------------ #
    async def _collect_keyframe_ocr(
        self, clip_path: str, ts: float, timeout: int
    ) -> List[Dict[str, Any]]:
        """抽取 1-2 个关键帧并 OCR，返回文本块列表。

        关键帧解帧失败（环境无 cv2/imageio/av）或 OCR 失败均静默跳过，返回空列表；
        抽取的临时关键帧在此 finally 清理（自身创建的临时文件，非队列片段本体）。
        """
        keyframes: List[str] = []
        try:
            for offset in range(_MAX_KEYFRAMES):
                frame = await asyncio.wait_for(
                    asyncio.to_thread(draw_keyframe, clip_path, ts + offset),
                    timeout=timeout,
                )
                if frame and os.path.isfile(frame) and frame not in keyframes:
                    keyframes.append(frame)
                if len(keyframes) >= _MAX_KEYFRAMES:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("VideoUnderstanding: 关键帧抽取异常，跳过 OCR: %s", exc)
            keyframes = []

        blocks: List[Dict[str, Any]] = []
        try:
            if keyframes:
                ocr_blocks, _avg_conf = await asyncio.to_thread(
                    self.image_worker.ocr, keyframes[0]
                )
                blocks = [b for b in (ocr_blocks or []) if isinstance(b, dict)]
                logger.info("VideoUnderstanding: 关键帧 OCR blocks=%d", len(blocks))
        except Exception as exc:  # noqa: BLE001
            logger.warning("VideoUnderstanding: 关键帧 OCR 失败，跳过恢复主流程: %s", exc)
            blocks = []
        finally:
            for kf in keyframes:
                try:
                    os.unlink(kf)
                except OSError:
                    pass
        return blocks

    # ------------------------------------------------------------------ #
    # 分支构建
    # ------------------------------------------------------------------ #
    def _build_narrative_summary(
        self,
        artifact: Any,
        event_type: str,
        source: str,
        ts: float,
        ocr_blocks: List[Dict[str, Any]],
    ) -> NarrativeSummary:
        """原生路径：基于 artifact 文本组织叙事化摘要（不重造视频理解）。

        把 vLLM 原生返回的视觉描述（或 extra_metadata.vision_description）组织成
        叙事形态 —— 过程（发生了什么）/ 动作 / 因果 / 情绪，并并入屏幕 OCR 文字。
        """
        vision_desc = str(getattr(artifact, "text_content", "") or "").strip()
        if not vision_desc:
            meta = getattr(artifact, "extra_metadata", {}) or {}
            vision_desc = str(meta.get("vision_description", "") or "").strip()

        ocr_text = _ocr_text(ocr_blocks)
        chunks: List[str] = []
        if vision_desc:
            chunks.append(f"片段过程：{vision_desc}")
        if ocr_text:
            chunks.append(f"屏幕文字：{ocr_text}")
        if event_type:
            chunks.append(f"触发事件：{event_type}")

        content = "；".join(chunks) if chunks else "（原生理解返回空描述）"
        confidence = float(getattr(artifact, "confidence", 1.0) or 1.0)

        return NarrativeSummary(
            content=content,
            events=[event_type],
            emotion="中性",
            clip_ts=ts,
            source=source,
            event_type=event_type,
            confidence=confidence,
            native_used=True,
            degraded=False,
            ocr_blocks=ocr_blocks,
        )

    def _build_degraded_summary(
        self,
        artifact: Any,
        clip_path: str,
        event_type: str,
        source: str,
        ts: float,
        ocr_blocks: List[Dict[str, Any]],
    ) -> NarrativeSummary:
        """降级路径：单帧快照型叙事摘要（degraded=True）。

        若 OCR 得到屏幕文字，则以关键帧文字为快照主体；否则退化为在 artifact
        占位文字上节略（环境无 cv2/imageio/av 时走此分支），仍可产出一个可消费的
        摘要，不抛异常。
        """
        ocr_text = _ocr_text(ocr_blocks)
        artifact_txt = str(getattr(artifact, "text_content", "") or "").strip()
        if not artifact_txt:
            meta = getattr(artifact, "extra_metadata", {}) or {}
            artifact_txt = str(meta.get("vision_description", "") or "").strip()

        if ocr_text:
            content = (
                f"[单帧快照·降级] 未能走 vLLM 原生视频理解，已抽取关键帧识别屏幕文字。"
                f"屏幕文字：{ocr_text}；触发事件：{event_type}。"
            )
        else:
            brief = artifact_txt[:150] or "（无可用的理解占位文字）"
            content = (
                f"[单帧快照·降级] 视频原生理解不可用，未能提取到可用关键帧，"
                f"基于占位信息节略：{brief}。触发事件：{event_type}。"
            )

        confidence = float(getattr(artifact, "confidence", 0.5) or 0.5)
        return NarrativeSummary(
            content=content,
            events=[event_type],
            emotion="中性",
            clip_ts=ts,
            source=source,
            event_type=event_type,
            confidence=confidence,
            native_used=False,
            degraded=True,
            ocr_blocks=ocr_blocks,
        )

    # ------------------------------------------------------------------ #
    # 队列 consumer 接入
    # ------------------------------------------------------------------ #
    async def consume(self, item: Dict[str, Any]) -> NarrativeSummary:
        """队列 consumer 回调（对齐 ``VisionClipQueue`` 的 ``async consumer(item)``）。

        从条目读取 clip_path / event_meta / source / ts，调用 ``understand``。
        记忆沉淀不在此处（下游 NarrativeVisionMemory）；异常由队列退出兜底清理，
        本方法仅保持 worker 不崩（异常向上抛由 ``_run`` 捕获记录并清理）。
        """
        clip_path = str(item.get("clip_path") or "")
        event_meta = item.get("event_meta") or {}
        source = str(item.get("source") or "")
        try:
            ts = float(item.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        return await self.understand(clip_path, event_meta, source, ts)

    def register_as_consumer(self, queue: Any) -> None:
        """把本模块注册为队列 consumer（``queue.set_consumer(self.consume)``）。

        Args:
            queue: 具有 ``set_consumer`` 方法的队列（如 ``VisionClipQueue``）。
        """
        queue.set_consumer(self.consume)
        logger.info("VideoUnderstanding: 已注册为队列 consumer")


# --------------------------------------------------------------------------- #
# 模块级辅助：关键帧抽取
# --------------------------------------------------------------------------- #
def draw_keyframe(video_path: str, timestamp_sec: float) -> Optional[str]:
    """从视频解一帧并写入临时图片（关键帧 OCR 用）。

    实现优先复用仓库可能已带有的视频解码库（cv2 / imageio / av：按序尝试）。
    **当前环境可能未安装这些库**（仓库 requirements 未列为必装），此时返回 None，
    调用方（``VideoUnderstanding``）据此跳过 OCR 并退化为节略文字，不引入大依赖。
    测试可用 mock 覆盖本函数以验证 OCR 分支。

    Args:
        video_path: 视频文件路径。
        timestamp_sec: 抽取帧的时间戳（秒）。

    Returns:
        临时图片绝对路径（JPEG/PNG），抽取失败/无解码库返回 None。
    """
    frame = None
    # 1) OpenCV
    try:
        import cv2  # type: ignore  # noqa: PLC0415（可选依赖，运行时探测）

        cap = cv2.VideoCapture(video_path)
        try:
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                idx = max(0, int(timestamp_sec * fps))
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, arr = cap.read()
                if ok and arr is not None:
                    frame = arr
        finally:
            # L4: set/read 抛异常时也必须释放解码器，防句柄泄漏
            cap.release()
    except Exception as exc:  # noqa: BLE001
        logger.debug("draw_keyframe: cv2 不可用或失败（%s）", exc)

    if frame is None:
        # 2) imageio
        try:
            import imageio.v2 as imageio  # type: ignore  # noqa: PLC0415

            reader = imageio.get_reader(video_path)
            fps = float(getattr(reader, "get_meta_data", lambda: {})().get("fps") or 30.0)
            idx = max(0, int(timestamp_sec * fps))
            try:
                frame = reader.get_data(idx)
            except (IndexError, Exception):  # noqa: BLE001 —— 尾帧越界/解码失败
                pass
            reader.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("draw_keyframe: imageio 不可用或失败（%s）", exc)

    if frame is None:
        # 3) av/PyAV
        try:
            import av  # type: ignore  # noqa: PLC0415

            container = av.open(video_path)
            try:
                stream = next(
                    (s for s in container.streams if s.type == "video"), None
                )
                if stream is not None:
                    stream.thread_type = "AUTO"
                    fps = float(stream.average_rate or 30.0)
                    # 帧序口径：目标帧序 = 时间戳秒 × fps（与上方 cv2/imageio
                    # 分支 idx = int(timestamp_sec * fps) 保持一致）。
                    # PyAV 中 pts 以 stream.time_base 为单位，换算秒需
                    # pts × time_base；旧实现 pts × fps / time_base 量纲颠倒
                    # （time_base 通常为 1/90000 量级，旧式会放大 8100 倍），
                    # 导致几乎任何 pts 都满足条件、恒取 seek 后首帧。
                    idx = max(0, int(timestamp_sec * fps))
                    container.seek(max(0, int(timestamp_sec * 1000000)))
                    for frame_av in container.decode(video=0):
                        # 帧序 = pts(时间基) × time_base(秒/时间基) × fps(帧/秒)
                        if frame_av.pts is not None and int(frame_av.pts * stream.time_base * fps) >= idx:
                            arr = frame_av.to_ndarray(format="bgr24")
                            frame = arr
                            break
            finally:
                # L4: decode 抛异常时也必须关闭容器，防句柄泄漏
                container.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("draw_keyframe: av 不可用或失败（%s）", exc)

    if frame is None:
        logger.warning(
            "draw_keyframe: 环境无 cv2/imageio/av 或解帧失败，返回 None（将跳过 OCR）。"
        )
        return None

    # 落盘临时图（可见用于 OCR）
    # L4: mktemp 已弃用且存在 TOCTOU 竞态，改 mkstemp（先关闭返回的 fd 再用路径）
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        _save_frame(tmp_path, frame)
    except Exception as exc:  # noqa: BLE001
        logger.warning("draw_keyframe: 保存临时关键帧失败（%s）", exc)
        try:
            os.unlink(tmp_path)  # mkstemp 已创建空文件，失败时清理避免残留
        except OSError:
            pass
        return None
    return tmp_path


def _save_frame(path: str, frame: Any) -> None:
    """把 numpy 帧/数组写为 PNG。优先 cv2.imwrite，回退 imageio.imwrite。"""
    try:
        import cv2  # type: ignore  # noqa: PLC0415

        cv2.imwrite(path, frame)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        import imageio.v2 as imageio  # type: ignore  # noqa: PLC0415

        imageio.imwrite(path, frame)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法写入关键帧临时图: {exc}") from exc


def _ocr_text(ocr_blocks: List[Dict[str, Any]]) -> str:
    """把 OCR 文本块列表合成为单行文字（不含 bbox）。"""
    texts = [str(b.get("text", "")).strip() for b in ocr_blocks if isinstance(b, dict)]
    texts = [t for t in texts if t]
    return "，".join(texts)


__all__ = [
    "NarrativeSummary",
    "VideoUnderstanding",
    "draw_keyframe",
]