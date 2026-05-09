"""
音频处理器 (ASR/TTS)
"""
from __future__ import annotations

import base64
import logging
import threading
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ASRActions, TTSActions, EmotionActions, EffectActions
from server.services.emotion_parser import get_supported_emotions, parse_text_with_emotions
from server.services.effect_parser import EffectParser

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.asr_client import ASRClient
    from server.services.tts_client import TTSClient

logger = logging.getLogger(__name__)

_tts_playing_clients: set = set()
_tts_playing_lock = threading.Lock()


def set_tts_playing(client_id: str, playing: bool):
    from server.services.asr_interrupt import get_asr_interrupt_module
    interrupt_module = get_asr_interrupt_module()

    with _tts_playing_lock:
        if playing:
            _tts_playing_clients.add(client_id)
        else:
            _tts_playing_clients.discard(client_id)

        has_tts_playing = len(_tts_playing_clients) > 0

    interrupt_module.set_tts_playing(has_tts_playing)


def is_tts_playing() -> bool:
    with _tts_playing_lock:
        return len(_tts_playing_clients) > 0


def init_interrupt_module(cxhms_client):
    from server.services.asr_interrupt import get_asr_interrupt_module
    interrupt_module = get_asr_interrupt_module()
    interrupt_module.set_cxhms_client(cxhms_client)

    from server.services.agent_interrupt_user import get_agent_interrupt_module
    agent_interrupt = get_agent_interrupt_module()
    agent_interrupt.set_cxhms_client(cxhms_client)


def init_audio_stream_processor(asr_client, cxhms_client):
    from server.services.vad_processor import get_audio_stream_processor
    from server.services.agent_interrupt_user import get_agent_interrupt_module

    stream_processor = get_audio_stream_processor()
    stream_processor.set_asr_client(asr_client)

    agent_interrupt = get_agent_interrupt_module()
    agent_interrupt.set_cxhms_client(cxhms_client)
    stream_processor.set_agent_interrupt(agent_interrupt)


def init_agent_interrupt_callbacks(manager, client_id: str):
    from server.services.agent_interrupt_user import get_agent_interrupt_module
    agent_interrupt = get_agent_interrupt_module()

    async def interrupt_user_callback():
        await manager.send_message(client_id, {
            "type": "interrupt_user",
            "data": {
                "reason": "agent_wants_to_speak"
            }
        })

    async def start_tts_callback(reply_content: str):
        await manager.send_message(client_id, {
            "type": "agent_reply",
            "data": {
                "content": reply_content
            }
        })

    agent_interrupt.set_callbacks(
        interrupt_user_callback=interrupt_user_callback,
        start_tts_callback=start_tts_callback
    )


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

            asr_text = result.get("text", "")
            if asr_text:
                try:
                    from server.services.asr_interrupt import get_asr_interrupt_module
                    interrupt_module = get_asr_interrupt_module()
                    if interrupt_module.enabled:
                        await interrupt_module.on_asr_result(asr_text)
                except Exception as e:
                    logger.error(f"ASR interrupt check error: {e}")
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
            tts_playing = True
            set_tts_playing(client_id, True)

            try:
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
            except Exception as e:
                logger.error(f"TTS stream error: {e}")
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=TTSActions.SYNTHESIZE_STREAM,
                    code="TTS_ERROR",
                    message=str(e)
                ))
            finally:
                try:
                    set_tts_playing(client_id, False)
                    tts_playing = False
                except Exception as reset_error:
                    logger.error(f"重置 TTS 播放状态失败：{reset_error}")

                if temp_file:
                    try:
                        import os
                        os.unlink(temp_file)
                    except Exception as cleanup_error:
                        logger.warning(f"清理临时文件失败：{cleanup_error}")

        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            try:
                set_tts_playing(client_id, False)
            except Exception as reset_error:
                logger.error(f"重置 TTS 播放状态失败：{reset_error}")
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

    async def handle_asr_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.services.vad_processor import get_audio_stream_processor
            stream_processor = get_audio_stream_processor()

            audio_base64 = data.get("audio")
            language = data.get("language", "auto")
            reset = data.get("reset", False)

            if reset:
                stream_processor.reset()
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action="asr_stream_status",
                    data={"status": "reset"}
                ))
                return

            if not audio_base64:
                return

            audio_data = base64.b64decode(audio_base64)

            result = await stream_processor.process_audio_chunk(audio_data)

            vad_result = result.get("vad", {})
            asr_result = result.get("asr")
            interrupt_result = result.get("interrupt")

            if vad_result.get("state_changed"):
                status = "speech_start" if vad_result["is_speaking"] else "speech_end"
                await manager.send_message(client_id, {
                    "type": "vad_status",
                    "data": {
                        "status": status,
                        "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                    }
                })

            if asr_result:
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action="asr_stream_result",
                    data={
                        "text": asr_result.get("text", ""),
                        "is_final": not vad_result.get("is_speaking", False)
                    }
                ))

            if interrupt_result and interrupt_result.get("should_interrupt"):
                reply_content = interrupt_result.get("reply_content", "")
                await manager.send_message(client_id, {
                    "type": "agent_interrupt_user",
                    "data": {
                        "should_reply": interrupt_result.get("should_reply", True),
                        "reply_content": reply_content
                    }
                })

            await manager.send_message(client_id, {
                "type": "vad_frame",
                "data": {
                    "is_speaking": vad_result.get("is_speaking", False),
                    "speech_probability": vad_result.get("speech_probability", 0),
                    "speech_duration_ms": vad_result.get("speech_duration_ms", 0)
                }
            })

        except Exception as e:
            logger.error(f"ASR stream error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action="asr_stream",
                code="ASR_STREAM_ERROR",
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
    manager.register_handler("asr_stream", handle_asr_stream)
