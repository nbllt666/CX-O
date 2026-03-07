"""
音频处理器 (ASR/TTS)
"""
from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from protocol.message import create_response, create_error, create_stream
from protocol.actions import ASRActions, TTSActions, EmotionActions, EffectActions
from services.emotion_parser import get_supported_emotions, parse_text_with_emotions
from services.effect_parser import EffectParser

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.asr_client import ASRClient
    from services.tts_client import TTSClient

logger = logging.getLogger(__name__)


def register_audio_handlers(
    manager: "ConnectionManager",
    asr_client: "ASRClient",
    tts_client: "TTSClient",
    effects_dir: str | None = None
):
    effect_parser = EffectParser(effects_dir)
    
    async def handle_asr_recognize(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            audio_base64 = data.get("audio")
            language = data.get("language", "auto")
            
            if not audio_base64:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ASRActions.RECOGNIZE,
                    code="INVALID_REQUEST",
                    message="Missing audio data"
                ))
                return
            
            audio_data = base64.b64decode(audio_base64)
            result = await asr_client.recognize(audio_data, language)
            
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ASRActions.RECOGNIZE,
                data=result
            ))
        except Exception as e:
            logger.error(f"ASR recognize error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ASRActions.RECOGNIZE,
                code="ASR_ERROR",
                message=str(e)
            ))

    async def handle_tts_synthesize(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            text = data.get("text", "")
            ref_audio_base64 = data.get("ref_audio")
            ref_text = data.get("ref_text", "")
            
            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return
            
            kwargs = {}
            if ref_audio_base64:
                import tempfile
                import os
                audio_data = base64.b64decode(ref_audio_base64)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_data)
                    kwargs["ref_audio_path"] = f.name
                if ref_text:
                    kwargs["ref_text"] = ref_text
            
            audio_bytes = await tts_client.synthesize(text, **kwargs)
            
            if "ref_audio_path" in kwargs:
                try:
                    os.unlink(kwargs["ref_audio_path"])
                except Exception:
                    pass
            
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE,
                data={
                    "audio_data": audio_base64,
                    "format": "wav"
                }
            ))
        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE,
                code="TTS_ERROR",
                message=str(e)
            ))

    async def handle_tts_synthesize_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            text = data.get("text", "")
            ref_audio_base64 = data.get("ref_audio")
            ref_text = data.get("ref_text", "")
            emotion_enabled = data.get("emotion_enabled", False)
            effects_enabled = data.get("effects_enabled", False)
            
            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE_STREAM,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return
            
            kwargs = {}
            temp_file = None
            if ref_audio_base64:
                import tempfile
                import os
                audio_data = base64.b64decode(ref_audio_base64)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_data)
                    temp_file = f.name
                    kwargs["ref_audio_path"] = temp_file
                if ref_text:
                    kwargs["ref_text"] = ref_text
            
            chunk_index = 0
            
            if emotion_enabled or effects_enabled:
                async for chunk in tts_client.synthesize_stream_with_emotions(text, **kwargs):
                    audio_base64 = None
                    if chunk.get("audio_data"):
                        audio_base64 = base64.b64encode(chunk["audio_data"]).decode("utf-8")
                    
                    stream_msg = create_stream(
                        request_id=request_id,
                        action=TTSActions.SYNTHESIZE_STREAM,
                        chunk_index=chunk_index,
                        data={
                            "text_segment": chunk.get("text_segment", ""),
                            "audio_data": audio_base64,
                            "emotion": chunk.get("emotion"),
                            "is_effect": chunk.get("is_effect", False),
                            "effect_name": chunk.get("effect_name")
                        },
                        is_final=chunk.get("is_final", False)
                    )
                    
                    await manager.send_message(client_id, stream_msg)
                    chunk_index += 1
            else:
                async for chunk in tts_client.synthesize_stream(text, **kwargs):
                    audio_base64 = None
                    if chunk.get("audio_data"):
                        audio_base64 = base64.b64encode(chunk["audio_data"]).decode("utf-8")
                    
                    stream_msg = create_stream(
                        request_id=request_id,
                        action=TTSActions.SYNTHESIZE_STREAM,
                        chunk_index=chunk_index,
                        data={
                            "text_segment": chunk.get("text_segment", ""),
                            "audio_data": audio_base64
                        },
                        is_final=chunk.get("is_final", False)
                    )
                    
                    await manager.send_message(client_id, stream_msg)
                    chunk_index += 1
            
            if temp_file:
                try:
                    import os
                    os.unlink(temp_file)
                except Exception:
                    pass
                
        except Exception as e:
            logger.error(f"TTS stream error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE_STREAM,
                code="TTS_ERROR",
                message=str(e)
            ))

    async def handle_emotions_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        
        try:
            emotions = get_supported_emotions()
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EmotionActions.LIST,
                data={"emotions": emotions}
            ))
        except Exception as e:
            logger.error(f"Emotions list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EmotionActions.LIST,
                code="EMOTION_ERROR",
                message=str(e)
            ))

    async def handle_emotions_parse(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            text = data.get("text", "")
            
            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=EmotionActions.PARSE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return
            
            segments = parse_text_with_emotions(text)
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EmotionActions.PARSE,
                data={"segments": segments}
            ))
        except Exception as e:
            logger.error(f"Emotions parse error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EmotionActions.PARSE,
                code="EMOTION_ERROR",
                message=str(e)
            ))

    async def handle_effects_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        
        try:
            effects = effect_parser.get_available_effects()
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EffectActions.LIST,
                data={"effects": effects}
            ))
        except Exception as e:
            logger.error(f"Effects list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EffectActions.LIST,
                code="EFFECT_ERROR",
                message=str(e)
            ))

    async def handle_effects_parse(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            text = data.get("text", "")
            
            if not text:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=EffectActions.PARSE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return
            
            segments = effect_parser.parse_text_with_effects(text)
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EffectActions.PARSE,
                data={"segments": segments}
            ))
        except Exception as e:
            logger.error(f"Effects parse error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EffectActions.PARSE,
                code="EFFECT_ERROR",
                message=str(e)
            ))

    manager.register_handler(ASRActions.RECOGNIZE, handle_asr_recognize)
    manager.register_handler(ASRActions.RECOGNIZE_BASE64, handle_asr_recognize)
    manager.register_handler(TTSActions.SYNTHESIZE, handle_tts_synthesize)
    manager.register_handler(TTSActions.SYNTHESIZE_STREAM, handle_tts_synthesize_stream)
    manager.register_handler(EmotionActions.LIST, handle_emotions_list)
    manager.register_handler(EmotionActions.PARSE, handle_emotions_parse)
    manager.register_handler(EffectActions.LIST, handle_effects_list)
    manager.register_handler(EffectActions.PARSE, handle_effects_parse)
