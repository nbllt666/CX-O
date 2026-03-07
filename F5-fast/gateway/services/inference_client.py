"""
Inference Client Service for F5-TTS.

This module provides a client wrapper for the F5-TTS inference service,
using httpx for HTTP communication.
"""

import asyncio
import base64
import io
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional, Union

import httpx
import numpy as np
import torch
import torchaudio

logger = logging.getLogger(__name__)


class F5TTSClient:
    """
    HTTP client for F5-TTS inference service.
    
    Provides synchronous and streaming inference methods with automatic
    connection management, audio preprocessing, and text preprocessing.
    """
    
    DEFAULT_INFERENCE_URL = "http://inference-service:8000"
    TARGET_SAMPLE_RATE = 24000
    TARGET_RMS = 0.15
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
    def __init__(
        self,
        inference_url: str = DEFAULT_INFERENCE_URL,
        model_name: str = "f5_tts",
        reference_sample_rate: int = 16000,
        timeout: float = 60.0,
    ):
        """
        Initialize the F5-TTS inference client.
        
        Args:
            inference_url: Base URL of the inference service
            model_name: Name of the F5-TTS model
            reference_sample_rate: Expected sample rate of input reference audio
            timeout: HTTP request timeout in seconds
        """
        self.inference_url = inference_url.rstrip("/")
        self.model_name = model_name
        self.reference_sample_rate = reference_sample_rate
        self.timeout = timeout
        
        self._client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None
        self._initialized = False
        
        self._resampler = torchaudio.transforms.Resample(
            reference_sample_rate, 
            self.TARGET_SAMPLE_RATE
        )
    
    def _get_sync_client(self) -> httpx.Client:
        """
        Get or create the synchronous HTTP client with lazy initialization.
        
        Returns:
            httpx.Client: HTTP client instance
        """
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.info(f"Sync HTTP client initialized for {self.inference_url}")
        return self._sync_client
    
    async def _get_async_client(self) -> httpx.AsyncClient:
        """
        Get or create the async HTTP client with lazy initialization.
        
        Returns:
            httpx.AsyncClient: Async HTTP client instance
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.info(f"Async HTTP client initialized for {self.inference_url}")
        return self._client
    
    async def health_check(self) -> dict:
        """
        Check the health status of the inference service.
        
        Returns:
            dict: Health status information
        """
        result = {
            "service_live": False,
            "model_ready": False,
        }
        
        try:
            client = await self._get_async_client()
            
            response = await client.get(
                f"{self.inference_url}/v2/models/{self.model_name}"
            )
            
            if response.status_code == 200:
                result["service_live"] = True
                data = response.json()
                result["model_ready"] = data.get("ready", False)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
        
        return result
    
    def _load_audio_from_file(self, audio_path: Union[str, Path]) -> tuple[torch.Tensor, int]:
        """
        Load audio from a file path.
        
        Args:
            audio_path: Path to the audio file
            
        Returns:
            tuple: (waveform tensor, sample_rate)
        """
        waveform, sample_rate = torchaudio.load(str(audio_path))
        return waveform, sample_rate
    
    def _load_audio_from_base64(self, audio_base64: str) -> tuple[torch.Tensor, int]:
        """
        Load audio from base64 encoded bytes.
        
        Assumes WAV format for base64 encoded audio.
        
        Args:
            audio_base64: Base64 encoded audio data
            
        Returns:
            tuple: (waveform tensor, sample_rate)
        """
        audio_bytes = base64.b64decode(audio_base64)
        buffer = io.BytesIO(audio_bytes)
        waveform, sample_rate = torchaudio.load(buffer)
        return waveform, sample_rate
    
    def _preprocess_audio(
        self, 
        audio_input: Union[str, Path, torch.Tensor, tuple[torch.Tensor, int], bytes, np.ndarray],
        input_sample_rate: Optional[int] = None
    ) -> np.ndarray:
        """
        Preprocess audio for model input.
        
        Steps:
        1. Load audio from file path, base64, bytes, or tensor
        2. Resample to 24kHz if needed
        3. Normalize audio (target RMS 0.15)
        4. Convert to numpy array
        
        Args:
            audio_input: Audio input (file path, tensor, bytes, or preprocessed array)
            input_sample_rate: Sample rate if audio_input is a tensor
            
        Returns:
            np.ndarray: Preprocessed audio waveform
        """
        if isinstance(audio_input, np.ndarray):
            return audio_input
        
        if isinstance(audio_input, bytes):
            buffer = io.BytesIO(audio_input)
            waveform, sample_rate = torchaudio.load(buffer)
        elif isinstance(audio_input, (str, Path)):
            waveform, sample_rate = self._load_audio_from_file(audio_input)
        elif isinstance(audio_input, torch.Tensor):
            if input_sample_rate is None:
                input_sample_rate = self.reference_sample_rate
            waveform = audio_input
            sample_rate = input_sample_rate
        elif isinstance(audio_input, tuple):
            waveform, sample_rate = audio_input
        else:
            raise ValueError(f"Unsupported audio input type: {type(audio_input)}")
        
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        
        ref_rms = torch.sqrt(torch.mean(torch.square(waveform)))
        if ref_rms < self.TARGET_RMS:
            waveform = waveform * self.TARGET_RMS / ref_rms
        
        if sample_rate != self.TARGET_SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(
                sample_rate, 
                self.TARGET_SAMPLE_RATE
            )
            waveform = resampler(waveform)
        
        return waveform.squeeze(0).numpy().astype(np.float32)
    
    async def infer_async(
        self,
        reference_audio: Union[str, Path, torch.Tensor, tuple[torch.Tensor, int], bytes, np.ndarray],
        reference_text: str,
        target_text: str,
    ) -> bytes:
        """
        Perform asynchronous TTS inference.
        
        Args:
            reference_audio: Reference audio input
            reference_text: Transcription text of the reference audio
            target_text: The text to synthesize
            
        Returns:
            bytes: Synthesized audio waveform as bytes
        """
        if isinstance(reference_audio, np.ndarray):
            preprocessed_audio = reference_audio
        else:
            preprocessed_audio = self._preprocess_audio(reference_audio)
        
        logger.info(f"Preprocessed text: ref='{reference_text[:30]}...', target='{target_text[:30]}...'")
        
        async def _infer():
            client = await self._get_async_client()
            
            audio_base64 = base64.b64encode(preprocessed_audio.tobytes()).decode("utf-8")
            
            payload = {
                "reference_audio": audio_base64,
                "reference_text": reference_text,
                "target_text": target_text,
            }
            
            response = await client.post(
                f"{self.inference_url}/v2/models/{self.model_name}/infer",
                json=payload,
            )
            
            if response.status_code != 200:
                raise RuntimeError(f"Inference failed with status {response.status_code}: {response.text}")
            
            result = response.json()
            
            if "audio" in result:
                return base64.b64decode(result["audio"])
            elif "waveform" in result:
                return base64.b64decode(result["waveform"])
            else:
                raise RuntimeError(f"Unexpected response format: {result.keys()}")
        
        return await self._async_retry_with_backoff(_infer)
    
    async def infer_stream(
        self,
        reference_audio: Union[str, Path, torch.Tensor, tuple[torch.Tensor, int], bytes, np.ndarray],
        reference_text: str,
        target_text: str,
        chunk_size: int = 4096,
    ) -> AsyncGenerator[bytes, None]:
        """
        Perform streaming TTS inference.
        
        Note: F5-TTS model generates audio in one pass. This method simulates
        streaming by chunking the output audio.
        
        Args:
            reference_audio: Reference audio input
            reference_text: Transcription text of the reference audio
            target_text: The text to synthesize
            chunk_size: Size of each audio chunk in samples
            
        Yields:
            bytes: Audio chunks as bytes
        """
        audio_bytes = await self.infer_async(reference_audio, reference_text, target_text)
        
        audio_array = np.frombuffer(audio_bytes, dtype=np.float32)
        total_samples = len(audio_array)
        
        for i in range(0, total_samples, chunk_size):
            chunk = audio_array[i:i + chunk_size]
            yield chunk.tobytes()
            await asyncio.sleep(0)
    
    async def _async_retry_with_backoff(self, func, *args, **kwargs):
        """
        Execute an async function with retry logic and exponential backoff.
        
        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Any: Function result
            
        Raises:
            Exception: If all retries fail
        """
        last_exception = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
        
        raise last_exception
    
    async def async_close(self):
        """Asynchronously close the HTTP client connections."""
        if self._client is not None:
            try:
                await self._client.aclose()
                logger.info("Async HTTP client closed")
            except Exception as e:
                logger.error(f"Error closing async HTTP client: {e}")
            finally:
                self._client = None
    
    def close(self):
        """Close the synchronous HTTP client connections."""
        if self._sync_client is not None:
            try:
                self._sync_client.close()
                logger.info("Sync HTTP client closed")
            except Exception as e:
                logger.error(f"Error closing sync HTTP client: {e}")
            finally:
                self._sync_client = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.async_close()
        return False
