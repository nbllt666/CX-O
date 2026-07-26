"""
音乐核心包：歌谱模型（v2）、JSON Schema 校验、枚举清单与 MusicXML 导入

公共符号：
- 数据模型：NoteEvent / ChordEvent / TrackNoteEvent / AccompanimentTrack / Score
- 校验：SCORE_SCHEMA_V2 / SCORE_SCHEMA（=V2 别名）/ validate_score / migrate_v1_to_v2
- 辅助：pitch_to_midi / total_beats
- 枚举清单：inventory 子模块（get_inventory / get_style / resolve_drum_key / INVENTORY）
- MusicXML：musicxml_to_score / MusicXMLImportError
"""
from __future__ import annotations

from workstation.music.musicxml_import import MusicXMLImportError, musicxml_to_score
from workstation.music.score import (
    SCORE_SCHEMA,
    SCORE_SCHEMA_V2,
    AccompanimentTrack,
    ChordEvent,
    NoteEvent,
    Score,
    TrackNoteEvent,
    migrate_v1_to_v2,
    pitch_to_midi,
    total_beats,
    validate_score,
)

__all__ = [
    "SCORE_SCHEMA",
    "SCORE_SCHEMA_V2",
    "AccompanimentTrack",
    "ChordEvent",
    "MusicXMLImportError",
    "NoteEvent",
    "Score",
    "TrackNoteEvent",
    "migrate_v1_to_v2",
    "musicxml_to_score",
    "pitch_to_midi",
    "total_beats",
    "validate_score",
]
