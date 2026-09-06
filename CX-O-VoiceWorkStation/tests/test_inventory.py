"""
音乐枚举清单测试（模块0 · inventory.py）

覆盖：INVENTORY 形状经冻结契约实例校验、128 音色 program 连续无缺、
styles/drum_keys 完备性、存取函数行为（get_inventory/get_style/resolve_drum_key）。
"""
from __future__ import annotations

import json
import os

import pytest
from jsonschema import Draft7Validator

from workstation.music.inventory import (
    INVENTORY,
    get_inventory,
    get_style,
    resolve_drum_key,
)

_CONTRACTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".trae", "specs", "redesign-composition-staff-editor", "contracts",
)


class TestInventoryShape:
    """INVENTORY 形状与冻结契约 music-inventory.schema.json 的一致性"""

    def test_inventory_passes_frozen_schema(self):
        with open(
            os.path.join(_CONTRACTS_DIR, "music-inventory.schema.json"), "r", encoding="utf-8"
        ) as fp:
            schema = json.load(fp)
        errors = list(Draft7Validator(schema).iter_errors(INVENTORY))
        assert errors == [], [f"{list(e.absolute_path)}: {e.message}" for e in errors]

    def test_sixteen_groups_fixed_order(self):
        groups = INVENTORY["instrument_groups"]
        assert len(groups) == 16
        expected_ids = [
            "piano", "chromatic_percussion", "organ", "guitar", "bass", "strings",
            "ensemble", "brass", "reed", "pipe", "synth_lead", "synth_pad",
            "synth_effects", "ethnic", "percussive", "sound_effects",
        ]
        assert [g["group_id"] for g in groups] == expected_ids

    def test_128_programs_contiguous(self):
        """128 音色 program 0–127 连续无缺；instruments[i].program = range[0] + i"""
        programs: list[int] = []
        for group in INVENTORY["instrument_groups"]:
            start, end = group["program_range"]
            assert end - start == 7
            assert len(group["instruments"]) == 8
            for i, instrument in enumerate(group["instruments"]):
                assert instrument["program"] == start + i
                programs.append(instrument["program"])
        assert programs == list(range(128))


class TestStyles:
    """节奏型枚举完备性"""

    def test_expected_styles_complete(self):
        styles = {s["id"]: s for s in INVENTORY["styles"]}
        assert set(styles) == {"block_chords", "arpeggio", "root_eighth", "rock_4beat"}
        assert styles["block_chords"]["applies_to"] == "melodic"
        assert styles["arpeggio"]["applies_to"] == "melodic"
        assert styles["root_eighth"]["applies_to"] == "melodic"
        assert styles["rock_4beat"]["applies_to"] == "percussion"

    def test_each_style_has_name_and_description(self):
        for style in INVENTORY["styles"]:
            assert style["name"]
            assert style["description"]


class TestDrumKeys:
    """鼓键映射完备性（初始最小集，score v2 打击乐轨 events.pitch 合法取值）"""

    def test_expected_drum_keys(self):
        keys = {entry["key"]: entry["midi"] for entry in INVENTORY["drum_keys"]}
        assert keys == {
            "kick": 36,
            "snare": 38,
            "closed_hihat": 42,
            "open_hihat": 46,
            "crash": 49,
            "ride": 51,
            "tom_high": 50,
            "tom_mid": 47,
            "tom_low": 45,
            "clap": 39,
        }

    def test_each_drum_key_has_chinese_name(self):
        for entry in INVENTORY["drum_keys"]:
            assert entry["name"]


class TestAccessors:
    """存取函数行为（签名匹配 voicews_music.pyi）"""

    def test_get_inventory_returns_deepcopy(self):
        inv = get_inventory()
        assert inv == INVENTORY
        assert inv is not INVENTORY
        # 篡改返回值不影响常量
        inv["instrument_groups"][0]["instruments"][0]["name"] = "被篡改"
        assert INVENTORY["instrument_groups"][0]["instruments"][0]["name"] != "被篡改"

    def test_get_style_hit(self):
        style = get_style("block_chords")
        assert style is not None
        assert style["id"] == "block_chords"
        assert style["applies_to"] == "melodic"
        assert style["name"] == "柱式和弦"

    def test_get_style_miss_returns_none(self):
        assert get_style("no_such_style") is None
        assert get_style("") is None

    def test_resolve_drum_key_canonical(self):
        assert resolve_drum_key("kick") == 36
        assert resolve_drum_key("snare") == 38
        assert resolve_drum_key("tom_low") == 45

    def test_resolve_drum_key_alias(self):
        assert resolve_drum_key("bd") == 36
        assert resolve_drum_key("bass_drum") == 36
        assert resolve_drum_key("hh") == 42

    def test_resolve_drum_key_chinese_name(self):
        assert resolve_drum_key("底鼓") == 36
        assert resolve_drum_key("军鼓") == 38

    def test_resolve_drum_key_unknown_raises_with_available(self):
        with pytest.raises(ValueError) as exc_info:
            resolve_drum_key("laser")
        message = str(exc_info.value)
        assert "laser" in message
        assert "kick" in message  # 附可用键名清单
