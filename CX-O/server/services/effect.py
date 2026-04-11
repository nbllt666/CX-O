import os
import re
from pathlib import Path
from typing import Any, Optional

EFFECT_PATTERN = re.compile(r"\[(sound:\s*(\w+))\](.*?)\[/sound\]", re.IGNORECASE | re.DOTALL)


class EffectParser:
    def __init__(self, effects_dir: Optional[str] = None):
        if effects_dir is None:
            effects_dir = Path(__file__).parent.parent / "data" / "effects"
        self.effects_dir = Path(effects_dir)
        self._effects_cache: Optional[list[str]] = None

    def get_available_effects(self) -> list[dict[str, Any]]:
        if self._effects_cache is not None:
            return [{"id": e, "name": e} for e in self._effects_cache]

        effects = []
        if self.effects_dir.exists():
            for file in self.effects_dir.iterdir():
                if file.is_file() and file.suffix.lower() in [".wav", ".mp3", ".ogg"]:
                    effect_id = file.stem
                    effects.append({
                        "id": effect_id,
                        "name": effect_id,
                        "file": str(file)
                    })

        self._effects_cache = [e["id"] for e in effects]
        return effects

    def get_effect_path(self, effect_name: str) -> Optional[Path]:
        effect_name_lower = effect_name.lower()

        for ext in [".wav", ".mp3", ".ogg"]:
            effect_path = self.effects_dir / f"{effect_name_lower}{ext}"
            if effect_path.exists():
                return effect_path

        return None

    def parse_text_with_effects(self, text: str) -> list[dict[str, Any]]:
        result = []

        last_end = 0
        for match in EFFECT_PATTERN.finditer(text):
            start, end = match.span()

            if start > last_end:
                text_content = text[last_end:start].strip()
                if text_content:
                    result.append({"type": "text", "content": text_content})

            full_match, sound_name, content = match.groups()
            result.append({
                "type": "sound",
                "name": sound_name.lower().strip(),
                "content": content.strip() if content else ""
            })

            last_end = end

        if last_end < len(text):
            remaining_text = text[last_end:].strip()
            if remaining_text:
                result.append({"type": "text", "content": remaining_text})

        return result
