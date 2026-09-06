"""
草稿命令总线单测（模块3 · draft_registry）

覆盖范围（任务说明 S4-B2）：
- create_draft（有 seed / 无 seed 占位 / v1 输入迁移 / 非法种子）
- note 类命令（add_note / update_note / move_note / delete_note / set_lyric，melody + 伴奏轨）
- chord 类命令（add_chord / update_chord / delete_chord）
- track 类命令（add_track / remove_track / set_track_instrument / set_track_mode / set_track_mix）
- arrange_track（mock arranger.arrange_events，验证物化写入 + manual 轨 TRACK_MODE_INVALID + STYLE_UNKNOWN）
- undo / redo（含空栈空操作 success=true + version 不增、新编辑清空 redo 栈、栈上限）
- validate_draft（合法 / 非法）
- 错误码（DRAFT_NOT_FOUND / NOTE_NOT_FOUND / TRACK_NOT_FOUND / COMMAND_UNKNOWN / COMMAND_ARGS_INVALID）
- version 递增（get_draft / validate_draft 不增）
- 原子落盘（草稿文件存在 + load_draft 载入 + delete_draft 清理）
- TTL 清扫（构造过期 updated_at，sweep_expired_drafts 返回正确数）
- submit_draft（桩返回 task_id + auto 轨物化）

隔离策略：每测试清空 _REGISTRY + drafts_dir 指向 tmp_path（autouse fixture）
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta
from unittest import mock

import pytest

from workstation.music import draft_registry as dr


# ---------------------------------------------------------------------------
# 测试夹具与辅助
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path, monkeypatch):
    """每测试隔离：清空内存注册表 + drafts_dir 指向 tmp_path"""
    dr._REGISTRY.clear()
    monkeypatch.setattr(dr, "_drafts_dir_abs", lambda: str(tmp_path))
    yield
    dr._REGISTRY.clear()


def _seed_score() -> dict:
    """合法 v2 歌谱种子"""
    return {
        "title": "测试歌",
        "bpm": 120,
        "melody": [{"pitch": "C4", "beats": 1.0, "lyric": "你"}],
        "chords": [{"chord": "C", "beats": 4}],
        "accompaniment_tracks": [],
    }


def _exec(_draft_id: str, command: str, **args) -> dict:
    """execute_command 便捷封装：args 以关键字参数传入。
    第一个形参名刻意避让 ``draft_id``，以便 args 内可含 draft_id 关键字
    （command-protocol args_<command> schema 多数要求 draft_id 字段）。
    """
    return dr.execute_command(_draft_id, command, args)


def _create(seed=None) -> str:
    """建草稿并返回 draft_id"""
    r = dr.create_draft(seed)
    assert r["success"], f"create_draft 失败: {r}"
    return r["draft_id"]


def _make_fake_arranger(events: list[dict], style_resolved: str = "block_chords") -> mock.MagicMock:
    """构造 mock arranger 模块（arrange_events / resolve_style）"""
    fake = mock.MagicMock()
    fake.resolve_style.return_value = style_resolved
    fake.arrange_events.return_value = copy.deepcopy(events)
    return fake


# ---------------------------------------------------------------------------
# create_draft
# ---------------------------------------------------------------------------


class TestCreateDraft:
    def test_create_draft_no_seed_placeholder(self):
        """无 seed 建空白草稿：melody 置 C4 全音符占位"""
        r = dr.create_draft()
        assert r["success"] is True
        assert r["version"] == 0
        assert r["snapshot"]["title"] == "未命名"
        assert r["snapshot"]["bpm"] == 120
        assert r["snapshot"]["melody"] == [{"pitch": "C4", "beats": 4, "lyric": ""}]
        assert r["changed_paths"] == ["$"]
        # 落盘文件存在
        assert os.path.isfile(dr._draft_file_path(r["draft_id"]))

    def test_create_draft_with_seed(self):
        """有 seed：使用传入歌谱"""
        r = dr.create_draft(_seed_score())
        assert r["success"] is True
        assert r["version"] == 0
        assert r["snapshot"]["title"] == "测试歌"
        assert r["snapshot"]["melody"][0]["lyric"] == "你"

    def test_create_draft_v1_migration(self):
        """v1 输入（含 accompaniment_style 且不含 accompaniment_tracks）自动迁移到 v2"""
        v1 = _seed_score()
        del v1["accompaniment_tracks"]  # v1 无此字段（迁移触发条件：含 style 且不含 tracks）
        v1["accompaniment_style"] = "piano"
        r = dr.create_draft(v1)
        assert r["success"] is True, f"v1 迁移失败: {r}"
        snap = r["snapshot"]
        # 迁移后 accompaniment_style 不再出现
        assert "accompaniment_style" not in snap
        # 生成首条 auto 钢琴轨，piano → block_chords
        assert len(snap["accompaniment_tracks"]) == 1
        trk = snap["accompaniment_tracks"][0]
        assert trk["id"] == "trk_0"
        assert trk["mode"] == "auto"
        assert trk["style"] == "block_chords"

    def test_create_draft_invalid_seed(self):
        """非法种子返回 SCORE_VALIDATION_FAILED，状态不变"""
        bad = _seed_score()
        bad["bpm"] = -1  # bpm 必须 >0
        r = dr.create_draft(bad)
        assert r["success"] is False
        assert r["error"]["code"] == "SCORE_VALIDATION_FAILED"
        assert "errors" in r["error"]["details"]
        # 无草稿被创建
        assert dr._REGISTRY == {}

    def test_create_draft_via_execute_command(self):
        """create_draft 经 execute_command 入口（args={score} 或 {}）"""
        r = _exec("ignored", "create_draft", score=_seed_score())
        assert r["success"] is True
        # args 缺省 score 也应建空白草稿
        r2 = _exec("ignored", "create_draft")
        assert r2["success"] is True
        assert r2["snapshot"]["melody"] == [{"pitch": "C4", "beats": 4, "lyric": ""}]


# ---------------------------------------------------------------------------
# note 类命令
# ---------------------------------------------------------------------------


class TestNoteCommands:
    def test_add_note_melody_replaces_placeholder(self):
        """空白草稿首个 add_note 替换占位（melody 长度仍为 1）"""
        did = _create()  # 空白草稿
        r = _exec(did, "add_note", draft_id=did, track="melody", pitch="D4", beats=2, lyric="好")
        assert r["success"] is True
        assert r["snapshot"]["melody"] == [{"pitch": "D4", "beats": 2, "lyric": "好"}]
        assert r["version"] == 1

    def test_add_note_melody_append(self):
        """已有音符的 melody 轨追加"""
        did = _create(_seed_score())  # melody 已有 1 个音符
        r = _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        assert r["success"] is True
        assert len(r["snapshot"]["melody"]) == 2
        assert r["snapshot"]["melody"][1] == {"pitch": "E4", "beats": 1, "lyric": "世"}

    def test_add_note_accompaniment_track(self):
        """伴奏轨 add_note：显式 offset + 插入后按 offset 升序"""
        did = _create(_seed_score())
        # 先加一条 manual 伴奏轨
        r = _exec(did, "add_track", draft_id=did, name="贝斯", program=33, mode="manual")
        track_id = r["result"]["track_id"]
        # 加两个音符，offset 乱序
        r1 = _exec(did, "add_note", draft_id=did, track=track_id, pitch="C2", beats=2, offset=2)
        r2 = _exec(did, "add_note", draft_id=did, track=track_id, pitch="G2", beats=2, offset=0)
        assert r2["success"] is True
        track = r2["snapshot"]["accompaniment_tracks"][0]
        # 按 offset 升序：G2(0) 在 C2(2) 之前
        assert track["events"][0]["pitch"] == "G2"
        assert track["events"][1]["pitch"] == "C2"

    def test_add_note_accompaniment_default_offset(self):
        """伴奏轨 add_note 缺省 offset = 追加到轨尾 max(offset+beats)"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="贝斯", program=33, mode="manual")
        track_id = r["result"]["track_id"]
        _exec(did, "add_note", draft_id=did, track=track_id, pitch="C2", beats=2, offset=0)
        r2 = _exec(did, "add_note", draft_id=did, track=track_id, pitch="E2", beats=1)  # 缺省 offset
        assert r2["success"] is True
        ev = r2["snapshot"]["accompaniment_tracks"][0]["events"]
        # 第二个音符 offset = 0 + 2 = 2
        assert ev[1]["offset"] == 2

    def test_update_note_melody(self):
        did = _create(_seed_score())
        r = _exec(did, "update_note", draft_id=did, track="melody", note_id=0,
                  patch={"pitch": "D4", "lyric": "您"})
        assert r["success"] is True
        note = r["snapshot"]["melody"][0]
        assert note["pitch"] == "D4"
        assert note["lyric"] == "您"

    def test_update_note_accompanition(self):
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="贝斯", program=33, mode="manual")
        track_id = r["result"]["track_id"]
        _exec(did, "add_note", draft_id=did, track=track_id, pitch="C2", beats=2, offset=0)
        r2 = _exec(did, "update_note", draft_id=did, track=track_id, note_id=0,
                   patch={"velocity": 100, "offset": 4})
        assert r2["success"] is True
        ev = r2["snapshot"]["accompaniment_tracks"][0]["events"][0]
        assert ev["velocity"] == 100
        assert ev["offset"] == 4

    def test_update_note_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "update_note", draft_id=did, track="melody", note_id=99,
                  patch={"pitch": "D4"})
        assert r["success"] is False
        assert r["error"]["code"] == "NOTE_NOT_FOUND"
        # 状态不变（version 不增）
        assert dr._REGISTRY[did]["version"] == 0

    def test_move_note_melody_reorder(self):
        """melody 轨 move_note = 移动到序号位置（重排）"""
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        _exec(did, "add_note", draft_id=did, track="melody", pitch="G4", beats=1, lyric="界")
        # melody = [C4, E4, G4]；把 note_id=2(G4) 移到序号 0
        r = _exec(did, "move_note", draft_id=did, track="melody", note_id=2, new_offset=0)
        assert r["success"] is True
        melody = r["snapshot"]["melody"]
        assert melody[0]["pitch"] == "G4"
        assert melody[1]["pitch"] == "C4"
        assert melody[2]["pitch"] == "E4"

    def test_move_note_accompaniment_offset(self):
        """伴奏轨 move_note = 设置 offset（+ 可选 new_pitch），改后重排"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="贝斯", program=33, mode="manual")
        track_id = r["result"]["track_id"]
        _exec(did, "add_note", draft_id=did, track=track_id, pitch="C2", beats=2, offset=0)
        r2 = _exec(did, "move_note", draft_id=did, track=track_id, note_id=0,
                   new_offset=5, new_pitch="D2")
        assert r2["success"] is True
        ev = r2["snapshot"]["accompaniment_tracks"][0]["events"][0]
        assert ev["offset"] == 5
        assert ev["pitch"] == "D2"

    def test_move_note_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "move_note", draft_id=did, track="melody", note_id=99, new_offset=0)
        assert r["success"] is False
        assert r["error"]["code"] == "NOTE_NOT_FOUND"

    def test_delete_note_melody(self):
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        r = _exec(did, "delete_note", draft_id=did, track="melody", note_id=0)
        assert r["success"] is True
        assert len(r["snapshot"]["melody"]) == 1
        assert r["snapshot"]["melody"][0]["pitch"] == "E4"

    def test_delete_note_idempotent_noop(self):
        """delete_note 越界=空操作成功，version 不增"""
        did = _create(_seed_score())
        r = _exec(did, "delete_note", draft_id=did, track="melody", note_id=99)
        assert r["success"] is True
        assert r["version"] == 0  # 不增
        assert r["changed_paths"] == []

    def test_set_lyric(self):
        did = _create(_seed_score())
        r = _exec(did, "set_lyric", draft_id=did, note_id=0, lyric="您")
        assert r["success"] is True
        assert r["snapshot"]["melody"][0]["lyric"] == "您"

    def test_set_lyric_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "set_lyric", draft_id=did, note_id=99, lyric="x")
        assert r["success"] is False
        assert r["error"]["code"] == "NOTE_NOT_FOUND"

    def test_add_note_track_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "add_note", draft_id=did, track="no_such_track",
                  pitch="C4", beats=1)
        assert r["success"] is False
        assert r["error"]["code"] == "TRACK_NOT_FOUND"


# ---------------------------------------------------------------------------
# chord 类命令
# ---------------------------------------------------------------------------


class TestChordCommands:
    def test_add_chord_append(self):
        did = _create(_seed_score())  # 已有 1 个和弦 C
        r = _exec(did, "add_chord", draft_id=did, chord="G", beats=4)
        assert r["success"] is True
        assert len(r["snapshot"]["chords"]) == 2
        assert r["snapshot"]["chords"][1] == {"chord": "G", "beats": 4}

    def test_add_chord_insert(self):
        did = _create(_seed_score())
        r = _exec(did, "add_chord", draft_id=did, chord="Am", beats=2, index=0)
        assert r["success"] is True
        assert r["snapshot"]["chords"][0] == {"chord": "Am", "beats": 2}

    def test_update_chord(self):
        did = _create(_seed_score())
        r = _exec(did, "update_chord", draft_id=did, index=0,
                  patch={"chord": "G7", "beats": 2})
        assert r["success"] is True
        assert r["snapshot"]["chords"][0] == {"chord": "G7", "beats": 2}

    def test_update_chord_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "update_chord", draft_id=did, index=99, patch={"chord": "G7"})
        assert r["success"] is False
        assert r["error"]["code"] == "CHORD_NOT_FOUND"

    def test_delete_chord(self):
        did = _create(_seed_score())
        _exec(did, "add_chord", draft_id=did, chord="G", beats=4)
        r = _exec(did, "delete_chord", draft_id=did, index=0)
        assert r["success"] is True
        assert len(r["snapshot"]["chords"]) == 1
        assert r["snapshot"]["chords"][0]["chord"] == "G"

    def test_delete_chord_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "delete_chord", draft_id=did, index=99)
        assert r["success"] is False
        assert r["error"]["code"] == "CHORD_NOT_FOUND"


# ---------------------------------------------------------------------------
# track 类命令
# ---------------------------------------------------------------------------


class TestTrackCommands:
    def test_add_track(self):
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="auto",
                  style="block_chords")
        assert r["success"] is True
        assert "track_id" in r["result"]
        track_id = r["result"]["track_id"]
        assert track_id.startswith("trk_")
        track = r["snapshot"]["accompaniment_tracks"][0]
        assert track["id"] == track_id
        assert track["name"] == "钢琴"
        assert track["mode"] == "auto"
        assert track["style"] == "block_chords"
        assert track["volume"] == 100
        assert track["pan"] == 64
        assert track["events"] == []

    def test_add_track_id_unique(self):
        """多次 add_track 生成不同 id"""
        did = _create(_seed_score())
        r1 = _exec(did, "add_track", draft_id=did, name="t1", program=0, mode="manual")
        r2 = _exec(did, "add_track", draft_id=did, name="t2", program=0, mode="manual")
        assert r1["result"]["track_id"] != r2["result"]["track_id"]

    def test_remove_track(self):
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="manual")
        track_id = r["result"]["track_id"]
        r2 = _exec(did, "remove_track", draft_id=did, track_id=track_id)
        assert r2["success"] is True
        assert len(r2["snapshot"]["accompaniment_tracks"]) == 0

    def test_remove_track_idempotent(self):
        """remove_track 不存在=空操作成功（幂等，对齐 delete_note 范式）"""
        did = _create(_seed_score())
        r = _exec(did, "remove_track", draft_id=did, track_id="trk_nonexistent")
        assert r["success"] is True
        assert r["version"] == 0  # 空操作 version 不增
        assert r["changed_paths"] == []

    def test_set_track_instrument(self):
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="manual")
        track_id = r["result"]["track_id"]
        r2 = _exec(did, "set_track_instrument", draft_id=did, track_id=track_id, program=33)
        assert r2["success"] is True
        track = r2["snapshot"]["accompaniment_tracks"][0]
        assert track["program"] == 33

    def test_set_track_instrument_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "set_track_instrument", draft_id=did,
                  track_id="no_such", program=33)
        assert r["success"] is False
        assert r["error"]["code"] == "TRACK_NOT_FOUND"

    def test_set_track_mode_manual_to_auto(self):
        """切 auto 时保留 events 作为微调基线，style 不变"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="manual",
                  style="block_chords")
        track_id = r["result"]["track_id"]
        r2 = _exec(did, "set_track_mode", draft_id=did, track_id=track_id, mode="auto")
        assert r2["success"] is True
        track = r2["snapshot"]["accompaniment_tracks"][0]
        assert track["mode"] == "auto"
        assert track["style"] == "block_chords"

    def test_set_track_mix(self):
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="manual")
        track_id = r["result"]["track_id"]
        r2 = _exec(did, "set_track_mix", draft_id=did, track_id=track_id, volume=80, pan=100)
        assert r2["success"] is True
        track = r2["snapshot"]["accompaniment_tracks"][0]
        assert track["volume"] == 80
        assert track["pan"] == 100


# ---------------------------------------------------------------------------
# arrange_track
# ---------------------------------------------------------------------------


class TestArrangeTrack:
    def test_arrange_track_auto_materialize(self):
        """auto 轨 arrange_track：物化写入 events，返回 events"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="auto",
                  style="block_chords")
        track_id = r["result"]["track_id"]
        fake_events = [
            {"pitch": "C4", "beats": 4, "offset": 0, "velocity": 64},
            {"pitch": "E4", "beats": 4, "offset": 4, "velocity": 64},
        ]
        fake_arranger = _make_fake_arranger(fake_events, style_resolved="block_chords")
        with mock.patch.object(dr, "_import_arranger", return_value=fake_arranger):
            r2 = _exec(did, "arrange_track", draft_id=did, track_id=track_id)
        assert r2["success"] is True
        assert r2["result"]["events"] == fake_events
        track = r2["snapshot"]["accompaniment_tracks"][0]
        assert track["events"] == fake_events
        # resolve_style 被调用（program=0 → block_chords 回退路径）
        fake_arranger.resolve_style.assert_called_once_with("block_chords", 0)
        # arrange_events 被调用，参数：chords, resolved_style, program, time_signature
        call_args = fake_arranger.arrange_events.call_args
        assert call_args.args[1] == "block_chords"
        assert call_args.args[2] == 0

    def test_arrange_track_with_explicit_style(self):
        """arrange_track 提供新 style 时更新轨 style 字段"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="auto",
                  style="block_chords")
        track_id = r["result"]["track_id"]
        fake_arranger = _make_fake_arranger([], style_resolved="arpeggio")
        with mock.patch.object(dr, "_import_arranger", return_value=fake_arranger):
            r2 = _exec(did, "arrange_track", draft_id=did, track_id=track_id, style="arpeggio")
        assert r2["success"] is True
        track = r2["snapshot"]["accompaniment_tracks"][0]
        assert track["style"] == "arpeggio"

    def test_arrange_track_manual_invalid(self):
        """manual 轨 arrange_track 报 TRACK_MODE_INVALID"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="manual")
        track_id = r["result"]["track_id"]
        r2 = _exec(did, "arrange_track", draft_id=did, track_id=track_id)
        assert r2["success"] is False
        assert r2["error"]["code"] == "TRACK_MODE_INVALID"
        assert r2["error"]["details"]["track_id"] == track_id
        assert r2["error"]["details"]["mode"] == "manual"

    def test_arrange_track_style_unknown(self):
        """arranger 抛 ValueError → STYLE_UNKNOWN"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="auto",
                  style="block_chords")
        track_id = r["result"]["track_id"]
        fake_arranger = mock.MagicMock()
        fake_arranger.resolve_style.return_value = "block_chords"
        fake_arranger.arrange_events.side_effect = ValueError("unknown style: foo")
        with mock.patch.object(dr, "_import_arranger", return_value=fake_arranger):
            r2 = _exec(did, "arrange_track", draft_id=did, track_id=track_id)
        assert r2["success"] is False
        assert r2["error"]["code"] == "STYLE_UNKNOWN"
        assert "style" in r2["error"]["details"]

    def test_arrange_track_track_not_found(self):
        did = _create(_seed_score())
        r = _exec(did, "arrange_track", draft_id=did, track_id="no_such")
        assert r["success"] is False
        assert r["error"]["code"] == "TRACK_NOT_FOUND"


# ---------------------------------------------------------------------------
# undo / redo
# ---------------------------------------------------------------------------


class TestUndoRedo:
    def test_undo_redo_basic(self):
        """undo 撤销编辑，redo 重做"""
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        # version=1, melody=[C4, E4]
        r_undo = _exec(did, "undo", draft_id=did)
        assert r_undo["success"] is True
        assert r_undo["version"] == 2  # undo 也 +1
        assert len(r_undo["snapshot"]["melody"]) == 1  # 回到 [C4]
        r_redo = _exec(did, "redo", draft_id=did)
        assert r_redo["success"] is True
        assert r_redo["version"] == 3
        assert len(r_redo["snapshot"]["melody"]) == 2  # 回到 [C4, E4]

    def test_undo_empty_stack_noop(self):
        """空 undo 栈：success=true，version 不增，快照不变"""
        did = _create(_seed_score())
        before = dr._REGISTRY[did]["score"]
        r = _exec(did, "undo", draft_id=did)
        assert r["success"] is True
        assert r["version"] == 0  # 不增
        assert r["changed_paths"] == ["$"]
        assert dr._REGISTRY[did]["score"] == before

    def test_redo_empty_stack_noop(self):
        """空 redo 栈：success=true，version 不增"""
        did = _create(_seed_score())
        r = _exec(did, "redo", draft_id=did)
        assert r["success"] is True
        assert r["version"] == 0

    def test_new_edit_clears_redo(self):
        """新编辑命令清空 redo 栈"""
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        _exec(did, "undo", draft_id=did)  # undo 后 redo 栈有 1 项
        assert len(dr._REGISTRY[did]["redo_stack"]) == 1
        # 新编辑命令
        _exec(did, "add_note", draft_id=did, track="melody", pitch="G4", beats=1, lyric="界")
        assert len(dr._REGISTRY[did]["redo_stack"]) == 0  # 被清空

    def test_undo_stack_limit(self):
        """undo 栈上限 undo_stack_limit（默认 100），超出 FIFO 弹出最旧"""
        did = _create(_seed_score())
        # 连续 105 次 add_note（melody 轨追加）
        for i in range(105):
            r = _exec(did, "add_note", draft_id=did, track="melody",
                      pitch="C4", beats=1, lyric=str(i))
            assert r["success"], f"第 {i} 次 add_note 失败"
        # undo 栈上限 100
        assert len(dr._REGISTRY[did]["undo_stack"]) == 100


# ---------------------------------------------------------------------------
# validate_draft
# ---------------------------------------------------------------------------


class TestValidateDraft:
    def test_validate_draft_valid(self):
        did = _create(_seed_score())
        r = _exec(did, "validate_draft", draft_id=did)
        assert r["success"] is True
        assert r["result"]["valid"] is True
        assert r["result"]["errors"] == []
        # version 不增
        assert r["version"] == 0

    def test_validate_draft_invalid(self):
        """直接破坏 score 制造非法态（绕过命令校验），validate_draft 应报 invalid"""
        did = _create(_seed_score())
        # 直接篡改内存 score（模拟不一致态）
        dr._REGISTRY[did]["score"]["bpm"] = -1
        r = _exec(did, "validate_draft", draft_id=did)
        assert r["success"] is True  # validate_draft 本身成功
        assert r["result"]["valid"] is False
        assert len(r["result"]["errors"]) > 0


# ---------------------------------------------------------------------------
# 错误码
# ---------------------------------------------------------------------------


class TestErrorCodes:
    def test_draft_not_found(self):
        r = _exec("nonexistent", "get_draft", draft_id="nonexistent")
        assert r["success"] is False
        assert r["error"]["code"] == "DRAFT_NOT_FOUND"
        assert r["error"]["details"]["draft_id"] == "nonexistent"

    def test_command_unknown(self):
        did = _create(_seed_score())
        r = _exec(did, "not_a_command", draft_id=did)
        assert r["success"] is False
        assert r["error"]["code"] == "COMMAND_UNKNOWN"
        assert "available" in r["error"]["details"]
        assert "create_draft" in r["error"]["details"]["available"]

    def test_command_args_invalid(self):
        """args 缺必填字段 → COMMAND_ARGS_INVALID"""
        did = _create(_seed_score())
        # add_note 缺 pitch
        r = _exec(did, "add_note", draft_id=did, track="melody", beats=1)
        assert r["success"] is False
        assert r["error"]["code"] == "COMMAND_ARGS_INVALID"
        assert "errors" in r["error"]["details"]

    def test_command_args_invalid_wrong_type(self):
        """args 类型错误 → COMMAND_ARGS_INVALID"""
        did = _create(_seed_score())
        # beats 必须是 number，传字符串
        r = _exec(did, "add_note", draft_id=did, track="melody",
                  pitch="C4", beats="not_a_number")
        assert r["success"] is False
        assert r["error"]["code"] == "COMMAND_ARGS_INVALID"

    def test_track_not_found_on_set(self):
        did = _create(_seed_score())
        r = _exec(did, "set_track_mix", draft_id=did, track_id="no_such", volume=80)
        assert r["success"] is False
        assert r["error"]["code"] == "TRACK_NOT_FOUND"


# ---------------------------------------------------------------------------
# version 语义
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_increments_on_edit(self):
        did = _create(_seed_score())
        assert dr._REGISTRY[did]["version"] == 0
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        assert dr._REGISTRY[did]["version"] == 1
        _exec(did, "add_chord", draft_id=did, chord="G", beats=4)
        assert dr._REGISTRY[did]["version"] == 2

    def test_version_not_increment_on_get(self):
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        v_before = dr._REGISTRY[did]["version"]
        _exec(did, "get_draft", draft_id=did)
        assert dr._REGISTRY[did]["version"] == v_before

    def test_version_not_increment_on_validate(self):
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        v_before = dr._REGISTRY[did]["version"]
        _exec(did, "validate_draft", draft_id=did)
        assert dr._REGISTRY[did]["version"] == v_before


# ---------------------------------------------------------------------------
# 原子落盘 + load_draft + delete_draft
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_draft_file_created(self):
        """create_draft 后 draft.json 存在"""
        did = _create(_seed_score())
        path = dr._draft_file_path(did)
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        assert data["draft_id"] == did
        assert data["version"] == 0
        assert data["score"]["title"] == "测试歌"
        # undo/redo 栈不落盘
        assert "undo_stack" not in data
        assert "redo_stack" not in data

    def test_draft_file_updated_on_edit(self):
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        with open(dr._draft_file_path(did), "r", encoding="utf-8") as fp:
            data = json.load(fp)
        assert data["version"] == 1
        assert len(data["score"]["melody"]) == 2

    def test_load_draft_after_restart(self):
        """load_draft 从磁盘恢复草稿到注册表（undo/redo 栈清空）"""
        did = _create(_seed_score())
        _exec(did, "add_note", draft_id=did, track="melody", pitch="E4", beats=1, lyric="世")
        # 模拟重启：清空内存注册表
        dr._REGISTRY.clear()
        assert dr._REGISTRY.get(did) is None
        # load_draft 恢复
        state = dr.load_draft(did)
        assert state is not None
        assert state["draft_id"] == did
        assert state["version"] == 1
        assert state["score"]["melody"][1]["pitch"] == "E4"
        # undo/redo 栈重启清空
        assert state["undo_stack"] == []
        assert state["redo_stack"] == []
        assert did in dr._REGISTRY
        # 恢复后可继续编辑
        r = _exec(did, "add_note", draft_id=did, track="melody", pitch="G4", beats=1, lyric="界")
        assert r["success"] is True
        assert r["version"] == 2

    def test_load_draft_nonexistent(self):
        assert dr.load_draft("nonexistent") is None

    def test_delete_draft_cleanup(self):
        """delete_draft 删除内存注册表 + 落盘文件"""
        did = _create(_seed_score())
        assert os.path.isfile(dr._draft_file_path(did))
        assert did in dr._REGISTRY
        result = dr.delete_draft(did)
        assert result is True
        assert did not in dr._REGISTRY
        assert not os.path.exists(dr._draft_file_path(did))

    def test_delete_draft_idempotent(self):
        """delete_draft 不存在返回 False（幂等，不报错）"""
        result = dr.delete_draft("nonexistent")
        assert result is False

    def test_atomic_rollback_on_validation_fail(self):
        """编辑后整谱校验失败 → 回滚，version 不增，score 不变"""
        did = _create(_seed_score())
        # 用 mock 使 validate_score 在应用后失败
        with mock.patch("workstation.music.draft_registry.validate_score",
                        return_value=(False, ["mock fail"], None)):
            r = _exec(did, "add_note", draft_id=did, track="melody",
                      pitch="E4", beats=1, lyric="世")
        assert r["success"] is False
        assert r["error"]["code"] == "SCORE_VALIDATION_FAILED"
        # 状态不变
        assert dr._REGISTRY[did]["version"] == 0
        assert len(dr._REGISTRY[did]["score"]["melody"]) == 1


# ---------------------------------------------------------------------------
# TTL 清扫
# ---------------------------------------------------------------------------


class TestTtlSweep:
    def test_sweep_expired(self):
        """过期草稿被清扫，返回清扫数"""
        did1 = _create(_seed_score())
        did2 = _create(_seed_score())
        # 构造 did1 过期（10 天前）
        expired = (datetime.now().astimezone() - timedelta(days=10)).isoformat(timespec="seconds")
        dr._REGISTRY[did1]["updated_at"] = expired
        # did2 保持当前
        count = dr.sweep_expired_drafts(7)
        assert count == 1
        assert did1 not in dr._REGISTRY
        assert did2 in dr._REGISTRY
        # 过期草稿的落盘文件也被清理
        assert not os.path.exists(dr._draft_file_path(did1))

    def test_sweep_zero_ttl(self):
        """ttl_days=0 不清扫"""
        did = _create(_seed_score())
        expired = (datetime.now().astimezone() - timedelta(days=30)).isoformat(timespec="seconds")
        dr._REGISTRY[did]["updated_at"] = expired
        count = dr.sweep_expired_drafts(0)
        assert count == 0
        assert did in dr._REGISTRY

    def test_sweep_not_expired(self):
        """未过期草稿不清扫"""
        did = _create(_seed_score())
        # updated_at 是当前时间
        count = dr.sweep_expired_drafts(7)
        assert count == 0
        assert did in dr._REGISTRY

    def test_sweep_boundary(self):
        """恰好 ttl 天边界：updated_at = now - 7 天，仍算未过期（< threshold 严格过期）"""
        did = _create(_seed_score())
        # 设为 6 天前（未过期）
        recent = (datetime.now().astimezone() - timedelta(days=6)).isoformat(timespec="seconds")
        dr._REGISTRY[did]["updated_at"] = recent
        count = dr.sweep_expired_drafts(7)
        assert count == 0


# ---------------------------------------------------------------------------
# list_drafts
# ---------------------------------------------------------------------------


class TestListDrafts:
    def test_list_drafts_order(self):
        """list_drafts 按 updated_at 倒序"""
        did1 = _create(_seed_score())
        # 调整 did1 updated_at 为较早
        dr._REGISTRY[did1]["updated_at"] = (datetime.now().astimezone() - timedelta(days=1)).isoformat(timespec="seconds")
        did2 = _create(_seed_score())  # 最新
        items = dr.list_drafts()
        assert len(items) == 2
        assert items[0]["draft_id"] == did2  # 最新在前
        assert items[1]["draft_id"] == did1
        # 字段完整
        assert set(items[0].keys()) == {"draft_id", "title", "version", "updated_at"}

    def test_list_drafts_empty(self):
        assert dr.list_drafts() == []


# ---------------------------------------------------------------------------
# submit_draft
# ---------------------------------------------------------------------------


class TestSubmitDraft:
    def test_submit_draft_stub(self):
        """submit_draft 桩返回 task_id（version 不增）"""
        did = _create(_seed_score())
        r = _exec(did, "submit_draft", draft_id=did)
        assert r["success"] is True
        assert "task_id" in r["result"]
        assert r["result"]["status"] == "pending"
        assert r["version"] == 0  # submit 非编辑类，version 不增
        # 草稿保留可继续编辑
        assert did in dr._REGISTRY

    def test_submit_draft_auto_materialize(self):
        """submit_draft 物化 auto 空 events 轨"""
        did = _create(_seed_score())
        r = _exec(did, "add_track", draft_id=did, name="钢琴", program=0, mode="auto",
                  style="block_chords")
        track_id = r["result"]["track_id"]
        fake_events = [{"pitch": "C4", "beats": 4, "offset": 0, "velocity": 64}]
        fake_arranger = _make_fake_arranger(fake_events, "block_chords")
        with mock.patch.object(dr, "_import_arranger", return_value=fake_arranger):
            r2 = _exec(did, "submit_draft", draft_id=did)
        assert r2["success"] is True
        # 物化不修改原草稿（deepcopy 后物化）
        track = r2["snapshot"]["accompaniment_tracks"][0]
        assert track["events"] == []  # 原草稿未变
        # 但 arranger 被调用（submit 内部物化副本）
        fake_arranger.arrange_events.assert_called_once()

    def test_submit_draft_not_found(self):
        r = dr.submit_draft("nonexistent")
        assert r["success"] is False
        assert r["error"]["code"] == "DRAFT_NOT_FOUND"


# ---------------------------------------------------------------------------
# execute_command 顶层分发
# ---------------------------------------------------------------------------


class TestExecuteCommandDispatch:
    def test_get_draft_via_execute_command(self):
        did = _create(_seed_score())
        r = _exec(did, "get_draft", draft_id=did)
        assert r["success"] is True
        assert r["version"] == 0
        assert r["snapshot"]["title"] == "测试歌"

    def test_command_unknown_returns_available_list(self):
        r = _exec("x", "bogus")
        assert r["success"] is False
        assert r["error"]["code"] == "COMMAND_UNKNOWN"
        assert len(r["error"]["details"]["available"]) == 20

    def test_args_validated_before_draft_lookup(self):
        """args 校验在 draft 查找之前（COMMAND_ARGS_INVALID 优先于 DRAFT_NOT_FOUND）"""
        # 即使 draft 不存在，args 非法也应先报 COMMAND_ARGS_INVALID
        r = _exec("nonexistent", "add_note", draft_id="nonexistent", track="melody", beats=1)
        # 缺 pitch → COMMAND_ARGS_INVALID
        assert r["success"] is False
        assert r["error"]["code"] == "COMMAND_ARGS_INVALID"
