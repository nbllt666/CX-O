"""
Live 客户端处理器
处理直播弹幕等实时消息
"""
from __future__ import annotations

import json
import logging
from typing import Optional, TYPE_CHECKING

from server.services.marker_adapter import MarkerAdapter
from server.services.context_manager import get_context_manager
from server.services.firewall import get_firewall_service
from server.services.frontend_marker import get_frontend_marker
from server.services.vad_processor import get_audio_stream_processor
from server.services.asr_interrupt import get_asr_interrupt_module
from server.services.agent_interrupt_user import get_agent_interrupt_module

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


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
        try:
            stream_processor = get_audio_stream_processor()
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
                    await self.manager.send_message(self.client_id, {
                        "type": "asr_result",
                        "data": {
                            "text": text,
                            "is_final": not vad_result.get("is_speaking", False)
                        }
                    })

                    interrupt_module = get_asr_interrupt_module()
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

        if self._session_id:
            self.context_manager.add_danmaku_message(self._session_id, data)

        marker_data = self.marker_adapter.process_danmaku(data)
        frontend_data = self.frontend_marker.format_for_frontend(marker_data)

        await self.manager.send_message(self.client_id, {
            "type": "danmaku",
            "data": frontend_data
        })

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
            interrupt_module = get_asr_interrupt_module()
            interrupt_module.set_config(data)

        if "agent_interrupt" in data:
            agent_interrupt = get_agent_interrupt_module()
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

        interrupt_module = get_asr_interrupt_module()
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
