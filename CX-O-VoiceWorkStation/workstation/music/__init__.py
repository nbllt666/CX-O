"""
音乐核心包：歌谱模型、JSON Schema 校验与 MusicXML 导入

公共符号：
- 数据模型：NoteEvent / ChordEvent / Score
- 校验：SCORE_SCHEMA / validate_score
- 辅助：pitch_to_midi / total_beats
- MusicXML：musicxml_to_score / MusicXMLImportError
"""
from __future__ import annotations

from workstation.music.musicxml_import import MusicXMLImportError, musicxml_to_score
from workstation.music.score import (
    SCORE_SCHEMA,
    ChordEvent,
    NoteEvent,
    Score,
    pitch_to_midi,
    total_beats,
    validate_score,
)

__all__ = [
    "SCORE_SCHEMA",
    "ChordEvent",
    "MusicXMLImportError",
    "NoteEvent",
    "Score",
    "musicxml_to_score",
    "pitch_to_midi",
    "total_beats",
    "validate_score",
]
