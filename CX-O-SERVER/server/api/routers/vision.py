"""主动视觉视频片段上传路由（POST /api/vision/clip）—— 后端底座。

职责（仅底座，不含任何视频理解消费逻辑）：
    1. 前端事件触发回溯打包的片段经 multipart 上传到此口。
    2. 落**临时区**（``cxo_vision`` 子目录，不落正式目录），唯一命名并携带事件元信息。
    3. 提交到独立异步队列 ``vision_clip_queue``（不复用对话 worker，防争抢）。
    4. **立即返回** accepted（不含等待理解完成），真实理解由下游 consumer 消费。
    5. 临时文件由队列统一兜底清理（consumer 结束后的 finally），隐私红线：原始视频不落盘。

护栏：
    - ``vision_enhanced.enabled`` 为 False 时直接返回「已忽略」（200，不处理，避免无效上传）。
    - ``source`` 非法 / ``ts`` 不可解析 / ``event_type`` 为空 → 422。
    - 上传文件过大 → 413（4xx），写入临时区/队列等异常 → 5xx。

部署边界（**单进程**）：
    本模块的限流/冷却状态（``_RATE_WINDOW`` / ``_COOLDOWN_STAMP``）与入队队列
    （``vision_clip_queue``）均为**进程内内存态**，与整条视觉链路（消费者、临时文件
    清理）及整服务（会话、缓存等）的**单进程架构一致**——服务以单 worker 运行
    （``server.main:main`` / ``api_server.py`` 的 ``uvicorn.run`` 均不传 ``workers``）。
    请勿以 ``uvicorn --workers N`` 多进程启动：多进程下各 worker 持有各自的限流/
    冷却状态与队列，小时限流会被放大 N 倍、同类事件冷却失效，且上传的片段分散到
    各进程队列、互不消费。若未来确需多 worker，须为**整条视觉链路**引入进程外共享
    （如 Redis 共享限流状态 + 外部队列），而不仅是护栏状态。

路由注册：见 ``server/api/app.py`` ``include_router(vision.router, prefix="/api")``。
"""
from __future__ import annotations

import asyncio
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import time as _time
from collections import deque
from typing import Deque, Dict, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from server.config import get_settings
from server.core.logging_config import get_contextual_logger
from server.core.vision.clip_queue import vision_clip_queue
from server.api.response import APIResponse

router = APIRouter()
logger = get_contextual_logger(__name__)

#: 临时区子目录（置于系统临时目录下，随系统中途清理，不占正式存储）
VISION_TEMP_SUBDIR = "cxo_vision"
#: 单片段大小上限（字节），超标返回 413
_MAX_CLIP_BYTES = 100 * 1024 * 1024  # 100MB
#: 合法 source 枚举
_ALLOWED_SOURCES = {"camera", "screen"}

# --------------------------------------------------------------------------- #
# 后端二次护栏（Task 12.2）：小时滑窗限流 + 同类事件冷却
#   与前端 VisionEventDetector 并存（checklist）；「限流=拒绝」，「超时=理解阶段丢弃」
#   两者语义独立，本处限流/冷却发生在入队之前（未落盘即拒绝），不混淆。
#   线程/事件循环安全边界：FastAPI 路由在单事件循环内串行执行，本类内存状态在该
#   事件循环线程内访问天然串行安全；若部署多进程/多事件循环 worker，各自持有内存
#   态（不清零的已知边界），不跨进程共享——本实现定位为单进程内二次护栏。
# --------------------------------------------------------------------------- #
#: 已接受 clip 的单调时间戳队列（小时滑窗限流用）
_RATE_WINDOW: Deque[float] = deque()
#: (source, event_type) -> 最近一次接受时间戳（同类事件冷却用）
_COOLDOWN_STAMP: Dict[Tuple[str, str], float] = {}
_HOUR_SEC = 3600.0


def reset_vision_guard() -> None:
    """清空护栏内存态（供测试复位 / 运维手动清零）。"""
    _RATE_WINDOW.clear()
    _COOLDOWN_STAMP.clear()


def _prune_cooldown(now: float) -> None:
    """C8: 清理冷却表中已过期键（now - stamp 超过当前冷却窗口即删除）。

    在写入新键处顺带调用，防止长驻进程下 _COOLDOWN_STAMP 无限增长；
    冷却未启用（cooldown_sec<=0）时历史戳记全部视为过期清空。
    """
    try:
        cooldown_sec = int(
            getattr(get_settings().config.vision_enhanced, "event_cooldown_sec", 0) or 0
        )
    except Exception:
        cooldown_sec = 0
    if cooldown_sec <= 0:
        _COOLDOWN_STAMP.clear()
        return
    expired = [k for k, ts in _COOLDOWN_STAMP.items() if (now - ts) > cooldown_sec]
    for k in expired:
        _COOLDOWN_STAMP.pop(k, None)


def _guard_check(
    source: str, event_type: str, max_per_hour: int, cooldown_sec: int
) -> Tuple[bool, str]:
    """对一次待接受 clip 做频率护栏判定（副作用：通过即入窗口/写冷却）。

    Args:
        source: 片段来源（'camera' | 'screen'）。
        event_type: 触发事件类型。
        max_per_hour: 小时上限；<=0 表示不启用小时限流。
        cooldown_sec: 同类事件冷却秒数；<=0 表示不启用冷却。

    Returns:
        (True, "") 通过；否则 (False, "rate_limited" | "cooldown")。
    """
    now = _time.monotonic()

    # 1) 同类事件冷却：按 (source, event_type) 在 cooldown_sec 内禁止重复触发
    key = (source, str(event_type).strip())
    last_ts = _COOLDOWN_STAMP.get(key)
    if cooldown_sec > 0 and last_ts is not None and (now - last_ts) < cooldown_sec:
        return False, "cooldown"

    # 2) 小时滑窗限流：滑动删除超过 1 小时的旧时间戳，再检查是否已达上限
    while _RATE_WINDOW and (now - _RATE_WINDOW[0]) >= _HOUR_SEC:
        _RATE_WINDOW.popleft()
    if max_per_hour > 0 and len(_RATE_WINDOW) >= max_per_hour:
        return False, "rate_limited"

    _RATE_WINDOW.append(now)
    _COOLDOWN_STAMP[key] = now
    # C8: 写入新键时顺带清理过期键
    _prune_cooldown(now)
    return True, ""


def _vision_tmp_dir() -> Path:
    """返回临时片段存放目录（临时区），必要时创建。"""
    d = Path(tempfile.gettempdir()) / VISION_TEMP_SUBDIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 创建失败则退回到系统临时根目录，保证有可写位置
        d = Path(tempfile.gettempdir())
    return d


def _unique_clip_name(source: str, event_type: str, ts_ms: int, filename: Optional[str]) -> str:
    """生成唯一片段文件名：携带 source / 事件 / 时间戳元信息 + uuid 后缀。"""
    safe_event = re.sub(r"[^A-Za-z0-9_-]", "_", event_type)[:30] or "clip"
    base = f"{source}_{safe_event}_{ts_ms}_{uuid.uuid4().hex[:8]}"
    ext = ""
    if filename:
        ext = Path(filename).suffix.lower() or ""
        if len(ext) > 10:
            ext = ""
    return f"{base}{ext}"


def _parse_ts(ts: Any) -> Optional[float]:
    """解析时间戳为数值秒；不可解析返回 None。"""
    try:
        return float(ts)
    except (TypeError, ValueError):
        return None


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    """将 Form 字符串 "true"/"1" 等解析为 bool；None/空返回 None。"""
    if value is None or not str(value).strip():
        return None
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _map_clip_exception(exc: Exception) -> None:
    """将片段落盘/异常映射为 HTTP 异常：超时→504，其余→500。"""
    if isinstance(exc, TimeoutError):
        raise HTTPException(status_code=504, detail=str(exc))
    raise HTTPException(status_code=500, detail=f"内部错误: {exc or exc.__class__.__name__}")


@router.post("/vision/clip", response_model=APIResponse)
async def upload_vision_clip(
    clip: UploadFile = File(...),
    event_type: str = Form(...),
    ts: str = Form(...),
    source: str = Form(...),
    narrative_memory_enabled: Optional[str] = Form(None),
):
    """接收前端回溯打包的视频片段并提交独立异步队列。

    Args:
        clip: 上传的视频片段文件。
        event_type: 触发事件类型（非空）。
        ts: 事件时间戳（可解析为数值秒）。
        source: 来源，'camera' | 'screen'。
        narrative_memory_enabled: 可选，是否本片段启用叙事记忆。

    Returns:
        APIResponse: ``data={'accepted': True, 'clip_id': ...}``（立即返回）。
        当 ``vision_enhanced.enabled`` 为 False 时返回「已忽略」。

    Raises:
        HTTPException 422: source 非法 / ts 不可解析 / event_type 为空 / 文件为空
        HTTPException 413: 文件过大
        HTTPException 429: 频率护栏拒绝（``event_cooldown_sec`` 内重复同类事件 → detail='cooldown'；
            1 小时内超 ``max_clips_per_hour`` → detail='rate_limited'）
        HTTPException 500: 临时区落盘失败 / 入队异常
        HTTPException 503: 片段队列繁忙（入队被丢弃）
        HTTPException 504: 落盘超时
    """
    settings = get_settings()
    ve = settings.config.vision_enhanced
    if not ve.enabled:
        logger.info("VisionClip: vision_enhanced 未启用，忽略片段上传")
        return APIResponse.ok(
            data={"accepted": False},
            message="已忽略",
        )

    # ---- 基础校验（司 4xx）----
    if source not in _ALLOWED_SOURCES:
        raise HTTPException(status_code=422, detail=f"source 非法，仅支持 {sorted(_ALLOWED_SOURCES)}")
    parsed_ts = _parse_ts(ts)
    if parsed_ts is None:
        raise HTTPException(status_code=422, detail="ts 无法解析为数值时间戳")
    if not event_type or not str(event_type).strip():
        raise HTTPException(status_code=422, detail="event_type 不能为空")

    # ---- C4: 分块读上传（1MB 块），边读边校验总量，避免超大请求整读进内存放大 ----
    size = 0
    chunks = []
    while chunk := await clip.read(1024 * 1024):
        size += len(chunk)
        if size > _MAX_CLIP_BYTES:
            raise HTTPException(
                status_code=413, detail=f"片段过大，超过 {_MAX_CLIP_BYTES // (1024 * 1024)}MB"
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=422, detail="上传片段为空")

    # ---- 后端二次护栏（Task 12.2）：小时限流 + 同类事件冷却（入队/落盘前拒绝）----
    # C8: 状态记账移到 size/空校验之后——被 413/422 拒绝的请求不占用限流窗口
    max_per_hour = int(getattr(ve, "max_clips_per_hour", 0) or 0)
    cooldown_sec = int(getattr(ve, "event_cooldown_sec", 0) or 0)
    guard_ok, guard_reason = _guard_check(source, event_type.strip(), max_per_hour, cooldown_sec)
    if not guard_ok:
        logger.info("VisionClip: 频率护栏拒绝 clip source=%s event_type=%s reason=%s",
                    source, event_type, guard_reason)
        raise HTTPException(status_code=429, detail=guard_reason)

    # ---- 落临时区（唯一命名，携带事件信息）----
    ts_ms = int(round(parsed_ts * 1000))
    clip_id = uuid.uuid4().hex
    filename = _unique_clip_name(source, event_type, ts_ms, clip.filename)
    clip_path = _vision_tmp_dir() / f"{clip_id}_{filename}"

    try:
        # C4: 阻塞写盘经线程包裹，避免卡事件循环
        await asyncio.to_thread(clip_path.write_bytes, content)
    except Exception as exc:  # noqa: BLE001
        logger.error("VisionClip: 落临时区失败: %s", exc, exc_info=True)
        _map_clip_exception(exc)

    accepted_at = datetime.now().astimezone().isoformat()
    item: Dict[str, Any] = {
        "clip_path": str(clip_path),
        "event_meta": {
            "event_type": event_type.strip(),
            "narrative_memory_enabled": _parse_bool(narrative_memory_enabled),
            "clip_max_sec": getattr(ve, "clip_max_sec", None),
        },
        "source": source,
        "ts": parsed_ts,
        "accepted_at": accepted_at,
    }

    try:
        ok = vision_clip_queue.enqueue(item)
    except Exception as exc:  # noqa: BLE001
        logger.error("VisionClip: 入队失败: %s", exc, exc_info=True)
        # 入队失败：兜底清理已落盘临时文件，避免遗留
        try:
            clip_path.unlink(missing_ok=True)
        except OSError:
            pass
        _map_clip_exception(exc)

    if not ok:
        try:
            clip_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=503, detail="片段队列繁忙，本次片段被丢弃，请稍后重试")

    logger.info("VisionClip: 已入队 clip_id=%s path=%s source=%s", clip_id, clip_path, source)
    # E8 修复: status 类响应透出模块级 dropped 计数（snake_case 追加字段，
    # 不改变既有契约字段的形状）
    return APIResponse.ok(
        data={
            "accepted": True,
            "clip_id": clip_id,
            "pending": vision_clip_queue.pending_count(),
            # 注入的队列替身可能未实现计数器，缺失时按 0 透出
            "dropped": getattr(vision_clip_queue, "dropped_count", 0),
        },
        message="已接受，排队处理中",
    )