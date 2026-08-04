"""
音效解析器
解析文本中的音效标记 [effect:name] 并替换为音效数据
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EFFECT_PATTERN = re.compile(r'\[effect:([^\]]+)\]')


class EffectParser:
    def __init__(self, effects_dir: str | None = None):
        self._effects_dir = Path(effects_dir) if effects_dir else None
        self._effects_cache: dict[str, bytes] = {}

    def _load_effect(self, effect_name: str) -> bytes | None:
        if effect_name in self._effects_cache:
            return self._effects_cache[effect_name]

        if not self._effects_dir or not self._effects_dir.exists():
            logger.warning(f"Effects directory not found: {self._effects_dir}")
            return None

        for ext in ['.wav', '.mp3', '.ogg', '.flac']:
            effect_path = self._effects_dir / f"{effect_name}{ext}"
            if effect_path.exists():
                try:
                    data = effect_path.read_bytes()
                    self._effects_cache[effect_name] = data
                    logger.debug(f"Loaded effect: {effect_name}")
                    return data
                except Exception as e:
                    logger.error(f"Failed to load effect {effect_name}: {e}")

        logger.warning(f"Effect not found: {effect_name}")
        return None

    def parse_text_with_effects(self, text: str) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        last_end = 0

        for match in EFFECT_PATTERN.finditer(text):
            if match.start() > last_end:
                text_before = text[last_end:match.start()].strip()
                if text_before:
                    segments.append({
                        "type": "text",
                        "content": text_before
                    })

            effect_name = match.group(1)
            effect_data = self._load_effect(effect_name)

            segments.append({
                "type": "effect",
                "name": effect_name,
                "data": effect_data
            })

            last_end = match.end()

        if last_end < len(text):
            remaining_text = text[last_end:].strip()
            if remaining_text:
                segments.append({
                    "type": "text",
                    "content": remaining_text
                })

        return segments

    def get_available_effects(self) -> list[str]:
        if not self._effects_dir or not self._effects_dir.exists():
            return []

        effects = []
        for f in self._effects_dir.iterdir():
            if f.is_file() and f.suffix.lower() in ['.wav', '.mp3', '.ogg', '.flac']:
                effects.append(f.stem)

        return sorted(effects)

    def clear_cache(self):
        self._effects_cache.clear()
