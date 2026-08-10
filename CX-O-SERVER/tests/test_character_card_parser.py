"""server.core.distillation.character_card_parser 单元测试。

覆盖 JSON/PNG 解析、V1/V2/V3 规范化、source_ref 转换与便捷入口。
运行：python -m pytest tests/test_character_card_parser.py -v
"""
import base64
import io
import json

import pytest

from server.core.distillation.character_card_parser import (
    _decode_card_json,
    character_card_to_source_ref,
    normalize_character_card,
    parse_character_card_from_bytes,
    parse_character_card_from_json_str,
    parse_json_character_card,
    parse_png_character_card,
)


def _png_bytes(card: dict, key: str = "chara_card_v3") -> bytes:
    from PIL import Image, PngImagePlugin

    buf = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text(key, json.dumps(card, ensure_ascii=False))
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


class TestParseJson:
    def test_valid(self):
        assert parse_json_character_card('{"a": 1}') == {"a": 1}

    def test_invalid_json(self):
        with pytest.raises(ValueError):
            parse_json_character_card("{not json")

    def test_not_object(self):
        with pytest.raises(ValueError):
            parse_json_character_card("[1, 2]")


class TestDecodeCardJson:
    def test_direct_json(self):
        assert _decode_card_json('{"x": 1}') == {"x": 1}

    def test_base64_json(self):
        raw = base64.b64encode('{"y": 2}'.encode()).decode()
        assert _decode_card_json(raw) == {"y": 2}

    def test_base64_bytes_json(self):
        decoded = base64.b64encode('{"z": 3}'.encode())
        assert _decode_card_json(decoded.decode()) == {"z": 3}

    def test_invalid(self):
        with pytest.raises(ValueError):
            _decode_card_json("not valid at all")


class TestParsePng:
    def test_extracts_v3(self):
        card = {"spec": "chara_card_v3", "data": {"name": "Alice", "description": "hi"}}
        raw = parse_png_character_card(_png_bytes(card))
        assert raw["spec"] == "chara_card_v3"

    def test_v2_key_fallback(self):
        card = {"name": "Bob"}
        raw = parse_png_character_card(_png_bytes(card, key="chara"))
        assert raw["name"] == "Bob"

    def test_v3_prefers_over_v2(self):
        card = {"spec": "chara_card_v3", "data": {"name": "V3"}}
        raw = parse_png_character_card(_png_bytes(card, key="chara"))
        assert raw["spec"] == "chara_card_v3"

    def test_invalid_png(self):
        with pytest.raises(ValueError):
            parse_png_character_card(b"not a png")

    def test_no_card_chunk(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="PNG")
        with pytest.raises(ValueError):
            parse_png_character_card(buf.getvalue())


class TestNormalize:
    def test_v3_data(self):
        raw = {
            "spec": "chara_card_v3",
            "spec_version": "3.0",
            "data": {"name": "Alice", "personality": "kind"},
        }
        out = normalize_character_card(raw)
        assert out["spec"] == "chara_card_v3"
        assert out["name"] == "Alice"
        assert out["personality"] == "kind"

    def test_v2_default_version(self):
        raw = {"spec": "chara_card_v2", "data": {"name": "Bob"}}
        out = normalize_character_card(raw)
        assert out["spec_version"] == "2.0"

    def test_v1_flat(self):
        raw = {"name": "Carol", "description": "desc"}
        out = normalize_character_card(raw)
        assert out["spec"] == "v1_legacy"
        assert out["name"] == "Carol"
        assert out["description"] == "desc"

    def test_data_without_spec(self):
        raw = {"data": {"name": "Dave"}}
        out = normalize_character_card(raw)
        assert out["spec"] == "unknown"
        assert out["name"] == "Dave"

    def test_missing_name_default(self):
        out = normalize_character_card({"description": "x"})
        assert out["name"] == "未命名角色"

    def test_extra_fields_in_source(self):
        raw = {"spec": "chara_card_v3", "data": {"name": "A", "custom_tag": "v"}}
        out = normalize_character_card(raw)
        assert out["extra_fields"]["custom_tag"] == "v"

    def test_extra_top_level_fields(self):
        raw = {"spec": "chara_card_v3", "data": {"name": "A"}, "meta_custom": 1}
        out = normalize_character_card(raw)
        assert out["extra_fields"]["_top_meta_custom"] == 1

    def test_standard_fields_not_in_extra(self):
        raw = {"spec": "chara_card_v2", "data": {"name": "A", "spec_version": "x"}}
        out = normalize_character_card(raw)
        assert "name" not in out["extra_fields"]
        assert "spec_version" not in out["extra_fields"]


class TestSourceRef:
    def test_standard_fields_in_order(self):
        card = {
            "name": "Alice",
            "description": "desc",
            "personality": "kind",
            "first_mes": "hi",
        }
        ref = character_card_to_source_ref(card)
        assert "角色名: Alice" in ref
        assert "描述: desc" in ref
        assert "性格: kind" in ref
        assert "开场白: hi" in ref

    def test_empty_skipped(self):
        ref = character_card_to_source_ref({"name": "A", "description": ""})
        assert "描述" not in ref

    def test_alternate_greetings(self):
        card = {"name": "A", "alternate_greetings": ["g1", "g2"]}
        ref = character_card_to_source_ref(card)
        assert "备选问候语 1: g1" in ref
        assert "备选问候语 2: g2" in ref

    def test_character_book_summary(self):
        card = {"name": "A", "character_book": {"entries": [{}, {}]}}
        ref = character_card_to_source_ref(card)
        assert "角色书: 2 条目" in ref

    def test_extensions_keys(self):
        card = {"name": "A", "extensions": {"world": 1, "talkativeness": 2}}
        ref = character_card_to_source_ref(card)
        assert "扩展: world, talkativeness" in ref

    def test_extra_fields_dict_json(self):
        card = {"name": "A", "extra_fields": {"book": {"t": 1}}}
        ref = character_card_to_source_ref(card)
        assert "额外字段 - book" in ref


class TestParseBytes:
    def test_json_bytes(self):
        data = parse_character_card_from_bytes(
            json.dumps({"name": "A"}).encode(), filename="card.json"
        )
        assert data["name"] == "A"

    def test_png_magic_without_name(self):
        card = {"spec": "chara_card_v3", "data": {"name": "PNG"}}
        data = parse_character_card_from_bytes(_png_bytes(card))
        assert data["name"] == "PNG"

    def test_invalid_utf8(self):
        with pytest.raises(ValueError):
            parse_character_card_from_bytes(b"\xff\xfe\x00\x01")

    def test_from_json_str(self):
        data = parse_character_card_from_json_str('{"name": "B"}')
        assert data["name"] == "B"