"""Tests for the SentenceTransformer embedder with disk cache."""

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.nlp.embedder import Embedder


class TestInit:
    def test_init_does_not_load_model(self) -> None:
        embedder = Embedder()
        assert embedder._model is None

    def test_init_defaults(self) -> None:
        embedder = Embedder()
        assert embedder.model_name == "paraphrase-multilingual-MiniLM-L12-v2"
        assert embedder.cache_dir == "data/embeddings_cache"


class TestEncode:
    @patch("src.nlp.embedder.Embedder._init_model")
    def test_encode_single_returns_numpy_array(
        self, mock_init: MagicMock, tmp_path
    ) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        fake_model = MagicMock()
        fake_model.encode.return_value = np.array([[1.0, 2.0, 3.0]])
        embedder._model = fake_model
        result = embedder.encode_single("hello world")
        assert isinstance(result, np.ndarray)
        assert result.shape == (3,)
        fake_model.encode.assert_called_once()

    @patch("src.nlp.embedder.Embedder._init_model")
    def test_encode_batch_returns_correct_shape(
        self, mock_init: MagicMock, tmp_path
    ) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        fake_model = MagicMock()
        fake_model.encode.return_value = np.array(
            [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        )
        embedder._model = fake_model
        result = embedder.encode_batch(["a", "b", "c"])
        assert result.shape == (3, 2)

    @patch("src.nlp.embedder.Embedder._init_model")
    def test_get_embedding_dim_returns_int(
        self, mock_init: MagicMock, tmp_path
    ) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        fake_model = MagicMock()
        fake_model.get_sentence_embedding_dimension.return_value = 384
        embedder._model = fake_model
        assert embedder.get_embedding_dim() == 384

    @patch("src.nlp.embedder.Embedder._init_model")
    def test_encode_single_cache_hit_skips_model(
        self, mock_init: MagicMock, tmp_path
    ) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        # Pre-seed the cache.
        text = "cached text"
        cached = np.array([0.5, 0.5, 0.5])
        embedder._write_cache(text, cached)
        # model should not be invoked
        embedder._model = MagicMock()
        result = embedder.encode_single(text)
        assert np.allclose(result, cached)
        embedder._model.encode.assert_not_called()


class TestCachePath:
    def test_cache_path_is_deterministic(self, tmp_path) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        first = embedder._cache_path("same text")
        second = embedder._cache_path("same text")
        assert first == second

    def test_cache_path_differs_for_different_text(self, tmp_path) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        first = embedder._cache_path("text one")
        second = embedder._cache_path("text two")
        assert first != second

    def test_cache_path_uses_cache_dir(self, tmp_path) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        path = embedder._cache_path("hello")
        assert path.startswith(str(tmp_path))
        assert path.endswith(".npy")


class TestCacheIO:
    def test_read_cache_returns_none_on_miss(self, tmp_path) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        assert embedder._read_cache("never cached") is None

    def test_write_and_read_cache_roundtrip(self, tmp_path) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        text = "roundtrip text"
        embedding = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        embedder._write_cache(text, embedding)
        loaded = embedder._read_cache(text)
        assert loaded is not None
        assert np.allclose(loaded, embedding)

    def test_read_cache_returns_none_on_corrupt_file(self, tmp_path) -> None:
        embedder = Embedder(cache_dir=str(tmp_path))
        text = "corrupt text"
        path = embedder._cache_path(text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("not a numpy file")
        assert embedder._read_cache(text) is None

    def test_write_cache_creates_directory(self, tmp_path) -> None:
        nested = tmp_path / "nested" / "cache"
        embedder = Embedder(cache_dir=str(nested))
        embedder._write_cache("some text", np.array([1.0]))
        assert os.path.exists(str(nested))