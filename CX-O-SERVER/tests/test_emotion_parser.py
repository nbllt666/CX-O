"""server.services.emotion_parser 单元测试。

覆盖情感标记解析纯函数：extract_emotions_with_text / get_supported_emotions。

运行：python -m pytest tests/test_emotion_parser.py -v
"""
from server.services.emotion_parser import (
    get_supported_emotions,
    extract_emotions_with_text,
)


def test_supported_emotions_sorted():
    emo = get_supported_emotions()
    assert isinstance(emo, list)
    assert emo == sorted(emo)
    assert "happy" in emo
    assert "neutral" in emo


# ---------------------------------------------------------------- extract
def test_extract_plain_text():
    segs = extract_emotions_with_text("你好世界")
    assert segs == [{"type": "text", "content": "你好世界"}]


def test_extract_single_emotion():
    segs = extract_emotions_with_text("[emotion:happy]哈哈")
    assert segs == [
        {"type": "emotion", "emotion": "happy"},
        {"type": "text", "content": "哈哈"},
    ]


def test_extract_emotion_case_insensitive():
    segs = extract_emotions_with_text("[emotion:HAPPY]")
    assert segs == [{"type": "emotion", "emotion": "happy"}]


def test_extract_emotion_between_text():
    segs = extract_emotions_with_text("前面[emotion:sad]后面")
    assert segs == [
        {"type": "text", "content": "前面"},
        {"type": "emotion", "emotion": "sad"},
        {"type": "text", "content": "后面"},
    ]


def test_extract_unknown_emotion_kept_as_text():
    segs = extract_emotions_with_text("[emotion:rage]")
    assert len(segs) == 1
    assert segs[0]["type"] == "text"
    assert segs[0]["content"] == "[emotion:rage]"


def test_extract_sleep():
    segs = extract_emotions_with_text("[sleep:1500]")
    assert segs == [{"type": "sleep", "duration_ms": 1500}]


def test_extract_sleep_and_emotion():
    segs = extract_emotions_with_text("a[emotion:laugh]b[sleep:500]c")
    assert segs == [
        {"type": "text", "content": "a"},
        {"type": "emotion", "emotion": "laugh"},
        {"type": "text", "content": "b"},
        {"type": "sleep", "duration_ms": 500},
        {"type": "text", "content": "c"},
    ]


def test_extract_empty_text():
    assert extract_emotions_with_text("") == []


def test_extract_whitespace_only():
    assert extract_emotions_with_text("   ") == []


def test_extract_outside_text_preserved():
    segs = extract_emotions_with_text("[emotion:calm] 睡 觉 ")
    assert segs[-1] == {"type": "text", "content": "睡 觉"}