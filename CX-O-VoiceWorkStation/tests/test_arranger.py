"""
模块1_自动编排器单测（arranger.py）

覆盖范围：
- resolve_style 三分支回退（非空原样 / 空+percussion / 空+melodic）
- 4 节奏型各生成典型用例（block_chords / arpeggio / root_eighth / rock_4beat）
  断言 events 数量、offset 升序、pitch 形状
- 空 chords 返回 []（静音轨，不报错）
- 打击乐轨 pitch 为 GM 鼓键名（resolve_drum_key 可解析）
- 旋律轨 pitch 为科学音高记谱（pitch_to_midi 可解析）
- 生成结果经 score.validate_score 校验通过（构造完整歌谱含生成的 events）
- applies_to 冲突抛 ValueError（rock_4beat 用于旋律轨 / block_chords 用于打击乐轨）
- 未知 style 抛 ValueError
- 幂等性（同输入同输出）
- 和弦解析覆盖大三/小三/属七/大七/减三/增三/升降根音
"""
from __future__ import annotations

from typing import Any

import pytest

from workstation.music.arranger import arrange_events, resolve_style
from workstation.music.inventory import resolve_drum_key
from workstation.music.score import pitch_to_midi, validate_score


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _chords(*pairs: tuple[str, float]) -> list[dict[str, Any]]:
    """构造和弦骨架 [{chord, beats}]"""
    return [{"chord": c, "beats": b} for c, b in pairs]


def _build_score_with_events(
    program: int,
    events: list[dict[str, Any]],
    track_id: str = "trk_0",
    name: str = "测试轨",
) -> dict:
    """构造含生成 events 的完整歌谱 v2（用于 validate_score 校验）"""
    return {
        "title": "编排测试歌",
        "bpm": 120,
        "time_signature": "4/4",
        "key": "C",
        "melody": [{"pitch": "C4", "beats": 1.0, "lyric": "测"}],
        "chords": [{"chord": "C", "beats": 4}],
        "accompaniment_tracks": [
            {
                "id": track_id,
                "name": name,
                "program": program,
                "mode": "manual",
                "style": "",
                "volume": 100,
                "pan": 64,
                "events": events,
            }
        ],
    }


# ---------------------------------------------------------------------------
# resolve_style
# ---------------------------------------------------------------------------


class TestResolveStyle:
    """resolve_style 三分支回退"""

    def test_nonempty_style_passthrough(self):
        """非空 style 原样返回（不论 program）"""
        assert resolve_style("arpeggio", 0) == "arpeggio"
        assert resolve_style("rock_4beat", -1) == "rock_4beat"
        assert resolve_style("block_chords", 5) == "block_chords"
        assert resolve_style("root_eighth", 32) == "root_eighth"

    def test_empty_style_percussion_fallback(self):
        """空 style + program=-1 → rock_4beat"""
        assert resolve_style("", -1) == "rock_4beat"

    def test_empty_style_melodic_fallback(self):
        """空 style + program>=0 → block_chords"""
        assert resolve_style("", 0) == "block_chords"
        assert resolve_style("", 127) == "block_chords"
        assert resolve_style("", 32) == "block_chords"


# ---------------------------------------------------------------------------
# arrange_events: 空 chords
# ---------------------------------------------------------------------------


class TestEmptyChords:
    """空 chords 返回 []（静音轨，不报错）"""

    def test_empty_chords_returns_empty_list(self):
        assert arrange_events([], "block_chords", 0) == []
        assert arrange_events([], "", -1) == []
        assert arrange_events([], "arpeggio", 5) == []
        assert arrange_events([], "root_eighth", 32) == []
        assert arrange_events([], "rock_4beat", -1) == []


# ---------------------------------------------------------------------------
# block_chords
# ---------------------------------------------------------------------------


class TestBlockChords:
    """block_chords（柱式和弦）：和弦全体音符齐发"""

    def test_single_chord_three_notes(self):
        """C 大三和弦 → C2/E2/G2 三个事件齐发 offset=0.0，beats=和弦 beats"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "block_chords", 0)
        assert len(events) == 3
        pitches = sorted(e["pitch"] for e in events)
        assert pitches == ["C2", "E2", "G2"]
        # 全部 offset=0.0（齐发）
        assert all(e["offset"] == 0.0 for e in events)
        # beats = 和弦 beats
        assert all(e["beats"] == 4.0 for e in events)
        # velocity 默认 64
        assert all(e["velocity"] == 64 for e in events)

    def test_multiple_chords_offset_ascending(self):
        """多和弦：offset 按和弦起点累加，升序排列"""
        chords = _chords(("C", 2.0), ("G", 2.0))
        events = arrange_events(chords, "block_chords", 0)
        offsets = [e["offset"] for e in events]
        assert offsets == sorted(offsets)
        # 第一和弦 offset=0.0，第二和弦 offset=2.0
        assert any(e["offset"] == 0.0 for e in events)
        assert any(e["offset"] == 2.0 for e in events)

    def test_minor_chord_intervals(self):
        """Am 小三和弦 → A2/C3/E3"""
        chords = _chords(("Am", 4.0))
        events = arrange_events(chords, "block_chords", 0)
        pitches = sorted(e["pitch"] for e in events)
        assert pitches == ["A2", "C3", "E3"]

    def test_dominant_seventh(self):
        """G7 属七 → G2/B2/D3/F3（4 个音）"""
        chords = _chords(("G7", 4.0))
        events = arrange_events(chords, "block_chords", 0)
        assert len(events) == 4
        pitches = sorted(e["pitch"] for e in events)
        assert pitches == ["B2", "D3", "F3", "G2"]

    def test_pitches_parseable_by_pitch_to_midi(self):
        """旋律轨 pitch 可经 pitch_to_midi 解析为合法 MIDI 音号"""
        chords = _chords(("Am", 4.0))
        events = arrange_events(chords, "block_chords", 0)
        for e in events:
            midi = pitch_to_midi(e["pitch"])
            assert isinstance(midi, int)
            assert midi > 0


# ---------------------------------------------------------------------------
# arpeggio
# ---------------------------------------------------------------------------


class TestArpeggio:
    """arpeggio（八分分解）：和弦音按八分音符依次琶音循环"""

    def test_eighth_notes_fill_chord_duration(self):
        """4 拍和弦 → 8 个八分音符（beats=0.5），offset 0.0→3.5"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "arpeggio", 0)
        assert len(events) == 8
        assert all(e["beats"] == 0.5 for e in events)
        offsets = [e["offset"] for e in events]
        assert offsets == sorted(offsets)
        assert offsets[0] == 0.0
        assert offsets[-1] == 3.5

    def test_arpeggio_cycles_chord_tones(self):
        """和弦音循环：C2 → E2 → G2 → C2 → E2 → G2 → C2 → E2"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "arpeggio", 0)
        pitches = [e["pitch"] for e in events]
        assert pitches[0:3] == ["C2", "E2", "G2"]
        assert pitches[3] == "C2"  # 循环回根音
        assert pitches[6] == "C2"  # 第二轮循环

    def test_offset_ascending_multiple_chords(self):
        """多和弦：offset 跨和弦累加升序"""
        chords = _chords(("C", 2.0), ("G", 2.0))
        events = arrange_events(chords, "arpeggio", 0)
        offsets = [e["offset"] for e in events]
        assert offsets == sorted(offsets)
        # 第一和弦最后一个 offset=1.5，第二和弦第一个 offset=2.0
        assert max(e["offset"] for e in events if e["offset"] < 2.0) == 1.5


# ---------------------------------------------------------------------------
# root_eighth
# ---------------------------------------------------------------------------


class TestRootEighth:
    """root_eighth（根音八分）：根音按八分音符重复，低八度铺底"""

    def test_root_note_repeated_eighth(self):
        """C 和弦 → 根音 C1 重复 8 次（4 拍 / 0.5）"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "root_eighth", 0)
        assert len(events) == 8
        pitches = [e["pitch"] for e in events]
        assert all(p == "C1" for p in pitches)
        assert all(e["beats"] == 0.5 for e in events)
        offsets = [e["offset"] for e in events]
        assert offsets == sorted(offsets)
        assert offsets[0] == 0.0
        assert offsets[-1] == 3.5

    def test_root_uses_bass_octave(self):
        """根音用低八度（C1 区，非 C2），对齐 inventory '低八度铺底'"""
        chords = _chords(("G", 4.0))
        events = arrange_events(chords, "root_eighth", 0)
        # G 和弦根音 = G1（低八度）
        assert all(e["pitch"] == "G1" for e in events)
        # G1 的 MIDI = (1+1)*12 + 7 = 31，低于 G2=43
        midi = pitch_to_midi(events[0]["pitch"])
        assert midi == 31

    def test_offset_ascending_multiple_chords(self):
        """多和弦：offset 跨和弦累加升序"""
        chords = _chords(("C", 2.0), ("Am", 2.0))
        events = arrange_events(chords, "root_eighth", 0)
        offsets = [e["offset"] for e in events]
        assert offsets == sorted(offsets)
        # 第二和弦根音 = A1
        second_chord_pitches = [e["pitch"] for e in events if e["offset"] >= 2.0]
        assert all(p == "A1" for p in second_chord_pitches)


# ---------------------------------------------------------------------------
# rock_4beat
# ---------------------------------------------------------------------------


class TestRock4Beat:
    """rock_4beat（鼓组四拍型，percussion 专用）"""

    def test_drum_pattern_4_beats(self):
        """4 拍和弦 → kick×2（1/3拍）+ snare×2（2/4拍）+ hihat×8（八分铺底）= 12 events"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "rock_4beat", -1)
        assert len(events) == 12
        kicks = [e for e in events if e["pitch"] == "kick"]
        snares = [e for e in events if e["pitch"] == "snare"]
        hihats = [e for e in events if e["pitch"] == "closed_hihat"]
        assert len(kicks) == 2
        assert len(snares) == 2
        assert len(hihats) == 8
        # kick 在 offset 0.0, 2.0
        kick_offsets = sorted(e["offset"] for e in kicks)
        assert kick_offsets == [0.0, 2.0]
        # snare 在 offset 1.0, 3.0
        snare_offsets = sorted(e["offset"] for e in snares)
        assert snare_offsets == [1.0, 3.0]
        # offset 升序
        offsets = [e["offset"] for e in events]
        assert offsets == sorted(offsets)

    def test_hihat_eighth_offsets(self):
        """closed_hihat 每 0.5 拍一击：offset 0.0/0.5/1.0/.../3.5"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "rock_4beat", -1)
        hihats = [e for e in events if e["pitch"] == "closed_hihat"]
        hihat_offsets = sorted(e["offset"] for e in hihats)
        assert hihat_offsets == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
        # 每个 hihat beats=0.5
        assert all(e["beats"] == 0.5 for e in hihats)

    def test_drum_pitch_is_valid_key_name(self):
        """打击乐轨 pitch 为合法 GM 鼓键名（resolve_drum_key 可解析）"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "rock_4beat", -1)
        for e in events:
            midi = resolve_drum_key(e["pitch"])
            assert isinstance(midi, int)
            assert 35 <= midi <= 81

    def test_velocity_default_64(self):
        """打击乐轨 velocity 默认 64"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "rock_4beat", -1)
        assert all(e["velocity"] == 64 for e in events)

    def test_cross_chord_continuity(self):
        """跨和弦边界鼓型连续：两个 2 拍和弦 → 全局 4 拍鼓型不中断"""
        chords = _chords(("C", 2.0), ("G", 2.0))
        events = arrange_events(chords, "rock_4beat", -1)
        # 全局 4 拍：kick 在 0.0/2.0，snare 在 1.0/3.0
        kicks = sorted(e["offset"] for e in events if e["pitch"] == "kick")
        snares = sorted(e["offset"] for e in events if e["pitch"] == "snare")
        assert kicks == [0.0, 2.0]
        assert snares == [1.0, 3.0]
        # 第二和弦起点 offset=2.0 应为 kick（全局第3拍，beat_idx=2 偶数）
        events_at_2 = [e for e in events if e["offset"] == 2.0]
        assert any(e["pitch"] == "kick" for e in events_at_2)


# ---------------------------------------------------------------------------
# applies_to 校验
# ---------------------------------------------------------------------------


class TestAppliesToValidation:
    """applies_to 冲突与未知 style 校验"""

    def test_rock_4beat_on_melodic_track_raises(self):
        """rock_4beat（percussion）用于旋律轨（program>=0）→ ValueError"""
        chords = _chords(("C", 4.0))
        with pytest.raises(ValueError, match="不适用于旋律轨"):
            arrange_events(chords, "rock_4beat", 0)

    def test_block_chords_on_percussion_track_raises(self):
        """block_chords（melodic）用于打击乐轨（program=-1）→ ValueError"""
        chords = _chords(("C", 4.0))
        with pytest.raises(ValueError, match="不适用于打击乐轨"):
            arrange_events(chords, "block_chords", -1)

    def test_arpeggio_on_percussion_track_raises(self):
        """arpeggio（melodic）用于打击乐轨 → ValueError"""
        chords = _chords(("C", 4.0))
        with pytest.raises(ValueError, match="不适用于打击乐轨"):
            arrange_events(chords, "arpeggio", -1)

    def test_unknown_style_raises(self):
        """未知 style → ValueError（附可用枚举）"""
        chords = _chords(("C", 4.0))
        with pytest.raises(ValueError, match="未知节奏型"):
            arrange_events(chords, "nonexistent_style", 0)


# ---------------------------------------------------------------------------
# 幂等性
# ---------------------------------------------------------------------------


class TestIdempotence:
    """确定性纯函数：同输入同输出"""

    def test_same_input_same_output(self):
        import copy
        chords = _chords(("C", 4.0), ("Am", 2.0), ("F", 2.0))
        r1 = arrange_events(chords, "arpeggio", 0)
        r2 = arrange_events(copy.deepcopy(chords), "arpeggio", 0)
        assert r1 == r2

    def test_input_not_mutated(self):
        """纯函数不污染入参"""
        chords = _chords(("C", 4.0))
        import copy
        snapshot = copy.deepcopy(chords)
        arrange_events(chords, "block_chords", 0)
        assert chords == snapshot


# ---------------------------------------------------------------------------
# 和弦解析覆盖
# ---------------------------------------------------------------------------


class TestChordParsing:
    """和弦标记解析覆盖各后缀与升降根音"""

    def test_major_triad(self):
        """C 大三 → C2/E2/G2"""
        events = arrange_events(_chords(("C", 1.0)), "block_chords", 0)
        assert sorted(e["pitch"] for e in events) == ["C2", "E2", "G2"]

    def test_minor_triad(self):
        """Am 小三 → A2/C3/E3"""
        events = arrange_events(_chords(("Am", 1.0)), "block_chords", 0)
        assert sorted(e["pitch"] for e in events) == ["A2", "C3", "E3"]

    def test_dominant_seventh(self):
        """G7 属七 → G2/B2/D3/F3"""
        events = arrange_events(_chords(("G7", 1.0)), "block_chords", 0)
        assert len(events) == 4
        assert set(e["pitch"] for e in events) == {"G2", "B2", "D3", "F3"}

    def test_major_seventh(self):
        """Fmaj7 大七 → F2/A2/C3/E3"""
        events = arrange_events(_chords(("Fmaj7", 1.0)), "block_chords", 0)
        assert len(events) == 4
        assert set(e["pitch"] for e in events) == {"F2", "A2", "C3", "E3"}

    def test_diminished(self):
        """Bdim 减三 → B2/D3/F3"""
        events = arrange_events(_chords(("Bdim", 1.0)), "block_chords", 0)
        assert len(events) == 3
        assert set(e["pitch"] for e in events) == {"B2", "D3", "F3"}

    def test_augmented(self):
        """Caug 增三 → C2/E2/G#2"""
        events = arrange_events(_chords(("Caug", 1.0)), "block_chords", 0)
        assert len(events) == 3
        assert set(e["pitch"] for e in events) == {"C2", "E2", "G#2"}

    def test_sharp_root(self):
        """C# 大三 → C#2/F2/G#2"""
        events = arrange_events(_chords(("C#", 1.0)), "block_chords", 0)
        assert set(e["pitch"] for e in events) == {"C#2", "F2", "G#2"}

    def test_flat_root(self):
        """Bb 大三 → A#2/D3/F3（b 等价 #）"""
        events = arrange_events(_chords(("Bb", 1.0)), "block_chords", 0)
        # Bb = A#，大三和弦 = Bb D F
        pitches = set(e["pitch"] for e in events)
        assert "A#2" in pitches or "Bb2" in pitches  # 实现用升号记谱


# ---------------------------------------------------------------------------
# validate_score 端到端
# ---------------------------------------------------------------------------


class TestValidateScoreIntegration:
    """生成结果经 score.validate_score 校验通过（构造完整歌谱含生成的 events）"""

    def test_block_chords_events_pass_validation(self):
        chords = _chords(("C", 4.0), ("G", 4.0))
        events = arrange_events(chords, "block_chords", 0)
        score = _build_score_with_events(0, events)
        ok, errors, normalized = validate_score(score)
        assert ok, f"校验失败: {errors}"
        assert normalized is not None

    def test_arpeggio_events_pass_validation(self):
        chords = _chords(("Am", 4.0))
        events = arrange_events(chords, "arpeggio", 0)
        score = _build_score_with_events(0, events)
        ok, errors, _ = validate_score(score)
        assert ok, f"校验失败: {errors}"

    def test_root_eighth_events_pass_validation(self):
        chords = _chords(("F", 4.0))
        events = arrange_events(chords, "root_eighth", 32)  # bass 轨 program=32
        score = _build_score_with_events(32, events)
        ok, errors, _ = validate_score(score)
        assert ok, f"校验失败: {errors}"

    def test_rock_4beat_events_pass_validation(self):
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "rock_4beat", -1)
        score = _build_score_with_events(-1, events)
        ok, errors, _ = validate_score(score)
        assert ok, f"校验失败: {errors}"

    def test_empty_style_fallback_passes_validation(self):
        """空 style + program=-1 → 回退 rock_4beat，校验通过"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "", -1)
        score = _build_score_with_events(-1, events)
        ok, errors, _ = validate_score(score)
        assert ok, f"校验失败: {errors}"
        # 应生成 rock_4beat 鼓击
        assert any(e["pitch"] == "kick" for e in events)

    def test_empty_style_melodic_fallback_passes_validation(self):
        """空 style + program>=0 → 回退 block_chords，校验通过"""
        chords = _chords(("C", 4.0))
        events = arrange_events(chords, "", 0)
        score = _build_score_with_events(0, events)
        ok, errors, _ = validate_score(score)
        assert ok, f"校验失败: {errors}"
        # 应生成柱式和弦音
        assert any(e["pitch"] == "C2" for e in events)

    def test_multi_track_score_passes_validation(self):
        """多轨歌谱（旋律轨 + 鼓轨）校验通过"""
        chords = _chords(("C", 4.0), ("Am", 4.0))
        melodic_events = arrange_events(chords, "arpeggio", 0)
        drum_events = arrange_events(chords, "rock_4beat", -1)
        score = {
            "title": "多轨测试歌",
            "bpm": 120,
            "time_signature": "4/4",
            "key": "C",
            "melody": [{"pitch": "C4", "beats": 1.0, "lyric": "测"}],
            "chords": chords,
            "accompaniment_tracks": [
                {
                    "id": "trk_piano",
                    "name": "钢琴",
                    "program": 0,
                    "mode": "manual",
                    "style": "arpeggio",
                    "volume": 100,
                    "pan": 64,
                    "events": melodic_events,
                },
                {
                    "id": "trk_drums",
                    "name": "鼓组",
                    "program": -1,
                    "mode": "manual",
                    "style": "rock_4beat",
                    "volume": 100,
                    "pan": 64,
                    "events": drum_events,
                },
            ],
        }
        ok, errors, _ = validate_score(score)
        assert ok, f"多轨校验失败: {errors}"
