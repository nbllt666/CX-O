"""
歌谱核心测试（歌谱 v2）：模型校验、v1→v2 迁移、OBS-3 边界、
多轨追加校验、音高换算、节拍合计与 MusicXML 导入
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from workstation.music import (
    SCORE_SCHEMA,
    SCORE_SCHEMA_V2,
    ChordEvent,
    MusicXMLImportError,
    NoteEvent,
    Score,
    migrate_v1_to_v2,
    musicxml_to_score,
    pitch_to_midi,
    total_beats,
    validate_score,
)

# 冻结契约路径（防漂移比对用）：逐层 dirname 定位 CX-O 根，禁止相对路径字符串
_CONTRACTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".trae", "specs", "redesign-composition-staff-editor", "contracts",
)


def _valid_score() -> dict:
    """构造一份合法歌谱 v2 裸 dict（仅必填字段 + chords；OBS-3：无 accompaniment_style）"""
    return {
        "title": "测试歌",
        "bpm": 120,
        "melody": [
            {"pitch": "C4", "beats": 1.0, "lyric": "你"},
            {"pitch": "A#3", "beats": 0.5, "lyric": ""},
            {"pitch": "Bb5", "beats": 2.0, "lyric": "好"},
        ],
        "chords": [{"chord": "C", "beats": 4}],
    }


def _v1_score(style: str = "piano") -> dict:
    """构造一份 v1 歌谱（含 accompaniment_style，触发迁移）"""
    data = _valid_score()
    data["accompaniment_style"] = style
    return data


class TestSchemaConstant:
    """SCORE_SCHEMA_V2 内嵌常量与冻结契约的防漂移比对"""

    def test_schema_v2_equals_frozen_contract(self):
        with open(os.path.join(_CONTRACTS_DIR, "score-v2.schema.json"), "r", encoding="utf-8") as fp:
            frozen = json.load(fp)
        assert SCORE_SCHEMA_V2 == frozen

    def test_backward_compat_alias(self):
        """SCORE_SCHEMA 为 SCORE_SCHEMA_V2 的向后兼容别名（cxfc_plugin 经别名发布 v2 参数面）"""
        assert SCORE_SCHEMA is SCORE_SCHEMA_V2


class TestValidateScore:
    """歌谱 v2 JSON Schema 校验用例"""

    def test_valid_score_passes_and_normalized(self):
        ok, errors, normalized = validate_score(_valid_score())
        assert ok is True
        assert errors == []
        assert normalized is not None
        # 规范化：默认值被填充
        assert normalized["time_signature"] == "4/4"
        assert normalized["key"] == "C"
        assert normalized["melody"][1]["lyric"] == ""
        assert normalized["chords"] == [{"chord": "C", "beats": 4}]

    def test_explicit_fields_preserved(self):
        data = _valid_score()
        data.update({"time_signature": "3/4", "key": "G"})
        ok, _, normalized = validate_score(data)
        assert ok is True
        assert normalized["time_signature"] == "3/4"
        assert normalized["key"] == "G"

    def test_obs3_bare_v1_dict_not_migrated(self):
        """OBS-3 边界锚定：v1 裸 dict 缺 accompaniment_style 不触发迁移，
        按 v2 校验后 accompaniment_tracks 落默认 []（v1 行为是填充 style=piano）"""
        ok, errors, normalized = validate_score(_valid_score())
        assert ok is True
        assert errors == []
        assert "accompaniment_style" not in normalized
        assert normalized["accompaniment_tracks"] == []

    def test_empty_chords_allowed(self):
        data = _valid_score()
        data["chords"] = []
        ok, errors, normalized = validate_score(data)
        assert ok is True
        assert errors == []
        assert normalized["chords"] == []

    def test_missing_bpm(self):
        data = _valid_score()
        del data["bpm"]
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("bpm" in e for e in errors)

    def test_bpm_not_positive(self):
        data = _valid_score()
        data["bpm"] = 0
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("bpm" in e for e in errors)

    def test_melody_beats_not_positive(self):
        data = _valid_score()
        data["melody"][0]["beats"] = 0
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("melody[0].beats" in e for e in errors)

    def test_chord_beats_not_positive(self):
        data = _valid_score()
        data["chords"][0]["beats"] = -1
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("chords[0].beats" in e for e in errors)

    def test_invalid_pitch(self):
        data = _valid_score()
        data["melody"][1]["pitch"] = "H2"
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("melody[1].pitch" in e for e in errors)

    def test_melody_not_array(self):
        data = _valid_score()
        data["melody"] = "not-an-array"
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("melody" in e for e in errors)

    def test_non_dict_rejected(self):
        ok, errors, normalized = validate_score([1, 2, 3])
        assert ok is False
        assert errors
        assert normalized is None

    def test_v2_rejects_legacy_field_when_tracks_present(self):
        """v2 additionalProperties=false：accompaniment_tracks 存在时
        accompaniment_style 属旧字段残留，结构校验拒绝"""
        data = _valid_score()
        data["accompaniment_tracks"] = [
            {"id": "trk_0", "name": "钢琴", "program": 0, "mode": "auto"}
        ]
        data["accompaniment_style"] = "piano"
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("accompaniment_style" in e for e in errors)


class TestMigrateV1ToV2:
    """v1 → v2 迁移用例（score-v2.schema.json x-migration）"""

    def test_piano_style_maps_to_block_chords(self):
        migrated = migrate_v1_to_v2(_v1_score("piano"))
        assert "accompaniment_style" not in migrated
        assert migrated["accompaniment_tracks"] == [
            {
                "id": "trk_0",
                "name": "钢琴",
                "program": 0,
                "mode": "auto",
                "style": "block_chords",
                "volume": 100,
                "pan": 64,
                "events": [],
            }
        ]

    @pytest.mark.parametrize("style", ["guitar", "strings", "arpeggio", "rock_4beat", ""])
    def test_other_styles_preserved_verbatim(self, style):
        """piano 之外的 accompaniment_style 原样保留为轨 style"""
        migrated = migrate_v1_to_v2(_v1_score(style))
        assert migrated["accompaniment_tracks"][0]["style"] == style

    def test_chords_and_melody_preserved(self):
        data = _v1_score("piano")
        migrated = migrate_v1_to_v2(data)
        assert migrated["chords"] == data["chords"]
        assert migrated["melody"] == data["melody"]
        assert migrated["title"] == data["title"]
        assert migrated["bpm"] == data["bpm"]

    def test_idempotent_on_v2_input(self):
        """v2 输入（含 accompaniment_tracks）原样深拷贝返回，不触发迁移"""
        v2 = _valid_score()
        v2["accompaniment_tracks"] = [
            {"id": "trk_x", "name": "贝斯", "program": 33, "mode": "manual"}
        ]
        migrated = migrate_v1_to_v2(v2)
        assert migrated == v2
        assert migrated is not v2  # 深拷贝

    def test_obs3_bare_dict_passes_through(self):
        """OBS-3：缺 accompaniment_style 的裸 dict 不触发迁移（也不补轨）"""
        bare = _valid_score()
        migrated = migrate_v1_to_v2(bare)
        assert "accompaniment_tracks" not in migrated
        assert "accompaniment_style" not in migrated

    def test_does_not_pollute_input(self):
        data = _v1_score("piano")
        snapshot = copy.deepcopy(data)
        migrate_v1_to_v2(data)
        assert data == snapshot  # 入参不被修改

    def test_validate_score_migrates_v1(self):
        """validate_score 前置迁移：v1 输入校验通过且输出为 v2 形状"""
        ok, errors, normalized = validate_score(_v1_score("piano"))
        assert ok is True
        assert errors == []
        assert "accompaniment_style" not in normalized
        assert normalized["accompaniment_tracks"][0]["style"] == "block_chords"
        # 迁移产物再次校验幂等
        ok2, _, normalized2 = validate_score(normalized)
        assert ok2 is True
        assert normalized2 == normalized


class TestAccompanimentTracksValidation:
    """多轨追加校验用例（结构校验之后的 ①音高 ②轨 id 唯一 ③鼓键名）"""

    def _score_with_tracks(self, tracks: list[dict]) -> dict:
        data = _valid_score()
        data["accompaniment_tracks"] = tracks
        return data

    def test_track_defaults_filled(self):
        data = self._score_with_tracks(
            [{"id": "trk_0", "name": "钢琴", "program": 0, "mode": "auto"}]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is True
        track = normalized["accompaniment_tracks"][0]
        assert track["style"] == ""
        assert track["volume"] == 100
        assert track["pan"] == 64
        assert track["events"] == []

    def test_duplicate_track_id_rejected(self):
        data = self._score_with_tracks(
            [
                {"id": "trk_0", "name": "钢琴", "program": 0, "mode": "auto"},
                {"id": "trk_0", "name": "贝斯", "program": 33, "mode": "manual"},
            ]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("accompaniment_tracks[1].id" in e and "trk_0" in e for e in errors)

    def test_manual_track_events_valid(self):
        """manual 轨合法 events（含 velocity 边界 1 与 127）通过"""
        data = self._score_with_tracks(
            [
                {
                    "id": "trk_bass",
                    "name": "贝斯",
                    "program": 33,
                    "mode": "manual",
                    "events": [
                        {"pitch": "C2", "beats": 0.5, "offset": 0.0, "velocity": 1},
                        {"pitch": "G2", "beats": 1.0, "offset": 0.5, "velocity": 127},
                    ],
                }
            ]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is True
        assert errors == []
        events = normalized["accompaniment_tracks"][0]["events"]
        assert events[0]["velocity"] == 1
        # velocity 缺省填充默认 64
        assert normalized["accompaniment_tracks"][0]["events"][0]["offset"] == 0.0

    def test_manual_track_event_velocity_default(self):
        data = self._score_with_tracks(
            [
                {
                    "id": "trk_bass",
                    "name": "贝斯",
                    "program": 33,
                    "mode": "manual",
                    "events": [{"pitch": "C2", "beats": 1.0, "offset": 0.0}],
                }
            ]
        )
        ok, _, normalized = validate_score(data)
        assert ok is True
        assert normalized["accompaniment_tracks"][0]["events"][0]["velocity"] == 64

    @pytest.mark.parametrize(
        "event, fragment",
        [
            ({"pitch": "H9", "beats": 1.0, "offset": 0.0}, "events[0].pitch"),
            ({"pitch": "C2", "beats": 0, "offset": 0.0}, "events[0].beats"),
            ({"pitch": "C2", "beats": 1.0, "offset": -1.0}, "events[0].offset"),
            ({"pitch": "C2", "beats": 1.0, "offset": 0.0, "velocity": 0}, "events[0].velocity"),
            ({"pitch": "C2", "beats": 1.0, "offset": 0.0, "velocity": 128}, "events[0].velocity"),
        ],
    )
    def test_manual_track_event_field_errors(self, event, fragment):
        data = self._score_with_tracks(
            [
                {
                    "id": "trk_bass",
                    "name": "贝斯",
                    "program": 33,
                    "mode": "manual",
                    "events": [event],
                }
            ]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any(fragment in e for e in errors)

    def test_drum_track_valid_drum_keys(self):
        """打击乐轨合法鼓键名（含别名 bd）通过"""
        data = self._score_with_tracks(
            [
                {
                    "id": "trk_drum",
                    "name": "鼓组",
                    "program": -1,
                    "mode": "manual",
                    "events": [
                        {"pitch": "kick", "beats": 0.5, "offset": 0.0},
                        {"pitch": "snare", "beats": 0.5, "offset": 1.0},
                        {"pitch": "bd", "beats": 0.5, "offset": 2.0},
                    ],
                }
            ]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is True
        assert errors == []

    def test_drum_track_invalid_drum_key_rejected(self):
        """打击乐轨 events.pitch 用科学音高记谱（非鼓键名）报错，含字段定位"""
        data = self._score_with_tracks(
            [
                {
                    "id": "trk_drum",
                    "name": "鼓组",
                    "program": -1,
                    "mode": "manual",
                    "events": [{"pitch": "C4", "beats": 1.0, "offset": 0.0}],
                }
            ]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert normalized is None
        assert any("accompaniment_tracks[0].events[0].pitch" in e for e in errors)

    def test_melodic_track_rejects_drum_key_pitch(self):
        """program≥0 轨 events.pitch 用鼓键名（非科学音高记谱）报错"""
        data = self._score_with_tracks(
            [
                {
                    "id": "trk_piano",
                    "name": "钢琴",
                    "program": 0,
                    "mode": "manual",
                    "events": [{"pitch": "kick", "beats": 1.0, "offset": 0.0}],
                }
            ]
        )
        ok, errors, normalized = validate_score(data)
        assert ok is False
        assert any("accompaniment_tracks[0].events[0].pitch" in e for e in errors)

    def test_track_structural_errors(self):
        """轨结构反例：缺 mode / program 越界 / id 非法字符 / 未知字段"""
        base = {"id": "trk_0", "name": "钢琴", "program": 0, "mode": "auto"}
        for bad_track, fragment in [
            ({"id": "trk_0", "name": "钢琴", "program": 0}, "mode"),
            ({"id": "trk_0", "name": "钢琴", "program": 128, "mode": "auto"}, "program"),
            ({"id": "trk_0", "name": "钢琴", "program": -2, "mode": "auto"}, "program"),
            ({"id": "Trk-0", "name": "钢琴", "program": 0, "mode": "auto"}, "id"),
            ({**base, "unknown_field": 1}, "unknown_field"),
        ]:
            data = self._score_with_tracks([bad_track])
            ok, errors, _ = validate_score(data)
            assert ok is False, f"应拒绝: {bad_track}"
            assert any(fragment in e for e in errors), (fragment, errors)


class TestPitchToMidi:
    """音高换算用例（约定 C4=60）"""

    def test_known_pitches(self):
        assert pitch_to_midi("C4") == 60
        assert pitch_to_midi("A4") == 69
        assert pitch_to_midi("Bb3") == 58
        assert pitch_to_midi("A#3") == 58  # 与 Bb3 等音

    def test_invalid_pitch_raises(self):
        for bad in ("H2", "", "C", "C#", "10", "do4"):
            with pytest.raises(ValueError):
                pitch_to_midi(bad)


class TestTotalBeats:
    """总节拍计算用例"""

    def test_total_beats(self):
        ok, _, normalized = validate_score(_valid_score())
        assert ok is True
        assert total_beats(normalized) == pytest.approx(3.5)


class TestScoreDataclass:
    """dataclass 模型与 dict 互转（v2）"""

    def test_from_dict_round_trip(self):
        ok, _, normalized = validate_score(_valid_score())
        assert ok is True
        score = Score.from_dict(normalized)
        assert score.title == "测试歌"
        assert score.melody[0] == NoteEvent(pitch="C4", beats=1.0, lyric="你")
        assert score.chords[0] == ChordEvent(chord="C", beats=4)
        assert score.accompaniment_tracks == []
        # 回转 dict 后仍通过校验（v2 形状）
        exported = score.to_dict()
        assert "accompaniment_style" not in exported
        ok2, errors2, _ = validate_score(exported)
        assert ok2 is True
        assert errors2 == []

    def test_from_dict_accepts_v1_input(self):
        """from_dict 兼容 v1 输入：内部先迁移再构造；to_dict 输出 v2"""
        score = Score.from_dict(_v1_score("piano"))
        assert len(score.accompaniment_tracks) == 1
        track = score.accompaniment_tracks[0]
        assert track.id == "trk_0"
        assert track.mode == "auto"
        assert track.style == "block_chords"
        exported = score.to_dict()
        assert "accompaniment_style" not in exported
        ok, errors, _ = validate_score(exported)
        assert ok is True, errors

    def test_track_events_round_trip(self):
        data = _valid_score()
        data["accompaniment_tracks"] = [
            {
                "id": "trk_bass",
                "name": "贝斯",
                "program": 33,
                "mode": "manual",
                "events": [{"pitch": "C2", "beats": 2.0, "offset": 0.0, "velocity": 80}],
            }
        ]
        ok, _, normalized = validate_score(data)
        assert ok is True
        score = Score.from_dict(normalized)
        event = score.accompaniment_tracks[0].events[0]
        assert event.pitch == "C2"
        assert event.velocity == 80
        ok2, errors2, _ = validate_score(score.to_dict())
        assert ok2 is True, errors2


def _make_minimal_musicxml(tmp_path: Path) -> bytes:
    """用 music21 现场生成最小 MusicXML（BPM/拍号/调号/和声标记/三音符旋律/逐字歌词）"""
    from music21 import harmony, key, metadata, meter, note, stream, tempo

    score = stream.Score()
    score.insert(0, metadata.Metadata(title="测试歌"))
    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=100))
    part.insert(0, meter.TimeSignature("4/4"))
    part.insert(0, key.KeySignature(0))  # C 大调
    part.insert(0, harmony.ChordSymbol("C", quarterLength=4))

    n1 = note.Note("C4", quarterLength=1.0)
    n1.lyric = "你"
    n2 = note.Note("D4", quarterLength=1.0)
    n2.lyric = "好"
    n3 = note.Note("E4", quarterLength=2.0)
    part.append([n1, n2, n3])
    score.insert(0, part)

    out_path = tmp_path / "minimal.musicxml"
    written = score.write("musicxml", fp=str(out_path))
    return Path(written).read_bytes()


class TestMusicXMLImport:
    """MusicXML 导入用例"""

    def test_convert_generated_musicxml(self, tmp_path):
        xml_bytes = _make_minimal_musicxml(tmp_path)
        score = musicxml_to_score(xml_bytes)

        assert score["title"] == "测试歌"
        assert score["bpm"] == 100
        assert score["time_signature"] == "4/4"
        assert score["key"] == "C"
        assert len(score["melody"]) == 3
        assert score["melody"][0] == {"pitch": "C4", "beats": 1.0, "lyric": "你"}
        assert score["melody"][1]["lyric"] == "好"
        assert score["melody"][2]["beats"] == 2.0
        assert len(score["chords"]) == 1
        assert "C" in score["chords"][0]["chord"]
        assert score["chords"][0]["beats"] > 0
        # 转换产物必须能通过歌谱校验（MusicXML 产物为 OBS-3 裸 dict → v2 tracks=[]）
        ok, errors, normalized = validate_score(score)
        assert ok is True, errors
        assert normalized["accompaniment_tracks"] == []

    def test_default_bpm_when_no_metronome_mark(self, tmp_path):
        """无 MetronomeMark 时 BPM 缺省 120"""
        from music21 import note, stream

        score = stream.Score()
        part = stream.Part()
        part.append(note.Note("C4", quarterLength=1.0))
        score.insert(0, part)
        out_path = tmp_path / "no_tempo.musicxml"
        written = score.write("musicxml", fp=str(out_path))
        result = musicxml_to_score(Path(written).read_bytes())
        assert result["bpm"] == 120

    def test_corrupted_xml_raises(self):
        with pytest.raises(MusicXMLImportError) as exc_info:
            musicxml_to_score(b"<score-partwise><broken")
        assert str(exc_info.value)

    def test_garbage_bytes_raise(self):
        with pytest.raises(MusicXMLImportError):
            musicxml_to_score(b"this is not xml at all")

    def test_empty_bytes_raise(self):
        with pytest.raises(MusicXMLImportError):
            musicxml_to_score(b"")
