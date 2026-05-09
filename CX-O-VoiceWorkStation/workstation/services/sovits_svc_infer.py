"""
So-VITS-SVC 推理服务
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SoVITSSVCInferer:
    def __init__(
        self,
        model_path: Optional[str] = None,
        output_dir: str = "data/models/sovits_svc",
    ):
        self._model_path = model_path
        self._output_dir = Path(output_dir)

    async def infer(
        self,
        audio_path: str,
        speaker_id: int = 0,
        transpose: int = 0,
    ) -> Path:
        audio = Path(audio_path)
        if not audio.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"So-VITS-SVC inference: {audio_path}, speaker={speaker_id}, transpose={transpose}")

        output_path = self._output_dir / f"converted_{audio.stem}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        return output_path
