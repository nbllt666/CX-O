"""
音频处理器 (ASR/TTS)
"""
from __future__ import annotations

import base64
import logging
import threading
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ASRActions, TTSActions, EmotionActions, EffectActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)

_tts_playing_clients: set = set()
_tts_playing_lock = threading.Lock()


def set_tts_playing(client_id: str, playing: bool):
    from server.services.asr import ASRInterrupt

    with _tts_playing_lock:
        if playing:
            _tts_playing_clients.add(client_id)
        else:
            _tts_playing_clients.discard(client_id)

        has_tts_playing = len(_tts_playing_clients) > 0

    try:
        interrupt_module = ASRInterrupt.get_instance()
        interrupt_module.set_tts_playing(has_tts_playing)
    except Exception as e:
        logger.warning(f"Could not set TTS playing status: {e}")


def is_tts_playing() -> bool:
    with _tts_playing_lock:
        return len(_tts_playing_clients) > 0


def init_interrupt_module():
    try:
        from server.services.asr import ASRInterrupt
        interrupt_module = ASRInterrupt.get_instance()
    except Exception as e:
        logger.warning(f"Could not initialize interrupt module: {e}")


def init_audio_stream_processor():
    pass


def init_agent_interrupt_callbacks(manager, client_id: str):
    pass


def register_audio_handlers(manager: "ConnectionManager"):
    _manager = manager
    effect_parser = None

    try:
        from server.services.effect import EffectParser
        effect_parser = EffectParser()
    except ImportError:
        pass

    async def handle_asr_recognize(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            audio_base64 = data.get("audio")
            language = data.get("language", "auto")

            if not audio_base64:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ASRActions.RECOGNIZE,
                    code="INVALID_REQUEST",
                    message="Missing audio data"
                ))
                return

            audio_data = base64.b64decode(audio_base64)

            from server.services.asr import get_asr_service
            asr_service = get_asr_service()

            if asr_service is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ASRActions.RECOGNIZE,
                    code="ASR_NOT_AVAILABLE",
                    message="ASR service is not available"
                ))
                return

            result = await asr_service.recognize(audio_data, language)

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ASRActions.RECOGNIZE,
                data=result
            ))

            asr_text = result.get("text", "")
            if asr_text:
                try:
                    from server.services.asr import ASRInterrupt
                    interrupt_module = ASRInterrupt.get_instance()
                    if hasattr(interrupt_module, 'enabled') and interrupt_module.enabled:
                        await interrupt_module.on_asr_result(asr_text)
                except Exception as e:
                    logger.error(f"ASR interrupt check error: {e}")
        except Exception as e:
            logger.error(f"ASR recognize error: {e}")
            await _manager.send_message(client_id, create_error(
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
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE,
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

            from server.services.tts import get_tts_service
            tts_service = get_tts_service()

            if tts_service is None:
                if temp_file:
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE,
                    code="TTS_NOT_AVAILABLE",
                    message="TTS service is not available"
                ))
                return

            audio_bytes = await tts_service.synthesize(text, **kwargs)

            if temp_file:
                try:
                    os.unlink(temp_file)
                except Exception:
                    pass

            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE,
                data={
                    "audio_data": audio_base64,
                    "format": "wav"
                }
            ))
        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            await _manager.send_message(client_id, create_error(
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
                await _manager.send_message(client_id, create_error(
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

            from server.services.tts import get_tts_service
            tts_service = get_tts_service()

            if tts_service is None:
                if temp_file:
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE_STREAM,
                    code="TTS_NOT_AVAILABLE",
                    message="TTS service is not available"
                ))
                return

            chunk_index = 0
            set_tts_playing(client_id, True)

            try:
                if emotion_enabled or effects_enabled:
                    async for chunk in tts_service.synthesize_stream_with_emotions(text, **kwargs):
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

                        await _manager.send_message(client_id, stream_msg)
                        chunk_index += 1
                else:
                    async for chunk in tts_service.synthesize_stream(text, **kwargs):
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

                        await _manager.send_message(client_id, stream_msg)
                        chunk_index += 1
            except Exception as e:
                logger.error(f"TTS stream error: {e}")
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE_STREAM,
                    code="TTS_ERROR",
                    message=str(e)
                ))
            finally:
                set_tts_playing(client_id, False)

                if temp_file:
                    try:
                        import os
                        os.unlink(temp_file)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=TTSActions.SYNTHESIZE_STREAM,
                code="TTS_ERROR",
                message=str(e)
            ))

    async def handle_emotions_list(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            emotions = []
            try:
                from server.services.emotion import get_supported_emotions
                emotions = get_supported_emotions()
            except ImportError:
                emotions = ["happy", "sad", "angry", "surprised", "fearful", "disgusted", "neutral"]

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EmotionActions.LIST,
                data={"emotions": emotions}
            ))
        except Exception as e:
            logger.error(f"Emotions list error: {e}")
            await _manager.send_message(client_id, create_error(
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
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=EmotionActions.PARSE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return

            segments = []
            try:
                from server.services.emotion import parse_text_with_emotions
                segments = parse_text_with_emotions(text)
            except ImportError:
                segments = [{"type": "text", "content": text}]

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EmotionActions.PARSE,
                data={"segments": segments}
            ))
        except Exception as e:
            logger.error(f"Emotions parse error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EmotionActions.PARSE,
                code="EMOTION_ERROR",
                message=str(e)
            ))

    async def handle_effects_list(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            effects = []
            if effect_parser:
                effects = effect_parser.get_available_effects()

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EffectActions.LIST,
                data={"effects": effects}
            ))
        except Exception as e:
            logger.error(f"Effects list error: {e}")
            await _manager.send_message(client_id, create_error(
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
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=EffectActions.PARSE,
                    code="INVALID_REQUEST",
                    message="Missing text"
                ))
                return

            segments = []
            if effect_parser:
                segments = effect_parser.parse_text_with_effects(text)
            else:
                segments = [{"type": "text", "content": text}]

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=EffectActions.PARSE,
                data={"segments": segments}
            ))
        except Exception as e:
            logger.error(f"Effects parse error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=EffectActions.PARSE,
                code="EFFECT_ERROR",
                message=str(e)
            ))

    async def handle_asr_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.services.asr import get_asr_service
            asr_service = get_asr_service()

            if asr_service is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action="asr_stream",
                    code="ASR_NOT_AVAILABLE",
                    message="ASR service is not available"
                ))
                return

            audio_base64 = data.get("audio")
            language = data.get("language", "auto")
            reset = data.get("reset", False)

            if reset:
                asr_service.reset_streaming()
                await _manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action="asr_stream_status",
                    data={"status": "reset"}
                ))
                return

            if not audio_base64:
                return

            audio_data = base64.b64decode(audio_base64)

            result = await asr_service.recognize(audio_data, language)

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action="asr_stream_result",
                data={
                    "text": result.get("text", ""),
                    "is_final": True
                }
            ))

        except Exception as e:
            logger.error(f"ASR stream error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action="asr_stream",
                code="ASR_STREAM_ERROR",
                message=str(e)
            ))

    _manager.register_handler(ASRActions.RECOGNIZE, handle_asr_recognize)
    _manager.register_handler(ASRActions.RECOGNIZE_BASE64, handle_asr_recognize)
    _manager.register_handler(TTSActions.SYNTHESIZE, handle_tts_synthesize)
    _manager.register_handler(TTSActions.SYNTHESIZE_STREAM, handle_tts_synthesize_stream)
    _manager.register_handler(EmotionActions.LIST, handle_emotions_list)
    _manager.register_handler(EmotionActions.PARSE, handle_emotions_parse)
    _manager.register_handler(EffectActions.LIST, handle_effects_list)
    _manager.register_handler(EffectActions.PARSE, handle_effects_parse)
    _manager.register_handler("asr_stream", handle_asr_stream)