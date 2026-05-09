"""
情感参考音频生成器
统一管理 CosyVoice 参考音频生成
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class EmotionRefGenerator:
    def __init__(
        self,
        cosyvoice_url: str = "http://127.0.0.1:50000",
        output_dir: str = "data/voice_refs",
    ):
        self._cosyvoice_url = cosyvoice_url
        self._output_dir = Path(output_dir)

    async def generate_all(
        self,
        base_audio_path: str,
        sample_text: str = "这是参考音频样本。",
        transition_text: str = "嗯，",
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        from workstation.services.cosyvoice_client import CosyVoiceClient

        base_audio = Path(base_audio_path)
        if not base_audio.exists():
            raise FileNotFoundError(f"Base audio file not found: {base_audio_path}")

        emotions_dir = self._output_dir / "emotions"
        transitions_dir = self._output_dir / "transitions"
        emotions_dir.mkdir(parents=True, exist_ok=True)
        transitions_dir.mkdir(parents=True, exist_ok=True)

        if not force:
            existing_emotions = len(list(emotions_dir.glob("*.wav"))) if emotions_dir.exists() else 0
            existing_transitions = len(list(transitions_dir.glob("*.wav"))) if transitions_dir.exists() else 0
            if existing_emotions == 8 and existing_transitions == 56:
                logger.info("All 64 reference audio files already exist. Skipping generation.")
                return {"emotions": existing_emotions, "transitions": existing_transitions, "total": 64, "skipped": True}

        client = CosyVoiceClient(base_url=self._cosyvoice_url)

        try:
            if not await client.health_check():
                raise ConnectionError(f"CosyVoice service not available at {self._cosyvoice_url}")

            results = await client.generate_all_refs(
                ref_audio=base_audio,
                emotions_dir=emotions_dir,
                transitions_dir=transitions_dir,
                sample_text=sample_text,
                transition_text=transition_text,
                progress_callback=progress_callback,
            )

            return {
                "emotions": len(results.get("emotions", {})),
                "transitions": len(results.get("transitions", {})),
                "total": results.get("total", 0),
                "skipped": False,
            }
        finally:
            await client.close()
