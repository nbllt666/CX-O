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
        
        from services.marker_adapter import MarkerAdapter
        adapter = MarkerAdapter.get_instance()
        adapter.set_client_config(
            self.client_id,
            self.client_config.get("supported_markers", []),
            self.client_config.get("marker_config", {})
        )
        
        self._marker_prompt = adapter.generate_marker_prompt(
            self.client_config.get("supported_markers", []),
            self.client_config.get("marker_config", {})
        )
        
        from services.context_manager import get_context_manager
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
        from services.firewall import FirewallService
        firewall = FirewallService.get_instance()
        
        result = await firewall.decide_danmaku(data)
        
        # 发送处理结果
        from gateway.server import manager
        await manager.send_message(self.client_id, {
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
        from services.context_manager import get_context_manager
        from services.frontend_marker import FrontendMarkerParser
        
        # 将弹幕加入上下文
        user = danmaku_data.get("user", {})
        context_message = {
            "role": f"直播间消息 userid:{user.get('uid', '')} username:{user.get('username', '')}",
            "content": danmaku_data.get("content", "")
        }
        
        # 添加到上下文管理器
        ctx_mgr = get_context_manager()
        session_id = f"live_{self.client_id}"
        ctx_mgr.add_message(session_id, context_message)
        
        messages = ctx_mgr.get_context_with_system_prompt(session_id)
        
        # 调用 CXHMS 生成回复
        try:
            from gateway.server import get_cxhms_client
            cxhms = get_cxhms_client()
            
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
        from services.marker_adapter import MarkerAdapter
        
        adapter = MarkerAdapter.get_instance()
        prompt = adapter.generate_marker_prompt(
            self.client_config.get("supported_markers", []),
            self.client_config.get("marker_config", {})
        )
        
        logger.info(f"Generated marker prompt for client {self.client_id}: {len(prompt)} chars")
        return prompt
    
    async def handle_audio(self, websocket: WebSocket, audio_data: bytes, client_id: str):
        """处理音频帧并转发到 ASR（支持打断检测）"""
        try:
            if self._is_tts_playing and self._audio_stream_processor:
                result = await self._audio_stream_processor.process_audio_chunk(audio_data)
                
                vad_result = result.get("vad", {})
                asr_result = result.get("asr")
                interrupt_result = result.get("interrupt")
                
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
                        logger.info(f"ASR recognized during TTS: {asr_text}")
                        await self.manager.send_message(client_id, {
                            "type": "asr_result",
                            "data": {
                                "text": asr_text,
                                "language": asr_result.get("language", "auto"),
                                "is_final": not vad_result.get("is_speaking", False)
                            }
                        })
                
                if interrupt_result and interrupt_result.get("should_interrupt"):
                    logger.info(f"Interrupt triggered during TTS playback")
                    await self._handle_interrupt(asr_result.get("text", "") if asr_result else "", 
                                                  interrupt_result.get("reply_content", ""))
            else:
                from services.asr_client import ASRClient
                asr_client = ASRClient(base_url="http://127.0.0.1:8001", timeout=120)
                
                result = await asr_client.recognize(audio_data, language="auto")
                
                asr_text = result.get("text", "")
                if asr_text:
                    logger.info(f"ASR recognized: {asr_text}")
                    
                    await self.manager.send_message(client_id, {
                        "type": "asr_result",
                        "data": {
                            "text": asr_text,
                            "language": result.get("language", "auto")
                        }
                    })
                
        except Exception as e:
            logger.error(f"Failed to process audio: {e}")
    
    def _init_interrupt_modules(self):
        """初始化打断模块"""
        try:
            from services.vad_processor import get_audio_stream_processor
            from services.asr_interrupt import get_asr_interrupt_module
            from services.agent_interrupt_user import get_agent_interrupt_module
            from services.asr_client import ASRClient
            from gateway.server import get_cxhms_client, get_config
            
            cxhms_client = get_cxhms_client()
            config = get_config()
            
            self._audio_stream_processor = get_audio_stream_processor()
            
            asr_config = config.services.asr
            asr_client = ASRClient(
                base_url=asr_config.url or "http://127.0.0.1:8001",
                timeout=getattr(asr_config, 'timeout', 60)
            )
            self._audio_stream_processor.set_asr_client(asr_client)
            
            asr_interrupt = get_asr_interrupt_module()
            asr_interrupt.set_cxhms_client(cxhms_client)
            asr_interrupt.set_interrupt_callback(self._on_asr_interrupt)
            
            agent_interrupt = get_agent_interrupt_module()
            agent_interrupt.set_cxhms_client(cxhms_client)
            agent_interrupt.set_asr_client(asr_client)
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
        
        logger.info(f"TTS started playing for client {self.client_id}")
    
    async def _handle_tts_end(self):
        """处理 TTS 播放结束"""
        self._is_tts_playing = False
        self._current_tts_request_id = None
        
        if self._interrupt_manager:
            self._interrupt_manager.set_tts_playing(False)
        
        if self._audio_stream_processor:
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
        """ASR 打断回调"""
        logger.info(f"ASR interrupt callback triggered: {asr_text}")
        
        await self.manager.send_message(self.client_id, {
            "type": "tts_interrupt",
            "data": {
                "reason": "user_speech",
                "asr_text": asr_text
            }
        })
        
        if llm_response:
            await self.manager.send_message(self.client_id, {
                "type": "interrupt_reply",
                "data": {
                    "content": llm_response
                }
            })
    
    async def _handle_interrupt(self, asr_text: str, reply_content: str):
        """处理打断事件"""
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
