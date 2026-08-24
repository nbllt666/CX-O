"""Vision enhanced 接口契约存根（种子阶段，待 s0201 补全）。

源真理: 后端视觉增强视频叙事记忆功能（vision_enhanced 配置段）
完成 Skill: s0201
当前状态: 种子——仅含 POST /api/vision/clip 代表性端点与核心类型
"""

from typing import Literal, Optional, Union

from pydantic import BaseModel


class VisionEventMeta(BaseModel):
    """视觉事件元信息：事件类型、时间戳与来源。"""
    event_type: Literal[
        'scene_change', 'user_action', 'emotion_shift', 'focus_mode',
        'user_idle', 'user_left', 'user_returned', 'sleep_detected'
    ]  # 唯一事件类型，见事件枚举
    ts: Union[int, float]  # 事件时间戳（秒或毫秒，取决于来源对齐口径）
    source: Literal['camera', 'screen']  # 事件来源：camera=摄像头画面，screen=屏幕捕捉


class VideoClip(BaseModel):
    """视频片段：围绕事件前后滚动缓冲捕获的原始段元信息。"""
    source: Literal['camera', 'screen']  # 片段来源
    start_ts: float  # 片段起始时间戳
    end_ts: float  # 片段结束时间戳
    pre_roll_sec: float  # 事件前预滚动缓冲秒数
    post_roll_sec: float  # 事件后滚动缓冲秒数
    keyframe_paths: Optional[list[str]] = None  # 关键帧/OCR 提取的帧文件路径列表


class NarrativeSummary(BaseModel):
    """叙事记忆摘要：生成的视频叙事文本与事件/动作/情绪标签。"""
    content: str  # 叙事文本正文
    events: list[str]  # 识别出的事件标签
    actions: list[str]  # 识别出的用户动作
    emotion: str  # 主要情绪
    clip_ts: Union[int, float]  # 片段时间戳
    source: Literal['camera', 'screen']  # 片段来源
    event_type: str  # 触发该片段的事件类型


class VisionClipRequest(BaseModel):
    """POST /api/vision/clip 请求体。"""
    event: VisionEventMeta  # 触发事件元信息
    clip: Optional[VideoClip] = None  # 视频片段元信息（外部传入事件时可省略）
    narrative_memory_enabled: bool = True  # 是否启用叙事记忆回写
    ocr_keyframe_enabled: bool = True  # 是否对关键帧做 OCR
    temporal_fusion_enabled: bool = False  # 是否启用跨时段时间融合
    require_vllm: bool = True  # 是否要求 vLLM 后端（false 时可用于降级/调试）


class VisionClipResponse(BaseModel):
    """POST /api/vision/clip 响应体。"""
    clip_id: str  # 生成的片段 ID
    narrative: Optional[NarrativeSummary] = None  # 叙事摘要（narrative_memory_enabled=true 时存在）
    ok: bool = True


async def create_vision_clip(request: VisionClipRequest) -> VisionClipResponse:
    """POST /api/vision/clip — 创建视频叙事记忆片段。

    异常声明与实现端（server/api/routers/vision.py::upload_vision_clip）对齐
    （2026-08-24，GN-004 阻断项 12.4 / O2 契约对齐）。注：实现端以 multipart
    Form 接收 clip 文件 + event_type/ts/source，非法值由差异化校验返回 422。

    Raises:
        HTTPException: 422 参数错误（source 非法 / ts 不可解析 / event_type 为空 / 文件为空）
        HTTPException: 413 文件过大（超单片段上限，默认 100MB）
        HTTPException: 429 频率护栏拒绝（event_cooldown_sec 内重复同类事件
            -> detail='cooldown'；1 小时内超 max_clips_per_hour -> detail='rate_limited'）
        HTTPException: 500 临时区落盘失败 / 入队异常
        HTTPException: 503 片段队列繁忙（入队被丢弃，请稍后重试）
        HTTPException: 504 落盘超时
    """
    ...


# TODO s0201: 补全 vision_enhanced 全部端点（clip 查询/删除/批量等）+ 完整异常说明