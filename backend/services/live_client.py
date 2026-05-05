"""
直播客户端处理器
处理 /ws/live 端点的客户端连接
支持伪全双工：TTS播放时可接收音频并打断
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class LiveClientHandler:
    def __init__(self, manager, client_id: str, client_config: dict):
        self.manager = manager
        self.client_id = client_id
        self.client_config = client_config
        self._audio_buffer = []
        self._marker_prompt = ""
        self._session_id = ""
        self._is_tts_playing = False
        self._current_tts_request_id: Optional[str] = None
        self._audio_stream_processor: Optional[Any] = None
        self._interrupt_manager: Optional[Any] = None
        self._initialized = False
        self._cxhms_client: Optional[Any] = None
    
    def _get_cxhms_client(self):
        """获取 CXHMS 客户端"""
        if self._cxhms_client is None:
            try:
                from .cxhms_client import CXHMSClient
                from config.settings import settings
                cxhms_url = getattr(settings.config, 'cxhms_url', 'ws://localhost:8100/ws')
                self._cxhms_client = CXHMSClient(url=cxhms_url)
            except Exception as e:
                logger.warning(f"Failed to create CXHMS client: {e}")
        return self._cxhms_client
    
    def set_cxhms_client(self, client):
        """设置 CXHMS 客户端"""
        self._cxhms_client = client
        
    async def handle_message(self, websocket: WebSocket, message: dict, client_id: str):
        """处理客户端消息"""
        msg_type = message.get("type")
        
        if msg_type == "connect":
            await self._handle_connect(websocket, message.get("data", {}))
        elif msg_type == "danmaku":
            await self._handle_danmaku(message.get("data", {}))
        elif msg_type == "audio_frame":
            pass
        elif msg_type == "tts_start":
            await self._handle_tts_start(message.get("data", {}))
        elif msg_type == "tts_end":
            await self._handle_tts_end()
        elif msg_type == "audio_stream":
            await self._handle_audio_stream(websocket, message.get("data", {}))
        else:
            logger.warning(f"Unknown message type: {msg_type}")
    
    async def _handle_connect(self, websocket: WebSocket, data: dict):
        """处理连接信息"""
        self.client_config["client_type"] = data.get("client_type", "web")
        self.client_config["room_id"] = data.get("room_id")
        self.client_config["supported_markers"] = data.get("supported_markers", [])
        self.client_config["marker_config"] = data.get("marker_config", {})
        
        self._session_id = f"live_{self.client_id}"
        
        from .marker_adapter import MarkerAdapter
        adapter = MarkerAdapter.get_instance()
        adapter.set_client_config(
            self.client_id,
            self.client_config.get("supported_markers", []),
            self.client_config.get("marker_config", {})
        )
        
        is_duplex = self.client_config.get("duplex_mode", True)
        self._marker_prompt = adapter.generate_marker_prompt(
            self.client_config.get("supported_markers", []),
            self.client_config.get("marker_config", {}),
            include_interrupt_rules=is_duplex
        )
        
        from .context_manager import get_context_manager
        ctx_mgr = get_context_manager()
        ctx_mgr.set_system_prompt(self._session_id, self._marker_prompt)
        
        await websocket.send_json({
            "type": "ack",
            "client_id": self.client_id,
            "status": "connected"
        })
        
        logger.info(f"Live client connected: {self.client_id}, type: {self.client_config['client_type']}, marker_prompt: {len(self._marker_prompt)} chars")
        
        self._init_interrupt_modules()
    
    async def _handle_danmaku(self, data: dict):
        """处理弹幕消息"""
        # 转发到防火墙处理
        from .firewall import FirewallService
        firewall = FirewallService.get_instance()
        
        result = await firewall.decide_danmaku(data)
        
        # 发送处理结果
        await self.manager.send_message(self.client_id, {
            "type": "danmaku_result",
            "data": {
                "original_content": data.get("content", ""),
                "decision": result.get("decision", "passive"),
                "added_to_context": result.get("added_to_context", False),
                "reply_triggered": result.get("reply_triggered", False),
                "user": {
                    "uid": data.get("user", {}).get("uid"),
                    "username": data.get("user", {}).get("username")
                }
            }
        })
        
        # 如果需要回复，触发 CXHMS
        if result.get("reply_triggered"):
            await self._trigger_cxhms_reply(data, result)
    
    async def _trigger_cxhms_reply(self, danmaku_data: dict, decision_result: dict):
        """触发 CXHMS 生成回复"""
        from .context_manager import get_context_manager
        from .frontend_marker import FrontendMarkerParser
        from .cxhms_client import CXHMSClient
        
        # 将弹幕加入上下文
        user = danmaku_data.get("user", {})
        context_message = {
            "role": f"直播间消息 userid:{user.get('uid', '')} username:{user.get('username', '')}",
            "content": danmaku_data.get("content", "")
        }
        
        # 添加到上下文管理器
        ctx_mgr = get_context_manager()
        session_id = f"live_{self.client_id}"
        ctx_mgr.add_message(
            session_id,
            role=context_message.get("role", "user"),
            content=context_message.get("content", "")
        )
        
        messages = ctx_mgr.get_context_with_system_prompt(session_id)
        
        # 调用 CXHMS 生成回复
        try:
            cxhms = self._get_cxhms_client()
            
            if cxhms:
                # 使用流式接口生成回复
                full_response = []
                
                async def handle_stream_response(response: dict):
                    if response.get("type") == "text" or response.get("content"):
                        text = response.get("content", response.get("text", ""))
                        if text:
                            full_response.append(text)
                            
                            # 解析前端标记
                            segments = FrontendMarkerParser.split_for_tts(text)
                            for segment in segments:
                                # 发送文本
                                await self.manager.send_message(self.client_id, {
                                    "type": "text",
                                    "data": {
                                        "content": segment.get("text", ""),
                                        "chunk_index": len(full_response) - 1,
                                        "is_final": response.get("is_final", False)
                                    }
                                })
                                
                                # 如果有标记，在 TTS 播放完成后发送
                                if segment.get("marker"):
                                    marker = segment["marker"]
                                    await self.manager.send_message(self.client_id, {
                                        "type": "frontend_marker",
                                        "data": {
                                            "marker_type": marker.get("marker_type"),
                                            "marker_content": {
                                                "action": marker.get("action"),
                                                "duration": marker.get("params", {}).get("duration"),
                                                "params": marker.get("params", {})
                                            },
                                            "split_index": len(full_response) - 1
                                        }
                                    })
                    
                    elif response.get("type") == "error":
                        logger.error(f"CXHMS stream error: {response.get('message')}")
                
                await cxhms.stream("chat", {
                    "messages": messages,
                    "stream": True
                }, handle_stream_response)
                
                logger.info(f"CXHMS reply generated for danmaku: {danmaku_data.get('content')}")
            else:
                logger.warning("CXHMS client not available")
                
        except Exception as e:
            logger.error(f"Failed to trigger CXHMS reply: {e}")
    
    async def _generate_marker_prompt(self):
        """生成前端标记提示词（已整合到连接流程中）"""
        from .marker_adapter import MarkerAdapter
        
        adapter = MarkerAdapter.get_instance()
        prompt = adapter.generate_marker_prompt(
            self.client_config.get("supported_markers", []),
            self.client_config.get("marker_config", {})
        )
        
        logger.info(f"Generated marker prompt for client {self.client_id}: {len(prompt)} chars")
        return prompt
    
    async def handle_audio(self, websocket: WebSocket, audio_data: bytes, client_id: str):
        """处理音频帧并转发到 ASR（支持双工模式）"""
        try:
            if not self._audio_stream_processor:
                logger.warning("Audio stream processor not initialized")
                return
            
            result = await self._audio_stream_processor.process_audio_chunk(audio_data)
            
            vad_result = result.get("vad", {})
            asr_result = result.get("asr")
            interrupt_result = result.get("interrupt")
            interrupt_type = result.get("interrupt_type")
            is_tts_playing = result.get("is_tts_playing", False)
            is_user_speaking = result.get("is_user_speaking", False)
            
            if vad_result.get("state_changed"):
                status = "speech_start" if vad_result["is_speaking"] else "speech_end"
                await self.manager.send_message(client_id, {
                    "type": "vad_status",
                    "data": {
                        "status": status,
                        "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                    }
                })
            
            if asr_result:
                asr_text = asr_result.get("text", "")
                if asr_text:
                    logger.info(f"ASR recognized: {asr_text}, TTS playing: {is_tts_playing}")
                    await self.manager.send_message(client_id, {
                        "type": "asr_result",
                        "data": {
                            "text": asr_text,
                            "language": asr_result.get("language", "auto"),
                            "is_final": asr_result.get("is_final", False),
                            "emotion": asr_result.get("emotion")
                        }
                    })
            
            if interrupt_result:
                if interrupt_type == "user_interrupt_tts":
                    if interrupt_result.get("should_interrupt"):
                        logger.info(f"User interrupt TTS triggered: {asr_result.get('text', '') if asr_result else ''}")
                        await self._on_asr_interrupt(
                            asr_result.get("text", "") if asr_result else "",
                            interrupt_result.get("llm_response", "")
                        )
                
                elif interrupt_type == "agent_interrupt_user":
                    if interrupt_result.get("should_interrupt"):
                        logger.info(f"Agent interrupt user triggered: {interrupt_result.get('reply_content', '')[:50]}")
                        await self._handle_agent_interrupt(
                            asr_result.get("text", "") if asr_result else "",
                            interrupt_result.get("reply_content", "")
                        )
                    elif interrupt_result.get("should_reply") and asr_result and asr_result.get("is_final"):
                        logger.info(f"Agent should reply after user finished: {interrupt_result.get('reply_content', '')[:50]}")
                        await self._handle_agent_reply(
                            asr_result.get("text", ""),
                            interrupt_result.get("reply_content", "")
                        )
                
        except Exception as e:
            logger.error(f"Failed to process audio: {e}")
    
    def _init_interrupt_modules(self):
        """初始化打断模块"""
        try:
            from .vad_processor import create_audio_stream_processor
            from .asr_interrupt import ASRInterruptModule
            from .agent_interrupt_user import AgentInterruptUser
            from .asr_client import ASRClient
            from .context_manager import get_context_manager
            from config.settings import settings
            
            cxhms_client = self._get_cxhms_client()
            config = settings
            
            self._audio_stream_processor = create_audio_stream_processor()
            
            asr_config = getattr(config, 'asr', None)
            asr_url = getattr(asr_config, 'url', 'http://127.0.0.1:8001') if asr_config else 'http://127.0.0.1:8001'
            asr_timeout = getattr(asr_config, 'timeout', 60) if asr_config else 60
            asr_client = ASRClient(
                base_url=asr_url,
                timeout=asr_timeout
            )
            self._audio_stream_processor.set_streaming_client(asr_client)
            
            asr_interrupt = ASRInterruptModule()
            asr_interrupt.set_session_id(self._session_id)
            asr_interrupt.set_context_manager(get_context_manager())
            asr_interrupt.set_interrupt_callback(self._on_asr_interrupt)
            self._audio_stream_processor.set_asr_interrupt(asr_interrupt)

            agent_interrupt = AgentInterruptUser()
            agent_interrupt.set_cxhms_client(cxhms_client)
            agent_interrupt.set_session_id(self._session_id)
            agent_interrupt.set_context_manager(get_context_manager())
            agent_interrupt.set_asr_client(asr_client)
            agent_interrupt.set_callbacks(
                interrupt_user_callback=self._on_agent_interrupt_user,
                start_tts_callback=self._on_start_tts
            )
            self._audio_stream_processor.set_agent_interrupt(agent_interrupt)
            
            self._interrupt_manager = asr_interrupt
            
            self._initialized = True
            logger.info(f"Interrupt modules initialized for client {self.client_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize interrupt modules: {e}")
    
    async def _handle_tts_start(self, data: dict):
        """处理 TTS 开始播放"""
        self._is_tts_playing = True
        self._current_tts_request_id = data.get("request_id")
        
        if self._interrupt_manager:
            self._interrupt_manager.set_tts_playing(True)
        
        if self._audio_stream_processor:
            self._audio_stream_processor.set_tts_playing(True)
        
        logger.info(f"TTS started playing for client {self.client_id}")

    async def _handle_tts_end(self):
        """处理 TTS 播放结束"""
        self._is_tts_playing = False
        self._current_tts_request_id = None
        
        if self._interrupt_manager:
            self._interrupt_manager.set_tts_playing(False)
        
        if self._audio_stream_processor:
            self._audio_stream_processor.set_tts_playing(False)
            self._audio_stream_processor.reset()
        
        logger.info(f"TTS ended for client {self.client_id}")
    
    async def _handle_audio_stream(self, websocket: WebSocket, data: dict):
        """处理音频流消息"""
        import base64
        
        audio_base64 = data.get("audio")
        reset = data.get("reset", False)
        
        if reset and self._audio_stream_processor:
            self._audio_stream_processor.reset()
            await self.manager.send_message(self.client_id, {
                "type": "audio_stream_reset",
                "data": {"status": "ok"}
            })
            return
        
        if audio_base64:
            audio_data = base64.b64decode(audio_base64)
            await self.handle_audio(websocket, audio_data, self.client_id)
    
    async def _on_asr_interrupt(self, asr_text: str, llm_response: str = ""):
        """ASR 打断回调（用户打断 TTS）"""
        logger.info(f"User interrupted TTS: {asr_text}")

        await self.manager.send_message(self.client_id, {
            "type": "tts_interrupt",
            "data": {
                "reason": "user_speech",
                "asr_text": asr_text
            }
        })
    
    async def _on_agent_interrupt_user(self):
        """Agent 打断用户回调"""
        logger.info(f"Agent interrupting user for client {self.client_id}")
        
        await self.manager.send_message(self.client_id, {
            "type": "user_interrupt",
            "data": {
                "reason": "agent_wants_to_speak"
            }
        })
    
    async def _on_start_tts(self, content: str):
        """开始 TTS 播放回调"""
        logger.info(f"Starting TTS for agent interrupt: {content[:50]}...")
        
        self._is_tts_playing = True
        if self._audio_stream_processor:
            self._audio_stream_processor.set_tts_playing(True)
        
        await self.manager.send_message(self.client_id, {
            "type": "agent_interrupt_reply",
            "data": {
                "content": content
            }
        })
    
    async def _handle_agent_interrupt(self, asr_text: str, reply_content: str):
        """处理 Agent 打断用户事件"""
        logger.info(f"Handling agent interrupt: asr={asr_text}, reply={reply_content[:50]}...")
        
        await self.manager.send_message(self.client_id, {
            "type": "user_interrupt",
            "data": {
                "reason": "agent_wants_to_speak",
                "asr_text": asr_text
            }
        })
        
        if reply_content:
            self._is_tts_playing = True
            if self._audio_stream_processor:
                self._audio_stream_processor.set_tts_playing(True)
            
            await self.manager.send_message(self.client_id, {
                "type": "agent_interrupt_reply",
                "data": {
                    "content": reply_content
                }
            })
    
    async def _handle_agent_reply(self, asr_text: str, reply_content: str):
        """处理 Agent 回复（用户说完后 Agent 回复）"""
        logger.info(f"Handling agent reply: asr={asr_text}, reply={reply_content[:50]}...")
        
        if reply_content:
            await self.manager.send_message(self.client_id, {
                "type": "agent_reply",
                "data": {
                    "content": reply_content,
                    "trigger_asr": asr_text
                }
            })
    
    async def _handle_interrupt(self, asr_text: str, reply_content: str):
        """处理打断事件（旧方法，保持兼容）"""
        await self.manager.send_message(self.client_id, {
            "type": "tts_interrupt",
            "data": {
                "reason": "user_speech_detected",
                "asr_text": asr_text
            }
        })
        
        if reply_content:
            await self.manager.send_message(self.client_id, {
                "type": "interrupt_reply",
                "data": {
                    "content": reply_content
                }
            })
        
        self._is_tts_playing = False
        if self._interrupt_manager:
            self._interrupt_manager.set_tts_playing(False)
