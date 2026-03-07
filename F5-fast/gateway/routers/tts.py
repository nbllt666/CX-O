"""
TTS Router Module.

This module provides REST API endpoints for Text-to-Speech synthesis,
including synchronous synthesis, streaming, and file upload support.
"""

import base64
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from models.schemas import StreamChunk, TTSRequest, TTSResponse
from services.inference_client import F5TTSClient

logger = logging.getLogger(__name__)

router = APIRouter()


def get_tts_client() -> F5TTSClient:
    """
    Dependency injection for F5TTSClient.
    
    Returns:
        F5TTSClient: The TTS client instance
    """
    try:
        from gateway.main import get_inference_client
        return get_inference_client()
    except ImportError:
        import sys
        sys.path.insert(0, '/app')
        from gateway.main import get_inference_client
        return get_inference_client()


TTSClientDep = Annotated[F5TTSClient, Depends(get_tts_client)]


@router.post(
    "/synthesize",
    response_model=TTSResponse,
    summary="Synthesize Speech",
    description="Convert text to speech using the provided reference audio for voice cloning. Supports both JSON (base64) and multipart form data.",
    status_code=status.HTTP_200_OK,
)
async def synthesize_speech(
    request: Optional[TTSRequest] = None,
    client: TTSClientDep = None,
    reference_audio_file: Optional[UploadFile] = File(None),
    reference_text: Optional[str] = Form(None),
    target_text: Optional[str] = Form(None),
    speed: Optional[float] = Form(1.0),
) -> TTSResponse:
    """
    Synthesize speech from text using voice cloning.
    
    Supports two input modes:
    1. JSON body with base64 encoded reference audio
    2. Multipart form data with audio file upload
    
    Args:
        request: TTS request containing reference audio (base64), text, and speed
        client: Injected F5TTSClient instance
        reference_audio_file: Uploaded reference audio file (multipart mode)
        reference_text: Transcription of reference audio (multipart mode)
        target_text: Text to synthesize (multipart mode)
        speed: Speech speed multiplier (multipart mode)
        
    Returns:
        TTSResponse: Synthesized audio with metadata
        
    Raises:
        HTTPException: If synthesis fails or invalid input provided
    """
    try:
        if request is not None:
            ref_audio_base64 = request.reference_audio
            ref_text = request.reference_text
            tgt_text = request.target_text
            spd = request.speed
            logger.info(f"Processing TTS request (JSON mode) for text: {tgt_text[:50]}...")
        elif reference_audio_file is not None and reference_text is not None and target_text is not None:
            audio_bytes = await reference_audio_file.read()
            ref_audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            ref_text = reference_text
            tgt_text = target_text
            spd = speed
            logger.info(f"Processing TTS request (multipart mode) for text: {tgt_text[:50]}...")
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either JSON body or multipart form data with reference_audio_file, reference_text, and target_text is required",
            )
        
        audio_bytes = await client.infer_async(
            reference_audio=ref_audio_base64,
            reference_text=ref_text,
            target_text=tgt_text,
        )
        
        import numpy as np
        audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
        duration = len(audio_array) / client.TARGET_SAMPLE_RATE
        
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        
        logger.info(f"TTS synthesis completed: duration={duration:.2f}s, sample_rate={client.TARGET_SAMPLE_RATE}")
        
        return TTSResponse(
            audio=audio_base64,
            sample_rate=client.TARGET_SAMPLE_RATE,
            duration=duration,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Speech synthesis failed: {str(e)}",
        )


@router.post(
    "/stream",
    summary="Stream Synthesized Speech",
    description="Convert text to speech and stream the result as Server-Sent Events (SSE)",
    status_code=status.HTTP_200_OK,
)
async def stream_speech(
    request: TTSRequest,
    client: TTSClientDep = None,
) -> StreamingResponse:
    """
    Stream synthesized speech as Server-Sent Events.
    
    Args:
        request: TTS request containing reference audio, text, and speed
        client: Injected F5TTSClient instance
        
    Returns:
        StreamingResponse: SSE stream with audio chunks
        
    Raises:
        HTTPException: If streaming synthesis fails
    """
    async def generate_sse_events():
        chunk_index = 0
        try:
            logger.info(f"Starting streaming TTS for text: {request.target_text[:50]}...")
            
            async for audio_chunk in client.infer_stream(
                reference_audio=request.reference_audio,
                reference_text=request.reference_text,
                target_text=request.target_text,
                chunk_size=4096,
            ):
                chunk_base64 = base64.b64encode(audio_chunk).decode("utf-8")
                
                chunk = StreamChunk(
                    chunk_index=chunk_index,
                    audio_data=chunk_base64,
                    is_final=False,
                )
                
                yield f"data: {chunk.model_dump_json()}\n\n"
                chunk_index += 1
            
            final_chunk = StreamChunk(
                chunk_index=chunk_index,
                audio_data="",
                is_final=True,
            )
            yield f"data: {final_chunk.model_dump_json()}\n\n"
            
            logger.info(f"Streaming TTS completed: {chunk_index} chunks sent")
            
        except Exception as e:
            logger.error(f"Streaming TTS failed: {e}", exc_info=True)
            error_chunk = StreamChunk(
                chunk_index=chunk_index,
                audio_data="",
                is_final=True,
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
    
    return StreamingResponse(
        generate_sse_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/upload",
    response_model=TTSResponse,
    summary="Upload and Synthesize",
    description="Upload a reference audio file and synthesize speech",
    status_code=status.HTTP_200_OK,
)
async def upload_and_synthesize(
    client: TTSClientDep = None,
    reference_audio: UploadFile = File(..., description="Reference audio file for voice cloning"),
    reference_text: str = Form(..., description="Transcription of the reference audio"),
    target_text: str = Form(..., description="Text to synthesize"),
    speed: float = Form(1.0, ge=0.5, le=2.0, description="Speech speed multiplier"),
) -> TTSResponse:
    """
    Upload a reference audio file and synthesize speech.
    
    Args:
        client: Injected F5TTSClient instance
        reference_audio: Uploaded reference audio file
        reference_text: Transcription of the reference audio
        target_text: Text to synthesize
        speed: Speech speed multiplier (0.5 to 2.0)
        
    Returns:
        TTSResponse: Synthesized audio with metadata
        
    Raises:
        HTTPException: If upload or synthesis fails
    """
    try:
        logger.info(f"Processing upload TTS request for text: {target_text[:50]}...")
        logger.info(f"Uploaded file: {reference_audio.filename}, content_type: {reference_audio.content_type}")
        
        audio_bytes = await reference_audio.read()
        
        if not audio_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded audio file is empty",
            )
        
        audio_bytes_result = await client.infer_async(
            reference_audio=audio_bytes,
            reference_text=reference_text,
            target_text=target_text,
        )
        
        import numpy as np
        audio_array = np.frombuffer(audio_bytes_result, dtype=np.float32)
        duration = len(audio_array) / client.TARGET_SAMPLE_RATE
        
        audio_base64 = base64.b64encode(audio_bytes_result).decode("utf-8")
        
        logger.info(f"Upload TTS synthesis completed: duration={duration:.2f}s")
        
        return TTSResponse(
            audio=audio_base64,
            sample_rate=client.TARGET_SAMPLE_RATE,
            duration=duration,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload TTS synthesis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Speech synthesis failed: {str(e)}",
        )


@router.post(
    "/batch",
    response_model=list[TTSResponse],
    summary="Batch Synthesize",
    description="Process multiple TTS requests in a single batch",
    status_code=status.HTTP_200_OK,
)
async def batch_synthesize(
    requests: list[TTSRequest],
    client: TTSClientDep = None,
) -> list[TTSResponse]:
    """
    Batch synthesize speech from multiple texts.
    
    Args:
        requests: List of TTS requests
        client: Injected F5TTSClient instance
        
    Returns:
        list[TTSResponse]: List of synthesized audio responses
        
    Raises:
        HTTPException: If batch synthesis fails
    """
    try:
        logger.info(f"Processing batch TTS request with {len(requests)} items")
        
        results = []
        for idx, req in enumerate(requests):
            try:
                audio_bytes = await client.infer_async(
                    reference_audio=req.reference_audio,
                    reference_text=req.reference_text,
                    target_text=req.target_text,
                )
                
                import numpy as np
                audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
                duration = len(audio_array) / client.TARGET_SAMPLE_RATE
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
                
                results.append(
                    TTSResponse(
                        audio=audio_base64,
                        sample_rate=client.TARGET_SAMPLE_RATE,
                        duration=duration,
                    )
                )
                logger.info(f"Batch item {idx + 1}/{len(requests)} completed")
            except Exception as e:
                logger.error(f"Batch item {idx + 1} failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Batch synthesis failed at item {idx + 1}: {str(e)}",
                )
        
        logger.info(f"Batch TTS synthesis completed: {len(results)} items")
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch TTS synthesis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch synthesis failed: {str(e)}",
        )
