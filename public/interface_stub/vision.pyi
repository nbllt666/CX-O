"""Vision enhanced 接口契约存根（种子阶段，待 s0201 补全）。

源真理: 后端视觉增强视频叙事记忆功能（vision_enhanced 配置段）
完成 Skill: s0201
当前状态: 种子——仅含 POST /api/vision/clip 代表性端点与核心类型
@version 1.0.1  # PATCH：追加帧过滤三态契约 FrameFilterDecision/FilterFrameRequest/FilterFrameResponse（spec add-vlm-frame-filter-face-match，纯新增声明，未动既有内容）；1.0.0 种子
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


# ---- 帧过滤三态契约（spec add-vlm-frame-filter-face-match，POST /api/vision/frame）----
# 三态语义：forward=有价值，转发给主 LLM；summarize=中等价值，仅生成摘要沉淀；
# discard=无价值，直接筛除。filter_fail_mode=passthrough 降级时 action 恒为 forward。
class FrameFilterDecision(BaseModel):
    """帧过滤判定结果：小 VLM 对单帧的三态判定（frame_filter_enabled=true 时产出）。"""
    action: Literal['forward', 'summarize', 'discard']  # 三态判定：forward 转发主 LLM / summarize 仅摘要沉淀 / discard 筛除
    summary: str  # 帧内容一句话摘要（三态均产出，discard 时为筛除依据的简述）
    reason: str  # 判定理由（供审计与调试回溯）
    importance: Literal['low', 'medium', 'high']  # 帧重要程度三档
    degraded: bool  # 是否降级产出（VLM 超时/JSON 解析失败时按 filter_fail_mode 兜底；true 时 action 恒为 forward，对应 passthrough 语义）


class FilterFrameRequest(BaseModel):
    """POST /api/vision/frame 请求体：单帧图像 + 会话归属信息。"""
    image: str  # 帧图像（dataURL 或纯 base64 编码的 JPEG/PNG，20MB 上限）
    agent_id: str  # 会话归属 Agent ID（用于取 ContextManager 最近 N 条上下文与档案归属）
    source: Literal['camera', 'screen']  # 帧来源：camera=摄像头画面，screen=屏幕捕捉
    ts: Optional[Union[int, float]] = None  # 帧时间戳（秒或毫秒，缺省由服务端补齐）


class FilterFrameResponse(BaseModel):
    """POST /api/vision/frame 响应体：三态判定 + 面部标签 + 过滤器生效标记。"""
    action: Literal['forward', 'summarize', 'discard']  # 三态判定结果（frame_filter_enabled=false 时恒为 forward）
    summary: Optional[str] = None  # 帧摘要（filter_active=true 时存在）
    reason: Optional[str] = None  # 判定理由（filter_active=true 时存在）
    importance: Optional[Literal['low', 'medium', 'high']] = None  # 重要程度（filter_active=true 时存在）
    degraded: Optional[bool] = None  # 是否降级产出（filter_active=true 时存在）
    face_labels: Optional[list[str]] = None  # 命中的人脸档案名列表（camera 源且 face_match.enabled 时存在，无人脸/未启用为 None）
    filter_active: bool  # 帧过滤器是否实际生效（frame_filter_enabled=false 时为 false，响应仅含 action=forward + filter_active）