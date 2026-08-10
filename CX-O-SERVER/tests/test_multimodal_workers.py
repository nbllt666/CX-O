"""server.core.multimodal.workers 四个 worker 的直接回归测试。

主管线（MultimodalPipeline）测试已用 mock worker 覆盖装配与分发路由；本文件
直接测试各 worker 的真实实现逻辑，隔离外部依赖（chardet / PIL / PaddleOCR /
requests），覆盖：

- TextWorker: 原始文本 / 文件读取 / NFKC 归一化 / 编码检测回退 / 异常
- CharacterCardWorker: JSON 字符串 / JSON 文件 / base64 / PNG 解析 / 字段标准化
- ImageWorker: OCR 解析 / bbox 归一化 / vision 请求与降级 / merge 置信度
- VLLMNativeWorker: 原生 / 降级 / payload 构造 / 响应提取

运行：python -m pytest tests/test_multimodal_workers.py -v
"""
import base64
import json
import sys
import types

import pytest

from server.core.multimodal.workers.text_worker import TextWorker
from server.core.multimodal.workers.character_card_worker import CharacterCardWorker
from server.core.multimodal.workers.image_worker import ImageWorker
from server.core.multimodal.workers.vllm_native_worker import VLLMNativeWorker


# ================================================================ TextWorker
class TestTextWorker:
    def test_process_raw_text(self):
        out = TextWorker().process("你好 World")
        assert out["text_content"] == "你好 World"
        assert out["extra_metadata"]["encoding"] == "utf-8"
        assert out["confidence"] == 1.0
        assert out["vision_degraded"] is False

    def test_process_nfkc_normalization(self):
        # 全角字符 → NFKC 归一化
        out = TextWorker().process("ＡＢＣ　１２３")
        assert out["text_content"] == "ABC 123"

    def test_process_strips_whitespace(self):
        assert TextWorker().process("  hello  " )["text_content"] == "hello"

    def test_process_empty_raises(self):
        with pytest.raises(ValueError):
            TextWorker().process("")

    def test_process_file_utf8(self, tmp_path):
        p = tmp_path / "note.txt"
        p.write_bytes("你好世界".encode("utf-8"))
        out = TextWorker().process(str(p))
        assert out["text_content"] == "你好世界"
        assert out["extra_metadata"]["encoding"] == "utf-8"

    def test_process_missing_path_treated_as_raw_text(self):
        # 非 isfile 的字符串按原始文本处理（设计行为，不抛 FileNotFoundError）
        out = TextWorker().process("missing.txt")
        assert out["text_content"] == "missing.txt"

    def test_detect_encoding_fallback_no_chardet(self, monkeypatch):
        # sys.modules["chardet"]=None → import 抛 ImportError，走 utf-8/gbk 回退
        monkeypatch.setitem(sys.modules, "chardet", None)
        enc = TextWorker._detect_encoding("utf-8 文本".encode("utf-8"))
        assert enc in ("utf-8", "gbk")

    def test_detect_encoding_fallback_all_fail(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "chardet", None)
        # 随机字节无法用 utf-8/gbk 严格解码
        with pytest.raises(ValueError):
            TextWorker._detect_encoding(b"\xff\xfe\x00\x81\xff")

    def test_detect_encoding_chardet_none_result(self, monkeypatch):
        fake = types.ModuleType("chardet")
        fake.detect = lambda b: {"encoding": None}
        monkeypatch.setitem(sys.modules, "chardet", fake)
        enc = TextWorker._detect_encoding("纯文本".encode("utf-8"))
        assert enc in ("utf-8", "gbk")

    def test_read_file_undoable_decode_falls_back(self, monkeypatch):
        # 让 chardet 返回 ascii → 对中文 utf-8 字节解码失败 → 回退 utf-8 replace
        fake = types.ModuleType("chardet")
        fake.detect = lambda b: {"encoding": "ascii"}
        monkeypatch.setitem(sys.modules, "chardet", fake)
        import tempfile, os
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as f:
            f.write("中文".encode("utf-8"))
            path = f.name
        try:
            text, enc = TextWorker()._read_file(path)
            assert text == "中文"
            assert enc == "utf-8"
        finally:
            os.unlink(path)


# ================================================================ CharacterCardWorker
class TestCharacterCardWorker:
    CARD = {"name": "爱丽丝", "description": "测试角色", "personality": "开朗"}

    def test_process_json_string(self):
        out = CharacterCardWorker().process(json.dumps(self.CARD, ensure_ascii=False))
        assert out["extra_metadata"]["name"] == "爱丽丝"
        assert out["confidence"] == 0.95
        assert out["vision_degraded"] is False
        assert "爱丽丝" in out["text_content"]

    def test_process_json_file(self, tmp_path):
        p = tmp_path / "card.json"
        p.write_text(json.dumps(self.CARD, ensure_ascii=False), encoding="utf-8")
        out = CharacterCardWorker().process(str(p))
        assert out["extra_metadata"]["name"] == "爱丽丝"

    def test_process_base64_string(self):
        b64 = base64.b64encode(json.dumps(self.CARD).encode("utf-8")).decode("ascii")
        out = CharacterCardWorker().process(b64)
        assert out["extra_metadata"]["name"] == "爱丽丝"

    def test_process_empty_raises(self):
        with pytest.raises(ValueError):
            CharacterCardWorker().process("")

    def test_json_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CharacterCardWorker().process(str(tmp_path / "missing.json"))

    def test_png_no_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CharacterCardWorker().parse_placeholder = None
            CharacterCardWorker()._extract_raw_json(str(tmp_path / "no.png"))

    def test_json_non_object_raises(self):
        with pytest.raises(ValueError):
            CharacterCardWorker()._parse_json_string("[1,2,3]")

    def test_name_missing_raises(self):
        with pytest.raises(ValueError):
            CharacterCardWorker()._normalize_fields({"description": "x"})

    def test_normalize_fields_defaults(self):
        fields = CharacterCardWorker._normalize_fields({"name": "n"})
        assert fields["description"] == ""
        assert fields["personality"] == ""
        assert fields["scenario"] == ""
        assert fields["first_mes"] == ""
        assert fields["mes_example"] == ""

    def test_normalize_fields_coerce_types(self):
        fields = CharacterCardWorker._normalize_fields(
            {"name": "n", "personality": 123, "description": None}
        )
        assert fields["personality"] == "123"
        assert fields["description"] == ""

    def test_looks_like_base64(self):
        assert CharacterCardWorker._looks_like_base64(
            "aGVsbG8gd29ybGQhISEhISEh"  # 合法 base64
        ) is True
        assert CharacterCardWorker._looks_like_base64("中文文本不base64吗") is False
        assert CharacterCardWorker._looks_like_base64("short") is False

    def test_png_parse_with_chara_chunk(self, monkeypatch, tmp_path):
        import base64 as _b64
        chara_b64 = _b64.b64encode(json.dumps(self.CARD).encode("utf-8")).decode("ascii")

        fake_img_cls = type("Image", (), {"open": staticmethod(lambda p: FakeImg(chara_b64))})
        fake_pil = types.ModuleType("PIL")
        fake_pil.Image = fake_img_cls
        monkeypatch.setitem(sys.modules, "PIL", fake_pil)

        p = tmp_path / "card.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n not-a-real-png")
        out = CharacterCardWorker()._parse_png_character_card(str(p))
        assert out["name"] == "爱丽丝"

    def test_png_without_chara_raises(self, monkeypatch, tmp_path):
        fake_img_cls = type("L", (), {"open": staticmethod(lambda p: FakeImg(None))})
        fake_pil = types.ModuleType("PIL")
        fake_pil.Image = fake_img_cls
        monkeypatch.setitem(sys.modules, "PIL", fake_pil)
        p = tmp_path / "card.png"
        p.write_bytes(b"x")
        with pytest.raises(ValueError):
            CharacterCardWorker()._parse_png_character_card(str(p))

    def test_png_pillow_not_installed(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "PIL", raising=False)
        p = tmp_path / "card.png"
        p.write_bytes(b"x")
        with pytest.raises(RuntimeError):
            CharacterCardWorker()._parse_png_character_card(str(p))


class FakeImg:
    """模拟 PIL Image：text 含可选 chara chunk。"""
    def __init__(self, chara_b64):
        self.text = {"chara": chara_b64} if chara_b64 else {}
        self.info = {}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


# ================================================================ ImageWorker
class TestImageWorker:
    def test_ocr_empty_path_raises(self):
        with pytest.raises(RuntimeError):
            ImageWorker().ocr("")

    def test_ocr_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ImageWorker().ocr(str(tmp_path / "missing.png"))

    def test_ocr_parse_lines(self, tmp_path, monkeypatch):
        img = tmp_path / "img.png"
        img.write_bytes(b"fake")
        w = ImageWorker()
        fake_engine = type("Engine", (), {
            "ocr": lambda self, path, cls=True: [
                [  # 页面 1
                    [[[10, 10], [50, 10], [50, 30], [10, 30]], ("你好", 0.98)],
                    [[[100, 100], [200, 100], [200, 140], [100, 140]], "世界"],
                    None,
                ]
            ]
        })
        monkeypatch.setattr(w, "_get_paddleocr", lambda: fake_engine())
        blocks, conf = w.ocr(str(img))
        # 按 bbox y 升序 → 你好 在前
        assert [b["text"] for b in blocks] == ["你好", "世界"]
        assert conf == pytest.approx(0.94, abs=0.01)

    def test_ocr_engine_not_installed(self, monkeypatch, tmp_path):
        monkeypatch.delitem(sys.modules, "paddleocr", raising=False)
        img = tmp_path / "img.png"
        img.write_bytes(b"fake")
        w = ImageWorker()
        with pytest.raises(RuntimeError):
            w._get_paddleocr()

    def test_normalize_bbox(self):
        box = [[10, 20], [50, 20], [50, 60], [10, 60]]
        assert ImageWorker._normalize_bbox(box) == [10, 20, 50, 60]

    def test_normalize_bbox_invalid(self):
        assert ImageWorker._normalize_bbox("bad") == [0, 0, 0, 0]

    def test_parse_ocr_line_invalid(self):
        assert ImageWorker._parse_ocr_line("junk") is None
        assert ImageWorker._parse_ocr_line([]) is None

    def test_vision_not_configured(self, tmp_path):
        img = tmp_path / "img.png"
        img.write_bytes(b"fake")
        w = ImageWorker(vision_model="")
        with pytest.raises(ConnectionError):
            w.vision(str(img))

    def test_vision_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ImageWorker(vision_model="m").vision(str(tmp_path / "no.png"))

    def test_vision_success(self, tmp_path, monkeypatch):
        img = tmp_path / "img.png"
        img.write_bytes(b"fake")
        w = ImageWorker(vision_model="m")
        response = types.SimpleNamespace(
            json=lambda: {"choices": [{"message": {"content": "一只猫"}}]}
        )
        monkeypatch.setattr(w, "_post_vision_request", lambda payload: response)
        assert w.vision(str(img)) == "一只猫"

    def test_vision_content_list(self):
        response = types.SimpleNamespace(
            json=lambda: {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
        )
        assert ImageWorker._extract_vision_text(response) == "a b"

    def test_vision_no_choices_raises(self, monkeypatch):
        response = types.SimpleNamespace(json=lambda: {"choices": []})
        with pytest.raises(RuntimeError):
            ImageWorker._extract_vision_text(response)

    def test_image_to_data_url(self, tmp_path):
        img = tmp_path / "pic.jpg"
        img.write_bytes(b"\x00\x01")
        url = ImageWorker._image_to_data_url(str(img))
        assert url.startswith("data:image/jpeg;base64,")

    def test_merge_with_vision(self):
        w = ImageWorker()
        w._last_ocr_confidence = 0.95
        out = w.merge([{"text": "A"}], "描述")
        assert out["vision_degraded"] is False
        assert out["confidence"] == pytest.approx(0.9)  # min(0.95, 0.9)
        assert "描述" in out["text_content"]

    def test_merge_without_vision(self):
        out = ImageWorker().merge([{"text": "A"}], "")
        assert out["vision_degraded"] is True
        assert out["confidence"] == 0.7
        assert out["text_content"] == "A"

    def test_invoke_paddleocr_empty(self):
        engine = type("E", (), {"ocr": lambda self, p, cls=True: None})()
        assert ImageWorker()._invoke_paddleocr(engine, "x.png") == []


# ================================================================ VLLMNativeWorker
class TestVLLMNativeWorker:
    def test_process_invalid_modality(self):
        with pytest.raises(ValueError):
            VLLMNativeWorker().process("x", "bogus", use_native=False)

    def test_process_empty_source(self):
        with pytest.raises(FileNotFoundError):
            VLLMNativeWorker().process("", "video", use_native=False)

    def test_process_degraded_when_not_native(self):
        out = VLLMNativeWorker().process("v.mp4", "video", use_native=False, provider="ollama")
        assert out["native_decode_used"] is False
        assert out["vision_degraded"] is True
        assert out["confidence"] == 0.5

    def test_process_native_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            VLLMNativeWorker().process(str(tmp_path / "no.mp4"), "video", use_native=True)

    def test_process_native_connection_error_degrades(self, tmp_path, monkeypatch):
        f = tmp_path / "a.mp4"
        f.write_bytes(b"fake")
        w = VLLMNativeWorker()

        def _fail(src, m):
            raise ConnectionError("unreachable")

        monkeypatch.setattr(w, "_call_vllm_native", _fail)
        out = w.process(str(f), "video", use_native=True, provider="vllm")
        assert out["native_decode_used"] is False
        assert out["vision_degraded"] is True

    def test_process_native_success(self, tmp_path, monkeypatch):
        f = tmp_path / "a.mp4"
        f.write_bytes(b"fake")
        w = VLLMNativeWorker()
        monkeypatch.setattr(w, "_call_vllm_native", lambda src, m: "视频内容")
        out = w.process(str(f), "video", use_native=True, provider="vllm")
        assert out["native_decode_used"] is True
        assert out["vision_degraded"] is False
        assert out["confidence"] == 0.88
        assert out["text_content"] == "视频内容"

    def test_build_payload_video(self, tmp_path):
        f = tmp_path / "a.mp4"
        f.write_bytes(b"data")
        payload = VLLMNativeWorker()._build_payload(str(f), "video")
        content = payload["messages"][0]["content"]
        video = [c for c in content if c.get("type") == "video_url"][0]
        assert video["video_url"]["url"].startswith("data:video/mp4;base64,")

    def test_build_payload_audio(self, tmp_path):
        f = tmp_path / "a.wav"
        f.write_bytes(b"data")
        payload = VLLMNativeWorker()._build_payload(str(f), "audio")
        content = payload["messages"][0]["content"]
        audio = [c for c in content if c.get("type") == "input_audio"][0]
        assert audio["input_audio"]["format"] == "wav"
        assert "data" in audio["input_audio"]

    def test_extract_response_text(self):
        resp = types.SimpleNamespace(
            json=lambda: {"choices": [{"message": {"content": "转录"}}]}
        )
        assert VLLMNativeWorker._extract_response_text(resp) == "转录"

    def test_extract_response_no_choices(self):
        resp = types.SimpleNamespace(json=lambda: {"choices": []})
        with pytest.raises(RuntimeError):
            VLLMNativeWorker._extract_response_text(resp)