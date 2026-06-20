"""
情感参考音频生成器
统一管理 CosyVoice 参考音频生成
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
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
        # 允许作为输入基准音频的根目录，默认仅允许 data/input，防止任意本地文件读取。
        self._allowed_audio_root = Path("data/input").resolve()

    def _validate_audio_path(self, audio_path: str) -> Path:
        """校验 audio_path 解析后必须位于允许的根目录之内，防止任意文件读取。"""
        audio = Path(audio_path)
        try:
            resolved = audio.resolve()
        except Exception as e:
            raise ValueError(f"Invalid audio path: {audio_path}: {e}")
        try:
            resolved.relative_to(self._allowed_audio_root)
        except ValueError:
            raise ValueError(
                f"audio path must be located under {self._allowed_audio_root}, got: {resolved}"
            )
        return resolved

    async def generate_all(
        self,
        base_audio_path: str,
        sample_text: str = "这是参考音频样本。",
        transition_text: str = "嗯，",
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        from workstation.services.cosyvoice_client import CosyVoiceClient

        base_audio = self._validate_audio_path(base_audio_path)
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

    async def generate_and_pack_zip(
        self,
        base_audio_path: str,
        sample_text: str = "这是参考音频样本。",
        transition_text: str = "嗯，",
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Path:
        from workstation.services.cosyvoice_client import (
            ALL_EMOTIONS,
            EMOTION_INSTRUCT_TEMPLATES,
            get_transition_instruct,
        )

        await self.generate_all(
            base_audio_path=base_audio_path,
            sample_text=sample_text,
            transition_text=transition_text,
            force=force,
            progress_callback=progress_callback,
        )

        emotions_dir = self._output_dir / "emotions"
        transitions_dir = self._output_dir / "transitions"

        emotions_meta = []
        for emotion in ALL_EMOTIONS:
            wav_path = emotions_dir / f"{emotion}.wav"
            if wav_path.exists():
                emotions_meta.append({
                    "file": f"emotions/{emotion}.wav",
                    "emotion": emotion,
                    "text": sample_text,
                    "instruct_text": EMOTION_INSTRUCT_TEMPLATES.get(emotion, ""),
                })

        transitions_meta = []
        for from_emotion in ALL_EMOTIONS:
            for to_emotion in ALL_EMOTIONS:
                if from_emotion != to_emotion:
                    wav_path = transitions_dir / f"{from_emotion}_to_{to_emotion}.wav"
                    if wav_path.exists():
                        transitions_meta.append({
                            "file": f"transitions/{from_emotion}_to_{to_emotion}.wav",
                            "from_emotion": from_emotion,
                            "to_emotion": to_emotion,
                            "text": transition_text,
                            "instruct_text": get_transition_instruct(from_emotion, to_emotion),
                        })

        meta = {
            "emotions": emotions_meta,
            "transitions": transitions_meta,
        }

        zip_path = self._output_dir / f"emotion_refs_{uuid.uuid4().hex}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for emotion in ALL_EMOTIONS:
                wav_path = emotions_dir / f"{emotion}.wav"
                if wav_path.exists():
                    zf.write(wav_path, f"emotions/{emotion}.wav")

            for from_emotion in ALL_EMOTIONS:
                for to_emotion in ALL_EMOTIONS:
                    if from_emotion != to_emotion:
                        wav_path = transitions_dir / f"{from_emotion}_to_{to_emotion}.wav"
                        if wav_path.exists():
                            zf.write(wav_path, f"transitions/{from_emotion}_to_{to_emotion}.wav")

            zf.writestr("refs_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        logger.info(f"Packed emotion refs zip: {zip_path}")
        return zip_path

    @staticmethod
    def _safe_extract_zip(zf: zipfile.ZipFile, output_dir: Path):
        for member in zf.infolist():
            member_path = os.path.normpath(member.filename)
            if member_path.startswith("..") or os.path.isabs(member_path):
                raise ValueError(f"Unsafe path in zip: {member.filename}")
            zf.extract(member, output_dir)

    @staticmethod
    def import_from_zip(zip_path: str, output_dir: str) -> dict:
        zip_file = Path(zip_path)
        if not zip_file.exists():
            raise FileNotFoundError(f"Zip file not found: {zip_path}")

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            EmotionRefGenerator._safe_extract_zip(zf, out)

        meta_path = out / "refs_meta.json"
        if not meta_path.exists():
            raise FileNotFoundError("refs_meta.json not found in zip archive")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta: dict = json.load(f)

        logger.info(f"Imported emotion refs zip to: {output_dir}")
        return meta
