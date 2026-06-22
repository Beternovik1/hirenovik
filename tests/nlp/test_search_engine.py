"""Tests for the FAISS SearchEngine."""

import os
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.nlp.embedder import Embedder
from src.nlp.search_engine import SearchEngine


@pytest.fixture
def embedder() -> Embedder:
    return Embedder(cache_dir="/tmp/embeddings_cache_test_nlp_search")


@pytest.fixture
def mock_faiss():
    """Inject a stub faiss module into sys.modules."""
    fake_faiss = types.ModuleType("faiss")

    class _IndexFlatIP:
        def __init__(self, dim: int) -> None:
            self.dim = dim
            self.vectors: np.ndarray = np.empty((0, dim), dtype=np.float32)

        def add(self, matrix: np.ndarray) -> None:
            self.vectors = np.vstack([self.vectors, np.asarray(matrix, dtype=np.float32)])

        def search(self, query: np.ndarray, k: int):
            matrix = self.vectors
            n = matrix.shape[0]
            if n == 0:
                return (
                    np.zeros((1, 0), dtype=np.float32),
                    np.full((1, k), -1, dtype=np.int64),
                )
            sims = (matrix @ query.reshape(-1)).reshape(-1)
            k_eff = min(k, n)
            order = np.argsort(-sims)[:k_eff]
            scores = sims[order].astype(np.float32).reshape(1, -1)
            indices = order.astype(np.int64).reshape(1, -1)
            # Pad with -1 if needed.
            if k_eff < k:
                pad_scores = np.full((1, k - k_eff), -1.0, dtype=np.float32)
                pad_idx = np.full((1, k - k_eff), -1, dtype=np.int64)
                scores = np.hstack([scores, pad_scores])
                indices = np.hstack([indices, pad_idx])
            return scores, indices

    fake_faiss.IndexFlatIP = _IndexFlatIP

    @staticmethod
    def _write_index(index, path):
        with open(path, "wb") as fh:
            fh.write(b"stub-index")

    @staticmethod
    def _read_index(path):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        return _IndexFlatIP(3)

    fake_faiss.write_index = _write_index
    fake_faiss.read_index = _read_index

    saved = sys.modules.get("faiss")
    sys.modules["faiss"] = fake_faiss
    yield fake_faiss
    if saved is None:
        sys.modules.pop("faiss", None)
    else:
        sys.modules["faiss"] = saved


class TestBuildIndex:
    def test_build_index_creates_faiss_index(self, embedder, mock_faiss, monkeypatch) -> None:
        documents = ["doc one", "doc two", "doc three"]
        doc_ids = [10, 20, 30]

        engine = SearchEngine(embedder=embedder)
        # Pre-load the embedder with a fake model to avoid downloading weights.
        fake_model = MagicMock()
        fake_model.encode.return_value = np.array(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(documents, doc_ids)
        assert engine._index is not None
        assert engine._index.vectors.shape == (3, 3)

    def test_build_index_mismatched_lengths_raises(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        with pytest.raises(ValueError):
            engine.build_index(["a", "b"], [1])

    def test_build_index_normalizes_embeddings(self, embedder, mock_faiss) -> None:
        documents = ["doc one", "doc two"]
        doc_ids = [1, 2]
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.return_value = np.array(
            [[3.0, 4.0, 0.0], [0.0, 5.0, 12.0]], dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(documents, doc_ids)
        norms = np.linalg.norm(engine._embeddings, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-6)

    def test_build_index_deduplicates_by_job_id(self, embedder, mock_faiss) -> None:
        # Same job_id appearing multiple times must be collapsed to one vector.
        documents = ["doc one", "doc one dup", "doc two"]
        doc_ids = [10, 10, 20]
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        preset = np.array(
            [[1.0, 0.0, 0.0], [0.5, 0.5, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32
        )
        # Return an array row count matching the (post-dedup) input length.
        fake_model.encode.side_effect = lambda texts, **kwargs: preset[: len(texts)]
        engine.embedder._model = fake_model
        engine.build_index(documents, doc_ids)
        # Only two unique ids remain; first occurrence wins for duplicates.
        assert engine._id_mapping == [10, 20]
        assert engine._documents == ["doc one", "doc two"]
        assert engine._embeddings.shape == (2, 3)

    def test_build_index_preserves_order_for_unique_ids(
        self, embedder, mock_faiss
    ) -> None:
        documents = ["doc a", "doc b", "doc c"]
        doc_ids = [100, 200, 300]
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.return_value = np.array(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(documents, doc_ids)
        assert engine._id_mapping == [100, 200, 300]


class TestQuery:
    def _build_engine(self, embedder, mock_faiss) -> SearchEngine:
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.side_effect = lambda texts, **kwargs: np.array(
            [[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(["doc one", "doc two", "doc three"], [10, 20, 30])
        return engine

    def test_query_returns_correct_k_results(self, embedder, mock_faiss) -> None:
        engine = self._build_engine(embedder, mock_faiss)
        results = engine.query("anything", k=2)
        assert len(results) == 2
        for r in results:
            assert "job_id" in r and "score" in r

    def test_query_results_sorted_by_score(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.side_effect = lambda texts, **kwargs: np.array(
            [[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32
        )
        engine.embedder._model = fake_model
        # Add vectors with varying similarities so search ranking is non-trivial.
        engine._index = mock_faiss.IndexFlatIP(3)
        engine._id_mapping = [10, 20, 30]
        engine._index.add(
            np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [1.0, 1.0, 0.0]], dtype=np.float32)
        )
        # Query vector close to first document.
        results = engine.query("x", k=3)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_query_with_empty_index_raises(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        with pytest.raises(RuntimeError):
            engine.query("anything")


class TestExpand:
    def test_expand_runs_multiple_rounds(self, embedder, mock_faiss, monkeypatch) -> None:
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.side_effect = lambda texts, **kwargs: np.array(
            [[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(["doc one", "doc two", "doc three"], [1, 2, 3])

        calls = {"count": 0}
        original = engine._search_vector

        def counting_search(vector, k):
            calls["count"] += 1
            return original(vector, k)

        monkeypatch.setattr(engine, "_search_vector", counting_search)
        engine.expand("seed", rounds=2, threshold=0.0, top_k=3)
        # At minimum 2 round searches + 1 seed search.
        assert calls["count"] >= 3

    def test_expand_deduplicates_results(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.side_effect = lambda texts, **kwargs: np.array(
            [[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(["doc one", "doc two"], [1, 2])
        results = engine.expand("seed", rounds=3, threshold=0.0, top_k=2)
        job_ids = [r["job_id"] for r in results]
        assert len(job_ids) == len(set(job_ids))


class TestSearchByKeywords:
    def test_search_by_keywords_averages_embeddings(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        fake_model = MagicMock()
        fake_model.encode.side_effect = lambda texts, **kwargs: np.array(
            [[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(["doc one", "doc two"], [1, 2])
        results = engine.search_by_keywords(["python", "aws"], k=2)
        assert len(results) <= 2

    def test_search_by_keywords_empty_returns_empty(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        assert engine.search_by_keywords([], k=5) == []


class TestSaveLoad:
    def test_save_and_load_roundtrip(self, embedder, mock_faiss, tmp_path) -> None:
        engine = SearchEngine(
            embedder=embedder,
            index_path=str(tmp_path / "index.bin"),
            id_mapping_path=str(tmp_path / "mapping.json"),
        )
        fake_model = MagicMock()
        fake_model.encode.side_effect = lambda texts, **kwargs: np.array(
            [[1.0, 0.0, 0.0]] * len(texts), dtype=np.float32
        )
        engine.embedder._model = fake_model
        engine.build_index(["doc one", "doc two"], [1, 2])
        engine.save()
        assert os.path.exists(engine.index_path)
        assert os.path.exists(engine.id_mapping_path)

        loaded = SearchEngine.load(
            embedder,
            index_path=engine.index_path,
            id_mapping_path=engine.id_mapping_path,
        )
        assert loaded._index is not None
        assert loaded._id_mapping == [1, 2]

    def test_save_without_index_raises(self, embedder, mock_faiss) -> None:
        engine = SearchEngine(embedder=embedder)
        with pytest.raises(RuntimeError):
            engine.save()