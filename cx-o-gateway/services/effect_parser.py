"""
音效解析模块
解析文本中的音效标记，扫描音效文件
"""
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EFFECT_PATTERN = re.compile(r'（([^）]+)）')


class EffectParser:
    def __init__(self, effects_dir: str | Path | None = None):
        if effects_dir is None:
            self._effects_dir = Path(__file__).parent.parent / "data" / "effects"
        else:
            self._effects_dir = Path(effects_dir)
        
        self._available_effects: dict[str, str] = {}
        self._scan_effects()
    
    def _scan_effects(self) -> None:
        self._available_effects.clear()
        
        if not self._effects_dir.exists():
            logger.warning(f"音效目录不存在: {self._effects_dir}")
            return
        
        for wav_file in self._effects_dir.glob("*.wav"):
            effect_name = wav_file.stem
            self._available_effects[effect_name] = wav_file.name
            logger.debug(f"发现音效: {effect_name} -> {wav_file.name}")
        
        logger.info(f"扫描完成，共发现 {len(self._available_effects)} 个音效文件")
    
    def rescan_effects(self) -> None:
        self._scan_effects()
    
    def parse_text_with_effects(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        
        segments: list[dict[str, Any]] = []
        last_end = 0
        
        for match in EFFECT_PATTERN.finditer(text):
            start = match.start()
            end = match.end()
            effect_name = match.group(1).strip()
            
            if start > last_end:
                text_content = text[last_end:start]
                if text_content:
                    segments.append({
                        "type": "text",
                        "content": text_content
                    })
            
            if effect_name in self._available_effects:
                segments.append({
                    "type": "sound",
                    "name": effect_name,
                    "file": self._available_effects[effect_name]
                })
            else:
                segments.append({
                    "type": "text",
                    "content": match.group(0)
                })
                logger.debug(f"音效不存在，降级为文本: {effect_name}")
            
            last_end = end
        
        if last_end < len(text):
            remaining_text = text[last_end:]
            if remaining_text:
                segments.append({
                    "type": "text",
                    "content": remaining_text
                })
        
        return segments
    
    def get_available_effects(self) -> list[dict[str, str]]:
        return [
            {"name": name, "file": file_name}
            for name, file_name in self._available_effects.items()
        ]
    
    def has_effect(self, name: str) -> bool:
        return name in self._available_effects
    
    def get_effect_file(self, name: str) -> str | None:
        return self._available_effects.get(name)
    
    def get_effect_path(self, name: str) -> Path | None:
        if name not in self._available_effects:
            return None
        return self._effects_dir / self._available_effects[name]
    
    def generate_effect_prompt(self) -> str:
        if not self._available_effects:
            return ""
        
        effect_names = sorted(self._available_effects.keys())
        effect_list = "、".join(effect_names)
        
        prompt = (
            f"【可用音效】\n"
            f"在回复中可以使用以下音效标记来插入音效：{effect_list}\n"
            f"格式：（音效名）\n"
            f"示例：（{effect_names[0]}）\n"
            f"注意：请仅在合适场景使用音效，不要过度使用。"
        )
        
        return prompt
    
    @property
    def effects_dir(self) -> Path:
        return self._effects_dir
    
    @property
    def effect_count(self) -> int:
        return len(self._available_effects)
