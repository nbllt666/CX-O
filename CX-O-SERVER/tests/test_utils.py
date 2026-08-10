"""
tests/test_utils.py
===================
server.core.utils 纯函数单元测试（无外部依赖，可独立运行）。

覆盖：
  - extract_json：markdown 栅栏、前后缀说明、括号不平衡、尾随逗号、
    字符串内括号、数组、非 str 输入、None/空串 等噪声场景
  - deep_merge：字典递归合并
  - format_messages_for_summary：长内容裁剪与格式
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from server.core.utils import deep_merge, extract_json, format_messages_for_summary  # noqa: E402


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_plain_array(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_markdown_fence_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_markdown_fence_no_lang(self):
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_prefix_suffix_text(self):
        assert extract_json('好的，这是结果：{"a": 1} 请查收') == {"a": 1}

    def test_newline_prefix(self):
        assert extract_json('\n\n{"a": 1}\n\n') == {"a": 1}

    def test_unbalanced_prefix(self):
        # 前置说明文字含未闭合括号，应仍能提取顶层对象
        assert extract_json('注意：这一句（未闭合 {"a": 1}') == {"a": 1}

    def test_trailing_comma(self):
        # 尾随逗号：直接 loads 失败，走括号扫描分支
        assert extract_json('{"a": 1,}') == {"a": 1}

    def test_trailing_comma_in_array(self):
        assert extract_json("[1, 2, 3,]") == [1, 2, 3]

    def test_trailing_comma_preserves_string_internal_comma(self):
        # 字符串内部的逗号即使后随 } 也不应被剥离
        assert extract_json('{"a": "x, y", "b": 1,}') == {"a": "x, y", "b": 1}

    def test_string_embedded_brackets(self):
        # 字符串内含大括号，不应破坏外层解析
        assert extract_json('{"msg": "包含 { 和 } 的文本", "n": 2}')["msg"] == "包含 { 和 } 的文本"

    def test_escaped_quote_in_string(self):
        assert extract_json('{"msg": "她说：\\"你好\\""}')["msg"] == '她说："你好"'

    def test_nested_object(self):
        assert extract_json('{"outer": {"inner": [1, 2]}}') == {"outer": {"inner": [1, 2]}}

    def test_none_returns_default(self):
        assert extract_json(None, default="d") == "d"

    def test_empty_string_returns_default(self):
        assert extract_json("   ", default="d") == "d"

    def test_non_string_passthrough(self):
        assert extract_json({"a": 1}) == {"a": 1}
        assert extract_json(123) == 123

    def test_invalid_returns_default(self):
        assert extract_json("not json at all", default="d") == "d"

    def test_array_with_prefix(self):
        assert extract_json('结果：[1, 2, 3]') == [1, 2, 3]

    def test_default_not_called_on_valid(self):
        assert extract_json('{"ok": true}', default="should-not-use") == {"ok": True}


class TestDeepMerge:
    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 1}
        override = {"a": {"y": 3, "z": 4}, "c": 5}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 3, "z": 4}, "b": 1, "c": 5}

    def test_non_dict_value_overrides(self):
        base = {"a": {"x": 1}}
        override = {"a": "str"}
        assert deep_merge(base, override) == {"a": "str"}

    def test_does_not_mutate_inputs(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        deep_merge(base, override)
        assert base == {"a": {"x": 1}}
        assert override == {"a": {"y": 2}}


class TestFormatMessagesForSummary:
    def test_basic_format(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        out = format_messages_for_summary(msgs)
        assert out == "[1] user: hi\n[2] assistant: hello"

    def test_long_content_truncated(self):
        msgs = [{"role": "user", "content": "x" * 100}]
        out = format_messages_for_summary(msgs, max_content_length=10)
        assert out.endswith("...")
        assert len(out) < 100

    def test_missing_role_default(self):
        out = format_messages_for_summary([{"content": "no role"}])
        assert out == "[1] unknown: no role"