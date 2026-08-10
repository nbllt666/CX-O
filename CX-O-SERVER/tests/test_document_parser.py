"""server.core.document.parser 单元测试。

覆盖 data URI 解析、MIME 推断、文本/PDF/DOCX 解析、图片识别与附件批处理。
运行：python -m pytest tests/test_document_parser.py -v
"""
import base64

import pytest

import server.core.document.parser as dp


def _data_uri(mime, data: bytes, base64_enc: bool = True) -> str:
    payload = base64.b64encode(data).decode() if base64_enc else data.decode("utf-8")
    return f"data:{mime};base64,{payload}" if base64_enc else f"data:{mime},{payload}"


class TestParseDataUri:
    def test_base64(self):
        mime, raw = dp.parse_data_uri(_data_uri("text/plain", b"hello"))
        assert mime == "text/plain"
        assert raw == b"hello"

    def test_non_base64(self):
        # 非 base64 需 header 含 ';' 且不含 base64（如 charset）
        mime, raw = dp.parse_data_uri("data:text/plain;charset=utf-8,hello")
        assert mime == "text/plain"
        assert raw == b"hello"

    def test_missing_data_prefix(self):
        with pytest.raises(ValueError):
            dp.parse_data_uri("text/plain,hello")

    def test_empty(self):
        with pytest.raises(ValueError):
            dp.parse_data_uri("")

    def test_missing_payload(self):
        with pytest.raises(ValueError):
            dp.parse_data_uri("data:text/plain;base64,")

    def test_invalid_base64(self):
        # 单字符 base64 长度非法，b64decode 会抛错
        with pytest.raises(ValueError):
            dp.parse_data_uri("data:text/plain;base64,a")

    def test_size_limit(self):
        big = b"a" * (dp.MAX_DOCUMENT_SIZE + 1)
        with pytest.raises(ValueError):
            dp.parse_data_uri(f"data:text/plain;base64,{base64.b64encode(big).decode()}")

    def test_empty_mime(self):
        # 无 ';' 时 mime 直接取 header 剩余部分（此处为空串）
        mime, _ = dp.parse_data_uri("data:;base64,aGk=")
        assert mime == ""


class TestInferMime:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.pdf", "application/pdf"),
            ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("a.doc", "application/msword"),
            ("a.txt", "text/plain"),
            ("a.md", "text/markdown"),
            ("a.markdown", "text/markdown"),
            ("a.unknown", "application/octet-stream"),
        ],
    )
    def test_extensions(self, name, expected):
        assert dp._infer_mime_from_name(name) == expected


class TestParseText:
    def test_utf8(self):
        assert dp._parse_text("你好".encode("utf-8")) == "你好"

    def test_gbk_fallback(self):
        assert dp._parse_text("中文".encode("gbk")) == "中文"

    def test_replace_fallback(self):
        out = dp._parse_text(b"\xff\xfe\x00")
        assert isinstance(out, str)


class TestParseDocument:
    def test_text_mime(self):
        assert dp.parse_document("a.txt", "text/plain", b"content") == "content"

    def test_markdown_mime(self):
        assert dp.parse_document("a.md", "text/markdown", b"# title") == "# title"

    def test_anythingllm_infers_from_name(self, monkeypatch):
        monkeypatch.setattr(dp, "_parse_text", lambda b: "inferred")
        assert dp.parse_document("a.txt", "application/anythingllm-document", b"x") == "inferred"

    def test_old_doc_returns_hint(self):
        out = dp.parse_document("old.doc", "application/msword", b"x")
        assert "不支持解析旧版 .doc" in out

    def test_unsupported_mime(self):
        with pytest.raises(ValueError):
            dp.parse_document("a.xyz", "application/octet-stream", b"x")

    def test_pdf_parses(self):
        # 用一个最小合法 PDF，pypdf 能解析页数
        pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\nxref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
        out = dp.parse_document("a.pdf", "application/pdf", pdf)
        assert isinstance(out, str)

    def test_pdf_pypdf_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "pypdf":
                raise ImportError("no pypdf")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ValueError):
            dp.parse_document("a.pdf", "application/pdf", b"x")


class TestIsImage:
    def test_true(self):
        assert dp.is_image_attachment("image/png") is True

    def test_false(self):
        assert dp.is_image_attachment("text/plain") is False


class TestParseAttachment:
    def test_document(self):
        att = {"name": "a.txt", "mime": "text/plain", "contentString": _data_uri("text/plain", b"hi")}
        text, img = dp.parse_attachment(att)
        assert text == "hi"
        assert img is None

    def test_image(self):
        att = {"name": "p.png", "mime": "image/png", "contentString": _data_uri("image/png", b"\x89png")}
        text, img = dp.parse_attachment(att)
        assert text is None
        assert img is not None

    def test_missing_content(self):
        with pytest.raises(ValueError):
            dp.parse_attachment({"name": "a.txt", "mime": "text/plain"})


class TestParseAttachments:
    def test_empty(self):
        assert dp.parse_attachments([]) == ("", [])

    def test_mixed(self):
        atts = [
            {"name": "a.txt", "mime": "text/plain", "contentString": _data_uri("text/plain", b"doc1")},
            {"name": "p.png", "mime": "image/png", "contentString": _data_uri("image/png", b"\x89png")},
        ]
        text, images = dp.parse_attachments(atts)
        assert "doc1" in text
        assert len(images) == 1

    def test_error_collected_not_raised(self):
        atts = [
            {"name": "bad", "mime": "text/plain", "contentString": "not-a-data-uri"},
            {"name": "ok.txt", "mime": "text/plain", "contentString": _data_uri("text/plain", b"good")},
        ]
        text, images = dp.parse_attachments(atts)
        assert "good" in text
        assert "解析失败" in text
        assert images == []