"""
Live 客户端处理器
处理直播弹幕等实时消息
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, TYPE_CHECKING

from server.services.marker_adapter import MarkerAdapter
from server.services.context_manager import get_context_manager
from server.services.firewall import get_firewall_service
from server.services.frontend_marker import get_frontend_marker
from server.services.live_feedback import LiveFeedbackTracker, get_live_feedback_tracker
from server.services.vad_processor import ensure_stream_processor_configured
from server.services.asr_interrupt import get_asr_interrupt_module
from server.services.agent_interrupt_user import get_agent_interrupt_module
from server.services.voice_context import reset_active_client_id, set_active_client_id

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 弹幕反馈 fire-and-forget 信号量（无界 create_task 限流）
# 超限时非阻塞丢弃，防止实录弹幕流下任务无限堆积；按事件循环缓存避免跨 loop 错环。
# --------------------------------------------------------------------------- #
_danmaku_sem: Optional[asyncio.Semaphore] = None
_danmaku_sem_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_danmaku_sem() -> asyncio.Semaphore:
    """获取模块级弹幕反馈并发信号量（可配置大小）。"""
    global _danmaku_sem, _danmaku_sem_loop
    loop = asyncio.get_running_loop()
    if _danmaku_sem is None or _danmaku_sem_loop is not loop:
        from server.config import get_config

        size = max(1, get_config().executor.danmaku_concurrency)
        _danmaku_sem = asyncio.Semaphore(size)
        _danmaku_sem_loop = loop
    return _danmaku_sem


async def _acquire_danmaku_slot() -> bool:
    """非阻塞申请一个弹幕反馈并发槽；已满返回 False（本次丢弃，防任务无限堆积）。"""
    sem = _get_danmaku_sem()
    if sem.locked():  # 已满直接丢弃，不排队
        return False
    await sem.acquire()
    return True


def _release_danmaku_slot() -> None:
    """归还弹幕反馈并发槽（须在事件循环线程内调用）。"""
    _get_danmaku_sem().release()


class LiveClientHandler:
    """直播客户端处理器——处理直播弹幕、礼物、进入等实时消息与音频流。"""

    def __init__(self, manager: "WebSocketManager", client_id: str, client_config: dict):
        self.manager = manager
        self.client_id = client_id
        self.client_config = client_config
        self.marker_adapter = MarkerAdapter()
        self.context_manager = get_context_manager()
        self.firewall = get_firewall_service()
        self.frontend_marker = get_frontend_marker()
        self.feedback_tracker: LiveFeedbackTracker = get_live_feedback_tracker()
        self._session_id: Optional[str] = None

    async def handle_message(self, websocket, message: dict, client_id: str):
        msg_type = message.get("type")

        if msg_type == "init":
            await self._handle_init(websocket, message)
        elif msg_type == "danmaku":
            await self._handle_danmaku(websocket, message)
        elif msg_type == "gift":
            await self._handle_gift(websocket, message)
        elif msg_type == "enter":
            await self._handle_enter(websocket, message)
        elif msg_type == "config":
            await self._handle_config(websocket, message)
        elif msg_type == "text":
            await self._handle_text(websocket, message)
        elif msg_type == "interrupt":
            await self._handle_interrupt(websocket, message)
        elif msg_type == "stop_tts":
            await self._handle_stop_tts(websocket, message)
        else:
            logger.warning(f"Unknown live message type: {msg_type}")

    async def handle_audio(self, websocket, audio_data: bytes, client_id: str):
        # 注入当前语音会话 client_id 到 contextvars（工具执行读取）
        token = set_active_client_id(self.client_id)
        try:
            # per-client 并发化：按 client_id 取独立处理器实例（会话间 VAD/ASR 不串扰）
            stream_processor = ensure_stream_processor_configured(self.client_id)
            result = await stream_processor.process_audio_chunk(audio_data)

            vad_result = result.get("vad", {})
            asr_result = result.get("asr")

            if vad_result.get("state_changed"):
                status = "speech_start" if vad_result["is_speaking"] else "speech_end"
                await self.manager.send_message(self.client_id, {
                    "type": "vad_status",
                    "data": {
                        "status": status,
                        "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                    }
                })

            if asr_result:
                text = asr_result.get("text", "")
                if text:
                    # 声纹说话人（仅注册命中带名；未注册 spk_N 伪名不外发）
                    _spk_name = asr_result.get("speaker_name") or (asr_result.get("speaker_id") if asr_result.get("speaker_registered") else "")
                    _payload = {
                        "text": text,
                        "is_final": not vad_result.get("is_speaking", False),
                    }
                    if _spk_name:
                        _payload["speaker_id"] = _spk_name
                        _payload["speaker_name"] = _spk_name
                    await self.manager.send_message(self.client_id, {
                        "type": "asr_result",
                        "data": _payload
                    })

                    # per-client 并发化：使用当前 client 打断模块（TTS 播放状态隔离）
                    interrupt_module = get_asr_interrupt_module(self.client_id)
                    if interrupt_module.enabled and interrupt_module._tts_playing:
                        decision, should_interrupt = await interrupt_module.on_asr_result(
                            text, is_final=not vad_result.get("is_speaking", False)
                        )
                        if should_interrupt:
                            await self.manager.send_message(self.client_id, {
                                "type": "interrupt",
                                "data": {
                                    "source": "asr",
                                    "text": text,
                                    "decision": decision
                                }
                            })

            await self.manager.send_message(self.client_id, {
                "type": "vad_frame",
                "data": {
                    "is_speaking": vad_result.get("is_speaking", False),
                    "speech_probability": vad_result.get("speech_probability", 0),
                    "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                }
            })

        except Exception as e:
            logger.error(f"Live audio processing error: {e}")
        finally:
            # 复位 contextvars，避免异常路径下 client_id 残留串扰
            reset_active_client_id(token)

    async def _handle_init(self, websocket, message: dict):
        data = message.get("data", {})
        self.client_config.update(data)
        self._session_id = data.get("session_id", self.client_id)

        logger.info(f"Live client initialized: {self.client_id}, config: {data}")

        await self.manager.send_message(self.client_id, {
            "type": "init_ack",
            "data": {"status": "ok", "session_id": self._session_id}
        })

    async def _handle_danmaku(self, websocket, message: dict):
        data = message.get("data", {})
        content = data.get("content", "")
        user_id = data.get("user", {}).get("uid", "")
        username = data.get("user", {}).get("username", "")

        filter_result = self.firewall.filter_message(content, user_id, username)
        if not filter_result.allowed:
            logger.debug("Danmaku filtered: %s", filter_result.reason)
            return
        # 弹幕反馈：过滤放行后喂给隐式反馈追踪器（fire-and-forget，不阻断主路径）
        await self._safe_feedback_danmaku(content, user_id)

        if self._session_id:
            self.context_manager.add_danmaku_message(self._session_id, data)

        marker_data = self.marker_adapter.process_danmaku(data)
        frontend_data = self.frontend_marker.format_for_frontend(marker_data)

        # 弹幕回显改为全房间广播：观众消息投递到 live 频道，所有订阅者（观众）彼此可见弹幕
        await self.manager.broadcast_to_channel(
            "live", {"type": "danmaku", "data": frontend_data}
        )

        # 弹幕转发互动房间：装配了互动协调器且房间开启观众席时，弹幕进入回应引擎
        await self._forward_danmaku_to_meeting(content, user_id, username)

    async def _forward_danmaku_to_meeting(self, content: str, user_id: str, username: str) -> None:
        """把弹幕投递给互动协调器（process_audience_message）。

        通过模块级 get_meeting_coordinator 读取已装配协调器（延迟导入避免循环依赖）；
        房间未开启观众席 / 无活跃房间时由协调器静默返回 None，此处 try/except 兜底。
        """
        try:
            from server.api.routers.meeting import get_meeting_coordinator

            coord = get_meeting_coordinator()
            if coord is not None:
                await coord.process_audience_message(content, userid=user_id, username=username)
        except Exception as e:  # 互动房间未装配/异常时静默跳过，不影响弹幕主路径
            logger.debug("弹幕转发互动房间跳过: %s", e)

    async def _safe_feedback_danmaku(self, content: str, user_id: str) -> None:
        """将过滤放行后的弹幕喂给隐式反馈追踪器（fire-and-forget，静默降级）。

        后台任务独立调度，不阻塞 danmaku 主路径；非阻塞申请并发槽，
        已满则丢弃本次反馈，防任务无限堆积；追踪器内部异常被吞掉。
        """
        if not await _acquire_danmaku_slot():
            logger.debug("live_feedback 弹幕反馈并发已满，丢弃本次反馈")
            return
        try:
            task = asyncio.create_task(
                self.feedback_tracker.on_danmaku(
                    text=content,
                    user_id=user_id,
                    session_id=self._session_id or "",
                )
            )
        except Exception as e:  # 调度失败静默降级并归还并发槽
            _release_danmaku_slot()
            logger.warning(f"live_feedback 弹幕反馈调度降级: {e}")
            return
        task.add_done_callback(lambda _t: _release_danmaku_slot())

    def record_ai_response(self, text: str, prompt: str = "", ts: Optional[float] = None) -> None:
        """记录一轮 AI 回复，供后续弹幕窗口判定隐性反馈（增量接入点）。"""
        import time as _time

        self.feedback_tracker.record_ai_response(text, ts=ts if ts is not None else _time.time(), prompt=prompt)

    async def _handle_gift(self, websocket, message: dict):
        data = message.get("data", {})
        # 每礼物事件触发；实录弹幕流下高频，降级 DEBUG 并惰性格式化避免热路径 eager f-string
        logger.debug("Gift received: %s", data)

        if self._session_id:
            self.context_manager.add_message(self._session_id, {
                "role": "gift",
                "content": json.dumps(data, ensure_ascii=False)
            })

        await self.manager.send_message(self.client_id, {
            "type": "gift_ack",
            "data": {"status": "ok"}
        })

    async def _handle_enter(self, websocket, message: dict):
        data = message.get("data", {})
        # 每进入事件触发；实录弹幕流下高频，降级 DEBUG 并惰性格式化避免热路径 eager f-string
        logger.debug("User entered: %s", data)

        await self.manager.send_message(self.client_id, {
            "type": "enter_ack",
            "data": {"status": "ok"}
        })

    async def _handle_config(self, websocket, message: dict):
        data = message.get("data", {})
        logger.info(f"Config update: {data}")

        if "firewall" in data:
            self.firewall.set_config(data["firewall"])

        if "interrupt" in data:
            interrupt_module = get_asr_interrupt_module(self.client_id)
            interrupt_module.set_config(data)

        if "agent_interrupt" in data:
            agent_interrupt = get_agent_interrupt_module(self.client_id)
            agent_interrupt.set_config(data)

        await self.manager.send_message(self.client_id, {
            "type": "config_ack",
            "data": {"status": "ok"}
        })

    async def _handle_text(self, websocket, message: dict):
        data = message.get("data", {})
        text = data.get("text", "")

        if self._session_id:
            self.context_manager.add_message(self._session_id, {
                "role": "user",
                "content": text
            })

        await self.manager.send_message(self.client_id, {
            "type": "text_ack",
            "data": {"status": "ok"}
        })

    async def _handle_interrupt(self, websocket, message: dict):
        data = message.get("data", {})
        source = data.get("source", "user")
        logger.info(f"Interrupt request from {source}")

        interrupt_module = get_asr_interrupt_module(self.client_id)
        interrupt_module.reset_interrupt()

        await self.manager.send_message(self.client_id, {
            "type": "interrupt_ack",
            "data": {"status": "ok"}
        })

    async def _handle_stop_tts(self, websocket, message: dict):
        logger.info(f"Stop TTS request from {self.client_id}")

        from server.handlers.audio import set_tts_playing
        await set_tts_playing(self.client_id, False)

        await self.manager.send_message(self.client_id, {
            "type": "stop_tts_ack",
            "data": {"status": "ok"}
        })
