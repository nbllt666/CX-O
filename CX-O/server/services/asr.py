import asyncio
import base64
import logging
import re
import tempfile
import os
from io import BytesIO
from typing import Any, AsyncGenerator, Optional
from concurrent.futures import ThreadPoolExecutor

import torch
import torchaudio

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=2)

TARGET_SAMPLE_RATE = 16000

REGEX = r"<\|.*\|>"


class ASRService:
    _instance: Optional["ASRService"] = None

    def __init__(
        self,
        model_dir: str = "SenseVoice",
        device: str = "cuda",
        language: str = "auto",
        use_itn: bool = True
    ):
        self.model_dir = model_dir
        self.device = device if torch.cuda.is_available() else "cpu"
        self.language = language
        self.use_itn = use_itn
        self.model = None
        self.model_kwargs = {}
        self.start_time = None
        self._streaming_buffer = BytesIO()
        self._streaming_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "ASRService":
        if cls._instance is None:
            from server.config import get_config
            config = get_config()
            cls._instance = cls(
                model_dir=config.asr.model_dir,
                device=config.asr.device,
                language=config.asr.language,
                use_itn=config.asr.use_itn
            )
        return cls._instance

    def load_model(self):
        if self.model is None:
            logger.info(f"Loading ASR model: {self.model_dir} on device: {self.device}")
            self.start_time = self.start_time or os.times().elapsed

            try:
                from model import SenseVoiceSmall
                self.model, self.model_kwargs = SenseVoiceSmall.from_pretrained(
                    model=self.model_dir,
                    device=self.device
                )
                self.model.eval()
                logger.info("ASR model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load ASR model: {e}")
                raise

        return self.model, self.model_kwargs

    def process_audio(self, file_io: BytesIO) -> tuple:
        try:
            import numpy as np
            from scipy.io import wavfile
            from scipy import signal

            file_io.seek(0)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(file_io.read())
                tmp_path = tmp.name

            try:
                sr, data = wavfile.read(tmp_path)
                if data.dtype == np.int16:
                    audio_data = data.astype(np.float32) / 32768.0
                else:
                    audio_data = data.astype(np.float32)

                if audio_data.ndim > 1:
                    audio_data = audio_data.mean(axis=1)

                if sr != TARGET_SAMPLE_RATE:
                    num_samples = int(len(audio_data) * TARGET_SAMPLE_RATE / sr)
                    audio_data = signal.resample(audio_data, num_samples)

                return torch.from_numpy(audio_data), True
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"Error processing audio: {e}")

            try:
                file_io.seek(0)
                data_or_path_or_list, audio_fs = torchaudio.load(file_io)

                if audio_fs != TARGET_SAMPLE_RATE:
                    resampler = torchaudio.transforms.Resample(
                        orig_freq=audio_fs, new_freq=TARGET_SAMPLE_RATE
                    )
                    data_or_path_or_list = resampler(data_or_path_or_list)

                if data_or_path_or_list.dim() > 1:
                    data_or_path_or_list = data_or_path_or_list.mean(0)

                return data_or_path_or_list, True
            except Exception as e2:
                logger.error(f"Error processing audio with torchaudio: {e2}")
                return None, False

    def run_inference(self, audios: list, lang: str) -> list[dict[str, Any]]:
        model, kwargs = self.load_model()

        if lang == "":
            lang = "auto"

        key = [f"audio_{i}" for i in range(len(audios))]

        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess
        except ImportError:
            rich_transcription_postprocess = lambda x: x

        res = model.inference(
            data_in=audios,
            language=lang,
            use_itn=self.use_itn,
            ban_emo_unk=False,
            key=key,
            fs=TARGET_SAMPLE_RATE,
            **kwargs,
        )

        processed_results = []
        if len(res) > 0:
            for item in res[0]:
                processed_item = {
                    "key": item.get("key", ""),
                    "raw_text": item.get("text", ""),
                    "text": "",
                    "language": "",
                    "emotion": "",
                    "event": ""
                }

                raw_text = item.get("text", "")
                processed_item["clean_text"] = re.sub(REGEX, "", raw_text, 0, re.MULTILINE)

                if self.use_itn:
                    try:
                        processed_item["text"] = rich_transcription_postprocess(raw_text)
                    except Exception:
                        processed_item["text"] = processed_item["clean_text"]
                else:
                    processed_item["text"] = processed_item["clean_text"]

                lang_match = re.search(r"<\|(\w+)\|>", raw_text)
                if lang_match:
                    processed_item["language"] = lang_match.group(1)

                emo_match = re.search(
                    r"<\|(HAPPY|SAD|ANGRY|NEUTRAL|FEARFUL|DISGUSTED|SURPRISED)\|>",
                    raw_text
                )
                if emo_match:
                    processed_item["emotion"] = emo_match.group(1)

                event_match = re.search(
                    r"<\|(BGM|Speech|Applause|Laughter|Cry|Sneeze|Breath|Cough|Sing|Speech_Noise)\|>",
                    raw_text
                )
                if event_match:
                    processed_item["event"] = event_match.group(1)

                processed_results.append(processed_item)

        return processed_results

    async def recognize(self, audio_data: bytes, language: str = "auto") -> dict[str, Any]:
        lang = language if language else self.language

        file_io = BytesIO(audio_data)
        audio_tensor, success = self.process_audio(file_io)

        if not success:
            return {
                "text": "",
                "error": "Failed to process audio"
            }

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            executor,
            self.run_inference,
            [audio_tensor],
            lang
        )

        if results:
            return results[0]
        return {"text": "", "error": "No results"}

    async def recognize_base64(self, audio_base64: str, language: str = "auto") -> dict[str, Any]:
        try:
            audio_data = base64.b64decode(audio_base64)
            return await self.recognize(audio_data, language)
        except Exception as e:
            logger.error(f"Error decoding base64 audio: {e}")
            return {"text": "", "error": str(e)}

    async def recognize_stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        language: str = "auto"
    ) -> AsyncGenerator[dict[str, Any], None]:
        lang = language if language else self.language
        accumulated_audio = BytesIO()
        chunk_count = 0

        async for chunk in audio_chunks:
            accumulated_audio.write(chunk)
            chunk_count += 1

            audio_tensor, success = self.process_audio(accumulated_audio)

            if not success:
                continue

            if audio_tensor is not None and len(audio_tensor) > 0:
                loop = asyncio.get_event_loop()
                try:
                    result = await loop.run_in_executor(
                        executor,
                        self.run_inference,
                        [audio_tensor],
                        lang
                    )
                    if result:
                        yield {
                            "text": result[0].get("text", ""),
                            "raw_text": result[0].get("raw_text", ""),
                            "language": result[0].get("language", ""),
                            "emotion": result[0].get("emotion", ""),
                            "event": result[0].get("event", ""),
                            "chunk_index": chunk_count,
                            "is_final": False
                        }
                except Exception as e:
                    logger.error(f"Streaming ASR error: {e}")
                    yield {"text": "", "error": str(e), "is_final": True}
                    break

        yield {"text": "", "is_final": True, "chunk_index": chunk_count}

    async def recognize_file(self, file_path: str, language: str = "auto") -> dict[str, Any]:
        if not os.path.exists(file_path):
            return {"text": "", "error": f"File not found: {file_path}"}

        with open(file_path, "rb") as f:
            audio_data = f.read()

        return await self.recognize(audio_data, language)

    def reset_streaming(self):
        self._streaming_buffer = BytesIO()

    async def health_check(self) -> dict[str, Any]:
        uptime = os.times().elapsed - self.start_time if self.start_time else 0
        try:
            self.load_model()
            return {
                "status": "healthy",
                "device": self.device,
                "model_dir": self.model_dir,
                "model_loaded": self.model is not None,
                "uptime_seconds": uptime
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "device": self.device,
                "model_dir": self.model_dir,
                "model_loaded": False,
                "error": str(e),
                "uptime_seconds": uptime
            }


_asr_service: Optional[ASRService] = None


def get_asr_service() -> ASRService:
    global _asr_service
    if _asr_service is None:
        _asr_service = ASRService.get_instance()
    return _asr_service
