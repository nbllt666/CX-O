"""server.core.graph.vectorizer (TextVectorizer) 单元测试。

覆盖简化哈希向量化、无模型回退、批量编码、维度、单例与关闭。
运行：python -m pytest tests/test_graph_vectorizer.py -v
"""
from types import SimpleNamespace

import numpy as np
import pytest

import server.core.graph.vectorizer as vmod
from server.core.graph.vectorizer import TextVectorizer, get_vectorizer


def _config(vector_dim=8):
    return SimpleNamespace(
        model="fake-model",
        device="cpu",
        cache_folder="/tmp/cache",
        batch_size=4,
        vector_dim=vector_dim,
    )


@pytest.fixture
def vec():  # 无模型环境：强制 _load_model 不加载
    v = TextVectorizer(config=_config())
    v._model = None
    return v


class TestSimpleEncode:
    def test_dimension(self, vec):
        out = vec._simple_encode("hello world")
        assert out.shape == (8,)
        assert out.dtype == np.float32

    def test_empty_text_zeros(self, vec):
        out = vec._simple_encode("")
        assert np.all(out == 0)

    def test_deterministic(self, vec):
        a = vec._simple_encode("hello world")
        b = vec._simple_encode("hello world")
        assert np.array_equal(a, b)

    def test_values_in_range(self, vec):
        out = vec._simple_encode("a b c d")
        assert np.all(out >= 0) and np.all(out <= 1)

    def test_long_text_truncated(self, vec):
        out = vec._simple_encode(" ".join(["w"] * 20))
        assert np.count_nonzero(out) == 8  # 只取前 vector_dim 个词


class TestEncode:
    def test_no_model_falls_back_to_simple(self, vec):
        out = vec.encode("hello")
        assert isinstance(out, np.ndarray)
        assert len(out) == 8

    def test_encode_batch(self, vec):
        out = vec.encode_batch(["a", "b", "c"])
        assert out.shape == (3, 8)


class TestLoadModel:
    def test_import_error_sets_none(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "sentence_transformers":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        v = TextVectorizer(config=_config())
        v._load_model()
        assert v._model is None


class TestDimAndClose:
    def test_get_dimension(self, vec):
        assert vec.get_dimension() == 8

    def test_close(self, vec):
        vec._model = object()
        vec.close()
        assert vec._model is None


class TestSingleton:
    def test_get_vectorizer_singleton(self, monkeypatch):
        monkeypatch.setattr(vmod, "_vectorizer", None)
        a = get_vectorizer()
        b = get_vectorizer()
        assert a is b