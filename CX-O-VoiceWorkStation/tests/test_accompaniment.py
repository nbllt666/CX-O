"""
模块2_多轨渲染管线单元测试（SMF format 1 字节级 + 通道分配 + auto 物化 + fluidsynth mock）

覆盖（对齐 merged.md §7 渲染管线冻结项 + voicews_music.pyi 模块5 签名）：
- SMF format 1 header：MThd（format=1, ntrks=轨数, division=480）、MTrk 块结构
- 轨 0 元轨：tempo meta(FF51) + 拍号 meta(FF58) + EOT(FF2F)，无音符
- 通道分配：旋律轨按序跳 9、打击乐轨固定 9、program change + CC7 + CC10 直写
- 多轨场景：2 旋律轨 + 1 鼓轨的 SMF 编码
- auto 轨物化（真实调用 arranger.arrange_events）
- pitch_to_midi / resolve_drum_key 集成
- offset/beats → tick 换算正确性
- fluidsynth 渲染（mock CLI 调用验证参数顺序与临时 .mid 处理）
- 空歌谱（无伴奏轨）的边界行为
- 依赖缺失逐项报错
"""
from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import workstation.music.accompaniment as accompaniment_module  # noqa: E402
from workstation.music.accompaniment import (  # noqa: E402
    AccompanimentError,
    check_render_dependencies,
    render_accompaniment,
    score_to_midi_bytes,
)
from workstation.music.arranger import arrange_events  # noqa: E402
from workstation.music.score import pitch_to_midi  # noqa: E402
from workstation.music.inventory import resolve_drum_key  # noqa: E402

# ---------------------------------------------------------------------------
# 测试歌谱（v2 规范化形态，含 accompaniment_tracks）
# ---------------------------------------------------------------------------


def _score_v2(**overrides) -> dict:
    """2 旋律轨 + 1 鼓轨的 v2 歌谱（manual 模式，事件确定性）"""
    score = {
        "title": "多轨测试",
        "bpm": 120,
        "time_signature": "4/4",
        "key": "C",
        "melody": [{"pitch": "C4", "beats": 4, "lyric": "测"}],
        "chords": [{"chord": "C", "beats": 4}],
        "accompaniment_tracks": [
            {
                "id": "trk_piano",
                "name": "钢琴",
                "program": 0,
                "mode": "manual",
                "style": "",
                "volume": 100,
                "pan": 64,
                "events": [
                    {"pitch": "C2", "beats": 4, "offset": 0, "velocity": 80}
                ],
            },
            {
                "id": "trk_bass",
                "name": "贝斯",
                "program": 33,
                "mode": "manual",
                "style": "",
                "volume": 110,
                "pan": 56,
                "events": [
                    {"pitch": "C2", "beats": 2, "offset": 0},
                    {"pitch": "G2", "beats": 2, "offset": 2, "velocity": 80},
                ],
            },
            {
                "id": "trk_drum",
                "name": "鼓组",
                "program": -1,
                "mode": "manual",
                "style": "",
                "volume": 120,
                "pan": 64,
                "events": [
                    {"pitch": "kick", "beats": 1, "offset": 0},
                    {"pitch": "snare", "beats": 1, "offset": 1},
                ],
            },
        ],
    }
    score.update(overrides)
    return score


def _score_empty_tracks(**overrides) -> dict:
    """无伴奏轨的空歌谱（纯主旋律）"""
    score = {
        "title": "空伴奏测试",
        "bpm": 96,
        "time_signature": "3/4",
        "key": "C",
        "melody": [{"pitch": "C4", "beats": 3, "lyric": ""}],
        "chords": [],
        "accompaniment_tracks": [],
    }
    score.update(overrides)
    return score


# ---------------------------------------------------------------------------
# SMF 解析辅助（字节级断言用）
# ---------------------------------------------------------------------------


def _decode_vlq(data: bytes, pos: int) -> tuple[int, int]:
    """解码 MIDI 变长数值，返回 (value, next_pos)"""
    value = 0
    while pos < len(data):
        byte = data[pos]
        value = (value << 7) | (byte & 0x7F)
        pos += 1
        if not (byte & 0x80):
            break
    return value, pos


def _parse_mthd(data: bytes) -> tuple[int, int, int]:
    """解析 MThd → (format, ntrks, division)"""
    assert data[:4] == b"MThd", "SMF 必须以 MThd 开头"
    header_len = int.from_bytes(data[4:8], "big")
    assert header_len == 6, f"MThd header 长度必须为 6，实际 {header_len}"
    fmt = int.from_bytes(data[8:10], "big")
    ntrks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    return fmt, ntrks, division


def _parse_mtrk_blocks(data: bytes) -> list[bytes]:
    """解析所有 MTrk 块，返回各轨数据字节列表（不含 MTrk 头与长度字段）"""
    blocks: list[bytes] = []
    pos = 14  # 跳过 MThd
    while pos + 8 <= len(data):
        tag = data[pos : pos + 4]
        assert tag == b"MTrk", f"期望 MTrk，实际 {tag!r} @ offset {pos}"
        track_len = int.from_bytes(data[pos + 4 : pos + 8], "big")
        track_data = data[pos + 8 : pos + 8 + track_len]
        assert len(track_data) == track_len, "MTrk 长度字段与实际数据不符"
        blocks.append(track_data)
        pos += 8 + track_len
    assert pos == len(data), f"SMF 尾部有未解析字节: {pos} != {len(data)}"
    return blocks


def _parse_track_events(track_data: bytes) -> list[tuple]:
    """解析单轨事件 → [(delta, status, *data_bytes), ...]

    meta 事件: (delta, 0xFF, meta_type, data_bytes)
    program change: (delta, 0xCn, program)
    CC: (delta, 0xBn, cc_num, value)
    Note On: (delta, 0x9n, pitch, velocity)
    Note Off: (delta, 0x8n, pitch, 0)
    """
    events: list[tuple] = []
    pos = 0
    while pos < len(track_data):
        delta, pos = _decode_vlq(track_data, pos)
        status = track_data[pos]
        nibble = status & 0xF0
        if status == 0xFF:  # meta event
            meta_type = track_data[pos + 1]
            length, meta_pos = _decode_vlq(track_data, pos + 2)
            meta_data = track_data[meta_pos : meta_pos + length]
            events.append((delta, status, meta_type, meta_data))
            pos = meta_pos + length
        elif nibble in (0x80, 0x90, 0xA0, 0xB0, 0xE0):  # 2 data bytes
            events.append((delta, status, track_data[pos + 1], track_data[pos + 2]))
            pos += 3
        elif nibble in (0xC0, 0xD0):  # 1 data byte
            events.append((delta, status, track_data[pos + 1]))
            pos += 2
        else:
            raise AssertionError(f"未支持的 status 字节: 0x{status:02X} @ pos {pos}")
    return events


# ---------------------------------------------------------------------------
# SMF format 1 header 与块结构
# ---------------------------------------------------------------------------


class TestSmfHeader:
    def test_format1_header_with_tracks(self):
        """有伴奏轨：format=1, ntrks=1+3=4, division=480"""
        data = score_to_midi_bytes(_score_v2())
        fmt, ntrks, division = _parse_mthd(data)
        assert fmt == 1
        assert ntrks == 4  # 1 元轨 + 3 乐器轨
        assert division == 480

    def test_format1_header_empty_tracks(self):
        """无伴奏轨：format=1, ntrks=1（仅元轨）"""
        data = score_to_midi_bytes(_score_empty_tracks())
        fmt, ntrks, division = _parse_mthd(data)
        assert fmt == 1
        assert ntrks == 1
        assert division == 480

    def test_mtrk_block_count_matches_ntrks(self):
        """MTrk 块数 = ntrks"""
        data = score_to_midi_bytes(_score_v2())
        _, ntrks, _ = _parse_mthd(data)
        blocks = _parse_mtrk_blocks(data)
        assert len(blocks) == ntrks

    def test_custom_division(self):
        """自定义 division 透传到 header"""
        data = score_to_midi_bytes(_score_v2(), division=240)
        _, _, division = _parse_mthd(data)
        assert division == 240

    def test_invalid_bpm_raises(self):
        with pytest.raises(ValueError, match="bpm"):
            score_to_midi_bytes({**_score_v2(), "bpm": 0})


# ---------------------------------------------------------------------------
# 轨 0 元轨（tempo/拍号）
# ---------------------------------------------------------------------------


class TestTempoTrack:
    def test_tempo_meta_value(self):
        """bpm=120 → tempo=500000 微秒/四分音符"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        tempo_events = _parse_track_events(blocks[0])
        # 首事件：delta=0, FF 51 03 <3 bytes>
        delta, status, meta_type, meta_data = tempo_events[0]
        assert delta == 0
        assert status == 0xFF and meta_type == 0x51
        assert int.from_bytes(meta_data, "big") == 500000

    def test_time_signature_meta(self):
        """4/4 → FF 58 04 04 02 18 08"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[0])
        # 第二事件：拍号 meta
        delta, status, meta_type, meta_data = events[1]
        assert status == 0xFF and meta_type == 0x58
        assert meta_data == bytes([4, 2, 24, 8])

    def test_time_signature_3_4(self):
        """3/4 → nn=3, dd=2"""
        data = score_to_midi_bytes(_score_empty_tracks())
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[0])
        ts_events = [e for e in events if e[1] == 0xFF and e[2] == 0x58]
        assert ts_events
        assert ts_events[0][3] == bytes([3, 2, 24, 8])

    def test_tempo_track_has_no_notes(self):
        """元轨不含 Note On/Off"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[0])
        for ev in events:
            assert (ev[1] & 0xF0) not in (0x80, 0x90), "元轨不应含音符事件"

    def test_tempo_track_ends_with_eot(self):
        """元轨以 FF 2F 00 结束"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[0])
        last = events[-1]
        assert last[1] == 0xFF and last[2] == 0x2F


# ---------------------------------------------------------------------------
# 通道分配（旋律轨跳 9，打击乐轨固定 9）
# ---------------------------------------------------------------------------


class TestChannelAllocation:
    def test_melodic_tracks_skip_channel_9(self):
        """10 个旋律轨 → 通道 0,1,2,3,4,5,6,7,8,10（跳过 9）"""
        tracks = [
            {
                "id": f"trk_{i}",
                "name": f"轨{i}",
                "program": i,
                "mode": "manual",
                "volume": 100,
                "pan": 64,
                "events": [{"pitch": "C3", "beats": 1, "offset": 0}],
            }
            for i in range(10)
        ]
        score = {
            "title": "通道测试",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 1, "lyric": ""}],
            "accompaniment_tracks": tracks,
        }
        data = score_to_midi_bytes(score)
        blocks = _parse_mtrk_blocks(data)
        # 乐器轨 = blocks[1..10]
        channels = []
        for block in blocks[1:]:
            events = _parse_track_events(block)
            # program change 的 channel = status & 0x0F
            pc = [e for e in events if (e[1] & 0xF0) == 0xC0]
            assert pc, "旋律轨必须有 program change"
            channels.append(pc[0][1] & 0x0F)
        assert channels == [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]

    def test_drum_track_uses_channel_9(self):
        """打击乐轨固定通道 9"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        # 鼓轨 = blocks[3]（第 4 个轨）
        drum_events = _parse_track_events(blocks[3])
        note_ons = [e for e in drum_events if (e[1] & 0xF0) == 0x90]
        assert note_ons
        for ev in note_ons:
            assert (ev[1] & 0x0F) == 9, "鼓轨 Note On 必须走通道 9"

    def test_drum_track_no_program_change(self):
        """打击乐轨不写 program change"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        drum_events = _parse_track_events(blocks[3])
        pc = [e for e in drum_events if (e[1] & 0xF0) == 0xC0]
        assert pc == [], "鼓轨不应有 program change"

    def test_melodic_track_has_program_change(self):
        """旋律轨写 program change"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        piano_events = _parse_track_events(blocks[1])
        pc = [e for e in piano_events if (e[1] & 0xF0) == 0xC0]
        assert len(pc) == 1
        assert pc[0][2] == 0  # program=0 钢琴


# ---------------------------------------------------------------------------
# 轨首控制事件（program change + CC7 + CC10）
# ---------------------------------------------------------------------------


class TestTrackControls:
    def test_cc7_volume_direct_write(self):
        """CC7 直写 volume（钢琴轨 volume=100）"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        piano_events = _parse_track_events(blocks[1])
        cc7 = [e for e in piano_events if (e[1] & 0xF0) == 0xB0 and e[2] == 0x07]
        assert len(cc7) == 1
        assert cc7[0][3] == 100

    def test_cc10_pan_direct_write(self):
        """CC10 直写 pan（钢琴轨 pan=64）"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        piano_events = _parse_track_events(blocks[1])
        cc10 = [e for e in piano_events if (e[1] & 0xF0) == 0xB0 and e[2] == 0x0A]
        assert len(cc10) == 1
        assert cc10[0][3] == 64

    def test_bass_track_controls(self):
        """贝斯轨 program=33, volume=110, pan=56"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        bass_events = _parse_track_events(blocks[2])
        pc = [e for e in bass_events if (e[1] & 0xF0) == 0xC0]
        cc7 = [e for e in bass_events if (e[1] & 0xF0) == 0xB0 and e[2] == 0x07]
        cc10 = [e for e in bass_events if (e[1] & 0xF0) == 0xB0 and e[2] == 0x0A]
        assert pc[0][2] == 33
        assert cc7[0][3] == 110
        assert cc10[0][3] == 56

    def test_drum_track_cc7_cc10_without_program_change(self):
        """鼓轨有 CC7/CC10（通道 9）但无 program change"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        drum_events = _parse_track_events(blocks[3])
        cc7 = [e for e in drum_events if (e[1] & 0xF0) == 0xB0 and e[2] == 0x07]
        cc10 = [e for e in drum_events if (e[1] & 0xF0) == 0xB0 and e[2] == 0x0A]
        assert len(cc7) == 1 and (cc7[0][1] & 0x0F) == 9
        assert len(cc10) == 1 and (cc10[0][1] & 0x0F) == 9
        assert cc7[0][3] == 120  # 鼓轨 volume=120


# ---------------------------------------------------------------------------
# 多轨场景（2 旋律轨 + 1 鼓轨）
# ---------------------------------------------------------------------------


class TestMultiTrack:
    def test_note_on_off_counts(self):
        """钢琴轨 1 音符 + 贝斯轨 2 音符 + 鼓轨 2 音符 = 各轨 Note On/Off 数正确"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        # blocks[1]=钢琴(1音), blocks[2]=贝斯(2音), blocks[3]=鼓(2音)
        for idx, expected_notes in [(1, 1), (2, 2), (3, 2)]:
            events = _parse_track_events(blocks[idx])
            note_ons = [e for e in events if (e[1] & 0xF0) == 0x90]
            note_offs = [e for e in events if (e[1] & 0xF0) == 0x80]
            assert len(note_ons) == expected_notes
            assert len(note_offs) == expected_notes

    def test_each_track_ends_with_eot(self):
        """每条乐器轨以 FF 2F 00 结束"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        for block in blocks:
            events = _parse_track_events(block)
            last = events[-1]
            assert last[1] == 0xFF and last[2] == 0x2F


# ---------------------------------------------------------------------------
# auto 轨物化（真实调用 arranger.arrange_events）
# ---------------------------------------------------------------------------


class TestAutoMaterialization:
    def test_auto_track_materializes_via_arranger(self):
        """auto 空 events 钢琴轨 + block_chords → 物化为 C 和弦三音"""
        score = {
            "title": "auto 物化测试",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 4, "lyric": ""}],
            "chords": [{"chord": "C", "beats": 4}],
            "accompaniment_tracks": [
                {
                    "id": "trk_auto",
                    "name": "自动钢琴",
                    "program": 0,
                    "mode": "auto",
                    "style": "block_chords",
                    "volume": 100,
                    "pan": 64,
                    "events": [],  # 空 events → 物化
                }
            ],
        }
        data = score_to_midi_bytes(score)
        blocks = _parse_mtrk_blocks(data)
        track_events = _parse_track_events(blocks[1])
        note_ons = [e for e in track_events if (e[1] & 0xF0) == 0x90]
        # block_chords C 和弦 = 根音+三音+五音 = 3 个 Note On
        assert len(note_ons) == 3
        # 物化结果应与 arranger.arrange_events 一致
        expected = arrange_events(
            [{"chord": "C", "beats": 4}], "block_chords", 0, "4/4"
        )
        expected_pitches = {pitch_to_midi(e["pitch"]) for e in expected}
        actual_pitches = {e[2] for e in note_ons}
        assert actual_pitches == expected_pitches

    def test_manual_track_not_materialized(self):
        """manual 轨直接用 events 字段，不调 arranger"""
        score = _score_v2()  # 全 manual
        # 钢琴轨只有 1 个音符（C2）
        data = score_to_midi_bytes(score)
        blocks = _parse_mtrk_blocks(data)
        piano_events = _parse_track_events(blocks[1])
        note_ons = [e for e in piano_events if (e[1] & 0xF0) == 0x90]
        assert len(note_ons) == 1  # 不被物化扩展

    def test_auto_track_with_materialized_events_not_re_materialized(self):
        """auto 轨已有 events（物化过）→ 不再重新生成"""
        score = {
            "title": "已物化测试",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 4, "lyric": ""}],
            "chords": [{"chord": "C", "beats": 4}],
            "accompaniment_tracks": [
                {
                    "id": "trk_auto",
                    "name": "自动钢琴",
                    "program": 0,
                    "mode": "auto",
                    "style": "block_chords",
                    "volume": 100,
                    "pan": 64,
                    "events": [
                        {"pitch": "C3", "beats": 4, "offset": 0}
                    ],  # 已有 1 个音符
                }
            ],
        }
        data = score_to_midi_bytes(score)
        blocks = _parse_mtrk_blocks(data)
        track_events = _parse_track_events(blocks[1])
        note_ons = [e for e in track_events if (e[1] & 0xF0) == 0x90]
        assert len(note_ons) == 1  # 用已有 events，不重新物化


# ---------------------------------------------------------------------------
# pitch_to_midi / resolve_drum_key 集成
# ---------------------------------------------------------------------------


class TestPitchAndDrumKey:
    def test_melodic_pitch_via_pitch_to_midi(self):
        """旋律轨 pitch 经 pitch_to_midi 解析（C2=36）"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        piano_events = _parse_track_events(blocks[1])
        note_ons = [e for e in piano_events if (e[1] & 0xF0) == 0x90]
        assert note_ons[0][2] == pitch_to_midi("C2")  # 36

    def test_drum_pitch_via_resolve_drum_key(self):
        """鼓轨 pitch 经 resolve_drum_key 解析（kick=36, snare=38）"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        drum_events = _parse_track_events(blocks[3])
        note_ons = [e for e in drum_events if (e[1] & 0xF0) == 0x90]
        # offset=0 → kick(36), offset=1 → snare(38)
        pitches = sorted(e[2] for e in note_ons)
        assert pitches == [resolve_drum_key("kick"), resolve_drum_key("snare")]
        assert pitches == [36, 38]

    def test_velocity_written(self):
        """velocity 直写（钢琴轨 velocity=80）"""
        data = score_to_midi_bytes(_score_v2())
        blocks = _parse_mtrk_blocks(data)
        piano_events = _parse_track_events(blocks[1])
        note_ons = [e for e in piano_events if (e[1] & 0xF0) == 0x90]
        assert note_ons[0][3] == 80

    def test_default_velocity_when_missing(self):
        """events 未指定 velocity → 回退 MIDI_VELOCITY=64"""
        score = {
            "title": "默认力度",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 1, "lyric": ""}],
            "accompaniment_tracks": [
                {
                    "id": "trk",
                    "name": "轨",
                    "program": 0,
                    "mode": "manual",
                    "volume": 100,
                    "pan": 64,
                    "events": [{"pitch": "C3", "beats": 1, "offset": 0}],
                }
            ],
        }
        data = score_to_midi_bytes(score)
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[1])
        note_ons = [e for e in events if (e[1] & 0xF0) == 0x90]
        assert note_ons[0][3] == 64


# ---------------------------------------------------------------------------
# offset/beats → tick 换算
# ---------------------------------------------------------------------------


class TestTickConversion:
    def test_offset_to_tick(self):
        """offset=0.5, division=480 → start_tick=240"""
        score = {
            "title": "tick 测试",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 1, "lyric": ""}],
            "accompaniment_tracks": [
                {
                    "id": "trk",
                    "name": "轨",
                    "program": 0,
                    "mode": "manual",
                    "volume": 100,
                    "pan": 64,
                    "events": [
                        {"pitch": "C3", "beats": 1.0, "offset": 0.5, "velocity": 64}
                    ],
                }
            ],
        }
        data = score_to_midi_bytes(score, division=480)
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[1])
        note_ons = [e for e in events if (e[1] & 0xF0) == 0x90]
        note_offs = [e for e in events if (e[1] & 0xF0) == 0x80]
        # 轨首控制事件在 tick=0（delta=0），Note On 在 tick=240（delta=240）
        assert note_ons[0][0] == 240
        # Note Off 在 tick=240+480=720，delta=720-240=480
        assert note_offs[0][0] == 480

    def test_beats_duration_to_tick(self):
        """beats=2, division=480 → duration=960 tick"""
        score = {
            "title": "duration 测试",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 1, "lyric": ""}],
            "accompaniment_tracks": [
                {
                    "id": "trk",
                    "name": "轨",
                    "program": 0,
                    "mode": "manual",
                    "volume": 100,
                    "pan": 64,
                    "events": [
                        {"pitch": "C3", "beats": 2.0, "offset": 0, "velocity": 64}
                    ],
                }
            ],
        }
        data = score_to_midi_bytes(score, division=480)
        blocks = _parse_mtrk_blocks(data)
        events = _parse_track_events(blocks[1])
        note_ons = [e for e in events if (e[1] & 0xF0) == 0x90]
        note_offs = [e for e in events if (e[1] & 0xF0) == 0x80]
        # Note On delta=0（offset=0），Note Off delta=960（beats=2*480）
        assert note_ons[0][0] == 0
        assert note_offs[0][0] == 960


# ---------------------------------------------------------------------------
# 空歌谱边界（无伴奏轨）
# ---------------------------------------------------------------------------


class TestEmptyScore:
    def test_empty_tracks_produces_only_tempo_track(self):
        """无伴奏轨 → SMF 只有元轨（ntrks=1），无乐器轨"""
        data = score_to_midi_bytes(_score_empty_tracks())
        _, ntrks, _ = _parse_mthd(data)
        assert ntrks == 1
        blocks = _parse_mtrk_blocks(data)
        assert len(blocks) == 1  # 只有元轨

    def test_empty_tracks_no_note_events(self):
        """空歌谱 SMF 不含任何 Note On/Off"""
        data = score_to_midi_bytes(_score_empty_tracks())
        for block in _parse_mtrk_blocks(data):
            for ev in _parse_track_events(block):
                assert (ev[1] & 0xF0) not in (0x80, 0x90)

    def test_missing_accompaniment_tracks_field(self):
        """歌谱缺 accompaniment_tracks 字段 → 等价空轨（仅元轨）"""
        score = {
            "title": "无字段",
            "bpm": 120,
            "melody": [{"pitch": "C4", "beats": 1, "lyric": ""}],
        }
        data = score_to_midi_bytes(score)
        _, ntrks, _ = _parse_mthd(data)
        assert ntrks == 1


# ---------------------------------------------------------------------------
# fluidsynth 渲染（mock subprocess，免真实依赖）
# ---------------------------------------------------------------------------


class TestRenderAccompanimentMocked:
    """render_accompaniment 子进程交互路径（mock subprocess.run + shutil.which）"""

    @staticmethod
    def _wav_bytes(frames: int = 100, rate: int = 44100) -> bytes:
        """构造最小合法 16bit 单声道 WAV 字节（模拟 fluidsynth 产物）"""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"\x00\x00" * frames)
        return buf.getvalue()

    def _patch_fluidsynth_available(self, monkeypatch) -> None:
        """mock fluidsynth 可在 PATH 中找到"""
        monkeypatch.setattr(
            accompaniment_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}"
        )

    def test_render_returns_str_path(self, tmp_path, monkeypatch):
        """render_accompaniment 返回 str 路径（契约要求）"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            out.write_bytes(self._wav_bytes())
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        result = render_accompaniment(_score_v2(), str(out), soundfont_path=str(sf))
        assert isinstance(result, str)
        assert result == str(out)

    def test_render_invokes_fluidsynth_with_correct_args(
        self, tmp_path, monkeypatch
    ):
        """配置正确 soundfont + mock fluidsynth → 命令行契约 + 旁路 midi 落盘"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            out.write_bytes(self._wav_bytes())
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        render_accompaniment(_score_v2(), str(out), soundfont_path=str(sf))

        cmd = captured["cmd"]
        # fluidsynth -ni -F <wav> -r <rate> <soundfont> <midi>
        assert cmd[0] == "fluidsynth"
        assert cmd[1] == "-ni"
        assert "-F" in cmd and str(out) in cmd
        assert "-r" in cmd and "44100" in cmd
        assert str(sf) in cmd
        # 旁路 midi 落盘且为合法 SMF format 1
        midi = out.with_suffix(".mid")
        assert midi.is_file()
        midi_bytes = midi.read_bytes()
        assert midi_bytes[:4] == b"MThd"
        assert int.from_bytes(midi_bytes[8:10], "big") == 1  # format 1

    def test_render_custom_sample_rate(self, tmp_path, monkeypatch):
        """自定义 sample_rate 透传到 -r 参数"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            out.write_bytes(self._wav_bytes(rate=48000))
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        render_accompaniment(
            _score_v2(), str(out), soundfont_path=str(sf), sample_rate=48000
        )
        assert "48000" in captured["cmd"]

    def test_render_failure_nonzero_returncode(self, tmp_path, monkeypatch):
        """fluidsynth 返回非 0 → AccompanimentError 含退出码与 stderr"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=2, stdout="", stderr="boom: bad soundfont"
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        with pytest.raises(AccompanimentError, match="退出码 2") as exc_info:
            render_accompaniment(_score_v2(), str(out), soundfont_path=str(sf))
        assert "boom" in str(exc_info.value)

    def test_render_failure_empty_output(self, tmp_path, monkeypatch):
        """fluidsynth 退出码 0 但未产出有效 WAV → AccompanimentError"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        with pytest.raises(AccompanimentError, match="未产出有效 WAV"):
            render_accompaniment(_score_v2(), str(out), soundfont_path=str(sf))

    def test_render_timeout(self, tmp_path, monkeypatch):
        """fluidsynth 子进程超时 → AccompanimentError 含超时秒数"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=0.01)

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        with pytest.raises(AccompanimentError, match="超时"):
            render_accompaniment(
                _score_v2(), str(out), soundfont_path=str(sf), timeout=0.01
            )

    def test_render_writes_multitrack_midi(self, tmp_path, monkeypatch):
        """渲染时旁路 .mid 为 format 1 多轨（ntrks=1+轨数）"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            out.write_bytes(self._wav_bytes())
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        render_accompaniment(_score_v2(), str(out), soundfont_path=str(sf))
        midi = out.with_suffix(".mid")
        midi_bytes = midi.read_bytes()
        _, ntrks, _ = _parse_mthd(midi_bytes)
        assert ntrks == 4  # 1 元轨 + 3 乐器轨


# ---------------------------------------------------------------------------
# 依赖缺失逐项报错
# ---------------------------------------------------------------------------


class TestDependencyErrors:
    _MISSING_CMD = "fluidsynth-definitely-not-exists-cxo-task-module2"

    def test_missing_soundfont_message(self, tmp_path):
        fake_sf = str(tmp_path / "missing.sf2")
        with pytest.raises(AccompanimentError) as exc_info:
            render_accompaniment(
                _score_v2(),
                str(tmp_path / "out.wav"),
                soundfont_path=fake_sf,
                fluidsynth_cmd=self._MISSING_CMD,
            )
        message = str(exc_info.value)
        assert "SoundFont" in message
        assert fake_sf in message

    def test_missing_fluidsynth_message(self, tmp_path):
        sf = tmp_path / "ok.sf2"
        sf.write_bytes(b"fake-soundfont")
        with pytest.raises(AccompanimentError) as exc_info:
            render_accompaniment(
                _score_v2(),
                str(tmp_path / "out.wav"),
                soundfont_path=str(sf),
                fluidsynth_cmd=self._MISSING_CMD,
            )
        message = str(exc_info.value)
        assert "fluidsynth" in message
        assert "PATH" in message

    def test_both_missing_lists_all_items(self, tmp_path):
        fake_sf = str(tmp_path / "missing.sf2")
        with pytest.raises(AccompanimentError) as exc_info:
            render_accompaniment(
                _score_v2(),
                str(tmp_path / "out.wav"),
                soundfont_path=fake_sf,
                fluidsynth_cmd=self._MISSING_CMD,
            )
        message = str(exc_info.value)
        assert "SoundFont" in message and fake_sf in message
        assert "fluidsynth" in message and "PATH" in message

    def test_empty_soundfont_message(self, tmp_path):
        """空串 soundfont → 提示未配置"""
        with pytest.raises(AccompanimentError, match="SoundFont"):
            render_accompaniment(
                _score_v2(),
                str(tmp_path / "out.wav"),
                soundfont_path="",
                fluidsynth_cmd=self._MISSING_CMD,
            )

    def test_check_render_dependencies_empty_soundfont(self):
        problems = check_render_dependencies("", self._MISSING_CMD)
        assert len(problems) == 2
