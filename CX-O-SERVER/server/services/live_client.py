"""
Live 客户端处理器
处理直播弹幕等实时消息
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
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


# fire-and-forget 反馈任务强引用集（仿 vad_processor._track_background_task）：
# 裸 create_task 的任务在完成前若失去所有引用，可能被 GC 提前回收而静默中断。
_feedback_tasks: set = set()


# --------------------------------------------------------------------------- #
# W5: live 会话 AI 回复链路（stream/response）与字幕播报同步（tts_sync/tick/end）
# --------------------------------------------------------------------------- #
# live 文本回复使用默认 agent（live 连接无 agent_id 概念，对齐 chat 处理器回退口径）
_LIVE_REPLY_AGENT_ID = "default"
# live 回复 token 上限：直播互动场景控制单轮生成时长（防御性，低于常规聊天默认值）
_LIVE_REPLY_MAX_TOKENS_CAP = 512
# 字幕播报近似参数：live 路径无真实 TTS 播放与音频下行通道（前端 useLiveWebSocket
# 忽略二进制帧），无真实时长源，按中文 TTS 常速（约 5 字/秒）估算；tick 为进度心跳间隔。
_LIVE_TTS_MS_PER_CHAR = 200
_LIVE_TTS_MIN_DURATION_MS = 800
_LIVE_TTS_TICK_INTERVAL = 0.2

# fire-and-forget 回复任务强引用集（仿 _feedback_tasks，防 GC 提前回收）
_reply_tasks: set = set()

# 回复分句正则：按句末标点（含换行）零宽切分，标点保留在前句
_REPLY_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")


def _split_reply_sentences(text: str) -> list:
    """把回复文本按句切分（保留标点），用于逐句字幕播报同步。"""
    parts = [p.strip() for p in _REPLY_SENTENCE_SPLIT_RE.split(text or "") if p.strip()]
    if not parts and text and text.strip():
        parts = [text.strip()]
    return parts


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
        # W5: 在途回复生成任务引用（in-flight 守卫 + 强引用跟踪）
        self._reply_task: Optional["asyncio.Task"] = None

    async def handle_message(self, websocket, message: dict, client_id: str):
        msg_type = message.get("type")

        try:
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
        except Exception as e:
            # E1 修复：8 种消息分派异常不再向上穿透断连 /ws/live——留痕后向
            # 该连接回发 error 帧（与 manager type 路由 error 回发格式一致），
            # 连接保持存活，由调用方收帧循环继续。
            logger.warning(
                f"Live message handling failed type={msg_type} client={client_id}: {e}"
            )
            try:
                await self.manager.send_message(
                    self.client_id,
                    {"type": "error", "error": f"处理消息失败: {str(e)}"},
                )
            except Exception as send_err:
                logger.debug(f"live error 帧回发失败 client={self.client_id}: {send_err}")

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

        # H1 注入校正：live 路径的真实会话 id（init 消息可自定义，缺省为 client_id）
        # 注入打断模块，保证 final 判定写回上下文落在正确 session。
        _asr_interrupt = get_asr_interrupt_module(self.client_id)
        _asr_interrupt.set_session_id(self._session_id)
        _agent_interrupt = get_agent_interrupt_module(self.client_id)
        _agent_interrupt.set_session_id(self._session_id)

        logger.info(f"Live client initialized: {self.client_id}, config: {data}")

        await self.manager.send_message(self.client_id, {
            "type": "init_ack",
            "data": {"status": "ok", "session_id": self._session_id}
        })

    async def _handle_danmaku(self, websocket, message: dict):
        # E1 修复：data:null / user 非字典时安全降级为空值，防 AttributeError
        # 断连 /ws/live（此前 data 为 None 时 data.get 直接崩溃）。
        data = message.get("data", {})
        if not isinstance(data, dict):
            logger.warning(f"弹幕 data 非字典，已降级为空对象: {type(data).__name__}")
            data = {}
        user = data.get("user", {})
        if not isinstance(user, dict):
            logger.warning(f"弹幕 user 非字典，已降级为空对象: {type(user).__name__}")
            user = {}
        content = data.get("content", "")
        user_id = user.get("uid", "")
        username = user.get("username", "")

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
        任务引用保存进模块级集合（仿 vad_processor._track_background_task），
        防止裸 create_task 无强引用被 GC 提前回收。
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

        def _on_feedback_done(done_task: "asyncio.Task") -> None:
            _feedback_tasks.discard(done_task)
            _release_danmaku_slot()

        _feedback_tasks.add(task)
        task.add_done_callback(_on_feedback_done)

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

        # W5: 礼物事件回显广播给 live 频道全部连接（对齐 danmaku :212 广播口径）。
        # 平台适配层（danmaku_connector）无 gift 事件源，此处以 C→S 入站事件为源
        # 回显广播；单用户场景下发送方自身的前端 onGift 亦被触发，界面可工作。
        await self._safe_channel_send({"type": "gift", "data": data})

    async def _handle_enter(self, websocket, message: dict):
        data = message.get("data", {})
        # 每进入事件触发；实录弹幕流下高频，降级 DEBUG 并惰性格式化避免热路径 eager f-string
        logger.debug("User entered: %s", data)

        await self.manager.send_message(self.client_id, {
            "type": "enter_ack",
            "data": {"status": "ok"}
        })

        # W5: 进入事件回显广播给 live 频道全部连接（对齐 danmaku :212 广播口径；
        # 平台适配层无 enter 事件源，以 C→S 入站事件为源回显广播）
        await self._safe_channel_send({"type": "enter", "data": data})

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

        # W5: 补出直播回复链路（C→S text → LLM → stream/response 下发）。
        # fire-and-forget 不阻塞连接消息循环；text_ack 已先行返回，生成失败仅日志。
        self._schedule_reply(text)

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

    # ------------------------------------------------------------------ #
    # W5: live 回复链路（stream/response）与字幕播报同步（tts_sync/tick/end）
    # ------------------------------------------------------------------ #
    async def _safe_channel_send(self, message: dict) -> bool:
        """向 live 频道广播消息；失败仅日志不阻断直播主流程，返回是否成功。"""
        try:
            await self.manager.broadcast_to_channel("live", message)
            return True
        except Exception as e:
            logger.warning(f"live 频道广播失败（type={message.get('type')}）: {e}")
            return False

    def _schedule_reply(self, text: str) -> None:
        """调度一轮 AI 回复生成（fire-and-forget，含强引用跟踪与在途守卫）。

        在途守卫：上一轮回复未完成时丢弃本轮生成（对齐弹幕反馈的丢弃式限流），
        避免直播弹幕流下 LLM 生成任务无限堆积。
        """
        if not (text and text.strip()):
            return
        if self._reply_task is not None and not self._reply_task.done():
            logger.debug("live 回复生成进行中，丢弃本轮 text 生成请求")
            return
        self._reply_task = asyncio.create_task(self._reply_pipeline(text))
        _reply_tasks.add(self._reply_task)
        self._reply_task.add_done_callback(_reply_tasks.discard)

    async def _reply_pipeline(self, text: str) -> None:
        """W5: live 会话 AI 回复链路——LLM 流式生成 → stream 逐块/response 终稿
        下发 → 上下文回写 → 隐式反馈记录 → 字幕播报同步。

        装配对齐 server/handlers/chat.py 主聊天链路同型（agent 配置 →
        build_messages → stream_chat），经 record_ai_response 打通既有
        「增量接入点」（此前无调用方）；整个管线异常均吞掉，不阻断直播主流程。
        """
        full = ""
        try:
            from server.chat_helpers import get_agent_config_async, get_llm_client_for_agent
            from server.prompt_builder import build_messages

            agent_config = await get_agent_config_async(_LIVE_REPLY_AGENT_ID)
            if not agent_config:
                logger.warning("live 回复生成跳过：默认 agent 不可用（%s）", _LIVE_REPLY_AGENT_ID)
                return
            llm = get_llm_client_for_agent(agent_config)
            session_id = self._session_id or self.client_id
            messages = build_messages(agent_config, self.context_manager, session_id, text)
            try:
                max_tokens = int(agent_config.get("max_tokens", _LIVE_REPLY_MAX_TOKENS_CAP))
            except (TypeError, ValueError):
                max_tokens = _LIVE_REPLY_MAX_TOKENS_CAP
            max_tokens = max(1, min(max_tokens, _LIVE_REPLY_MAX_TOKENS_CAP))

            async for chunk in llm.stream_chat(
                messages=messages,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=max_tokens,
            ):
                content = ""
                if isinstance(chunk, dict):
                    if chunk.get("type") == "content":
                        content = chunk.get("content", "")
                elif isinstance(chunk, str):
                    content = chunk
                if not content:
                    continue
                full += content
                await self._safe_channel_send({"type": "stream", "data": {"content": content}})

            if full.strip():
                await self._safe_channel_send({"type": "response", "data": {"content": full}})
                if self._session_id:
                    self.context_manager.add_message(self._session_id, {
                        "role": "assistant", "content": full
                    })
                try:
                    self.record_ai_response(full, prompt=text)
                except Exception as e:
                    logger.warning(f"live_feedback 回复记录降级: {e}")
                await self._announce_reply_subtitles(full)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"live 回复生成失败（text_ack 已回，不影响直播主流程）: {e}")

    async def _announce_reply_subtitles(self, text: str) -> None:
        """W5: 回复字幕播报同步——按句串行广播 tts_sync / tts_tick / tts_end。

        live 路径无真实 TTS 播放与音频下行通道，本方法仅广播字幕同步信号
        （设计参照 git fa2be0f 版被删除的 LiveTTSSyncBroadcaster，字段契约
        playback_id/server_ts/text/duration/position 与前端 useLiveWebSocket
        一致）；时长按常速近似估算（_LIVE_TTS_MS_PER_CHAR）。广播通道失效
        （房间空/已断连）时停止播报推进。
        """
        for sentence in _split_reply_sentences(text):
            duration_ms = max(
                _LIVE_TTS_MIN_DURATION_MS, len(sentence) * _LIVE_TTS_MS_PER_CHAR
            )
            playback_id = uuid.uuid4().hex[:12]
            if not await self._safe_channel_send({"type": "tts_sync", "data": {
                "playback_id": playback_id,
                "server_ts": int(time.time() * 1000),
                "text": sentence,
                "duration": duration_ms,
            }}):
                return
            start = time.monotonic()
            while True:
                await asyncio.sleep(_LIVE_TTS_TICK_INTERVAL)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                if elapsed_ms >= duration_ms:
                    break
                await self._safe_channel_send({"type": "tts_tick", "data": {
                    "playback_id": playback_id,
                    "server_ts": int(time.time() * 1000),
                    "position": min(elapsed_ms, duration_ms),
                }})
            await self._safe_channel_send({"type": "tts_end", "data": {
                "playback_id": playback_id,
                "server_ts": int(time.time() * 1000),
            }})
