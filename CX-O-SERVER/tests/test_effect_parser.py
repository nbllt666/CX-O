"""server.services.effect_parser 单元测试。

覆盖 EffectParser：音效标记解析、effects_dir 缺失回退、缓存、多扩展名加载、
get_available_effects、clear_cache。用 tmp_path 构建临时 effect 文件。

运行：python -m pytest tests/test_effect_parser.py -v
"""
import pytest

from server.services.effect_parser import EffectParser


def _make_effect(dir, name, ext=".wav", data=b"\x00\x01"):
    (dir / f"{name}{ext}").write_bytes(data)


# ---------------------------------------------------------------- 基础
def test_parse_plain_text():
    p = EffectParser()
    assert p.parse_text_with_effects("你好") == [{"type": "text", "content": "你好"}]


def test_parse_empty():
    assert EffectParser().parse_text_with_effects("") == []


def test_parse_no_dir_effect_data_none():
    p = EffectParser()
    segs = p.parse_text_with_effects("[effect:boom]")
    assert len(segs) == 1
    assert segs[0]["type"] == "effect"
    assert segs[0]["name"] == "boom"
    assert segs[0]["data"] is None


def test_parse_effect_between_text(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "boom")
    segs = p.parse_text_with_effects("前[effect:boom]后")
    assert segs[0] == {"type": "text", "content": "前"}
    assert segs[1]["type"] == "effect"
    assert segs[1]["data"] == b"\x00\x01"
    assert segs[2] == {"type": "text", "content": "后"}


# ---------------------------------------------------------------- 加载/缓存
def test_load_effect_loads_binary(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "boom", data=b"DATA")
    assert p._load_effect("boom") == b"DATA"


def test_load_effect_multiple_extensions(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "bu", ext=".mp3")
    _make_effect(tmp_path, "ba", ext=".ogg")
    assert p._load_effect("bu") == b"\x00\x01"
    assert p._load_effect("ba") == b"\x00\x01"


def test_load_effect_extension_priority(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "x", ext=".wav", data=b"WAV")
    _make_effect(tmp_path, "x", ext=".mp3", data=b"MP3")
    assert p._load_effect("x") == b"WAV"


def test_load_effect_missing(tmp_path):
    p = EffectParser(str(tmp_path))
    assert p._load_effect("ghost") is None


def test_load_effect_caches(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "boom")
    assert p._load_effect("boom") is not None
    # 第二次命中缓存
    assert p._load_effect("boom") is not None


def test_no_dir_warns(tmp_path):
    p = EffectParser(str(tmp_path / "missing"))
    assert p._load_effect("boom") is None


# ---------------------------------------------------------------- 可用列表/清缓存
def test_get_available_effects(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "a")
    _make_effect(tmp_path, "b", ext=".ogg")
    _make_effect(tmp_path, "c", ext=".txt")  # 非音频扩展被忽略
    (tmp_path / "subdir").mkdir()
    assert p.get_available_effects() == ["a", "b"]


def test_get_available_no_dir(tmp_path):
    p = EffectParser(str(tmp_path / "missing"))
    assert p.get_available_effects() == []


def test_clear_cache(tmp_path):
    p = EffectParser(str(tmp_path))
    _make_effect(tmp_path, "boom")
    p._load_effect("boom")
    assert len(p._effects_cache) == 1
    p.clear_cache()
    assert p._effects_cache == {}