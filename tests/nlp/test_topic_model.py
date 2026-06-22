"""Tests for the BERTopic TopicModel."""

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.nlp.embedder import Embedder
from src.nlp.topic_model import TopicModel


@pytest.fixture
def embedder() -> Embedder:
    return Embedder(cache_dir="/tmp/embeddings_cache_test_nlp")


@pytest.fixture
def mock_topic_deps():
    """Inject stub modules for bertopic/umap/hdbscan into sys.modules."""
    fake_bertopic = types.ModuleType("bertopic")
    fake_bertopic.BERTopic = MagicMock()
    fake_umap = types.ModuleType("umap")
    fake_umap.UMAP = MagicMock()
    fake_hdbscan = types.ModuleType("hdbscan")
    fake_hdbscan.HDBSCAN = MagicMock()
    fake_countvec_mod = "sklearn.feature_extraction.text"
    # CountVectorizer is part of sklearn which is installed.

    saved = {
        "bertopic": sys.modules.get("bertopic"),
        "umap": sys.modules.get("umap"),
        "hdbscan": sys.modules.get("hdbscan"),
    }
    sys.modules["bertopic"] = fake_bertopic
    sys.modules["umap"] = fake_umap
    sys.modules["hdbscan"] = fake_hdbscan
    yield fake_bertopic, fake_umap, fake_hdbscan
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


class FitTopicModel:
    """A picklable placeholder used for save/load roundtrip tests."""

    def __init__(self) -> None:
        self.fitted = True

    def fit_transform(self, documents):  # noqa: D401 - test stub
        return (["Topic_0"] * len(documents), None)


class TestFit:
    def test_fit_sets_internal_model(self, embedder, mock_topic_deps) -> None:
        fake_bertopic, fake_umap, fake_hdbscan = mock_topic_deps
        fake_instance = MagicMock()
        fake_instance.fit_transform.return_value = (["Topic_0"], None)
        fake_bertopic.BERTopic.return_value = fake_instance

        topic_model = TopicModel(embedder=embedder, min_topic_size=30)
        docs = ["doc one", "doc two", "doc three"]
        topic_model.fit(docs)
        assert topic_model._model is fake_instance

    def test_fit_with_few_documents_handles_edge_case(
        self, embedder, mock_topic_deps
    ) -> None:
        fake_bertopic, fake_umap, fake_hdbscan = mock_topic_deps
        fake_instance = MagicMock()
        fake_instance.fit_transform.return_value = (["Topic_0"], None)
        fake_bertopic.BERTopic.return_value = fake_instance

        topic_model = TopicModel(embedder=embedder, min_topic_size=30)
        # Very few documents (< min_topic_size). Should not raise.
        topic_model.fit(["only one doc"])
        # HDBSCAN min_cluster_size should be clamped down.
        assert fake_hdbscan.HDBSCAN.call_count == 1
        kwargs = fake_hdbscan.HDBSCAN.call_args.kwargs
        assert kwargs["min_cluster_size"] == 1

    def test_hdbscan_uses_correct_parameter_name(
        self, embedder, mock_topic_deps
    ) -> None:
        """Regression: HDBSCAN must receive min_cluster_size, not min_topic_size."""
        fake_bertopic, fake_umap, fake_hdbscan = mock_topic_deps
        fake_instance = MagicMock()
        fake_instance.fit_transform.return_value = (["Topic_0"], None)
        fake_bertopic.BERTopic.return_value = fake_instance

        topic_model = TopicModel(embedder=embedder, min_topic_size=30)
        topic_model.fit(["doc one", "doc two", "doc three"])
        assert fake_hdbscan.HDBSCAN.call_count == 1
        kwargs = fake_hdbscan.HDBSCAN.call_args.kwargs
        # The correct HDBSCAN parameter name is min_cluster_size.
        assert "min_cluster_size" in kwargs
        assert "min_topic_size" not in kwargs
        assert kwargs["min_samples"] == 1
        assert kwargs["prediction_data"] is True


class TestGetTopicInfo:
    def test_get_topic_info_returns_dataframe(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        topic_model._model = MagicMock()
        expected = pd.DataFrame(
            {"Topic": [0, 1], "Count": [10, 5], "Name": ["a", "b"]}
        )
        topic_model._model.get_topic_info.return_value = expected
        result = topic_model.get_topic_info()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2

    def test_get_topic_info_before_fit_raises(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        with pytest.raises(RuntimeError):
            topic_model.get_topic_info()


class TestGetTopicKeywords:
    def test_get_topic_keywords_returns_dict(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        topic_model._topic_keywords = {0: ["python", "aws"], 1: ["cloud"]}
        result = topic_model.get_topic_keywords()
        assert isinstance(result, dict)
        assert result[0] == ["python", "aws"]
        assert result[1] == ["cloud"]


class TestAssignTopics:
    def test_assign_topics_returns_correct_length(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        topic_model._model = MagicMock()
        topic_model._model.transform.return_value = ([0, 1, 0], None)
        result = topic_model.assign_topics(["a", "b", "c"])
        assert len(result) == 3
        assert result == [0, 1, 0]

    def test_assign_topics_before_fit_raises(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        with pytest.raises(RuntimeError):
            topic_model.assign_topics(["a"])


class TestAssignToDb:
    @patch("src.nlp.topic_model.db_connect")
    @patch("src.nlp.topic_model.Session")
    def test_assign_to_db_updates_keywords_json(
        self, mock_session_cls, mock_db_connect
    ) -> None:
        mock_engine = MagicMock()
        mock_db_connect.return_value = mock_engine
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False
        mock_session_cls.return_value = mock_session

        embedder = Embedder(cache_dir="/tmp/embeddings_cache_test_nlp")
        topic_model = TopicModel(embedder=embedder)
        topic_model._model = MagicMock()
        topic_model._model.transform.return_value = ([0, 1], None)
        topic_model._topic_keywords = {0: ["python"], 1: ["cloud"]}

        df = pd.DataFrame(
            {"id": [100, 200], "cleaned_description": ["doc one", "doc two"]}
        )
        mapping = topic_model.assign_to_db(df)
        assert mapping == {100: 0, 200: 1}
        # assign_to_db also populates the topic-to-doc mapping.
        assert topic_model._topic_docs == {0: [100], 1: [200]}
        # Two updates issued against the session.
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()
        mock_engine.dispose.assert_called_once()

    def test_assign_to_db_missing_columns_raises(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        with pytest.raises(ValueError):
            topic_model.assign_to_db(pd.DataFrame({"id": [1]}))

    def test_assign_to_db_empty_returns_empty(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        topic_model._model = MagicMock()
        df = pd.DataFrame({"id": [], "cleaned_description": []})
        assert topic_model.assign_to_db(df) == {}


class TestSaveLoad:
    def test_save_and_load_roundtrip(self, embedder, tmp_path) -> None:
        model_path = str(tmp_path / "model.pkl")
        keywords_path = str(tmp_path / "kw.json")
        coherence_path = str(tmp_path / "coherence.json")
        docs_path = str(tmp_path / "docs.json")

        topic_model = TopicModel(embedder=embedder)
        # Use a picklable stub instead of MagicMock (mocks cannot be pickled).
        stub = FitTopicModel()
        topic_model._model = stub
        topic_model._topic_keywords = {0: ["python"]}

        # Patch all artifact paths to tmp_path so the test never reads or
        # writes the real on-disk model artifacts.
        with patch.object(TopicModel, "DEFAULT_KEYWORDS_PATH", keywords_path), \
                patch.object(TopicModel, "DEFAULT_COHERENCE_PATH", coherence_path), \
                patch.object(TopicModel, "DEFAULT_DOCS_PATH", docs_path):
            topic_model.save(model_path)
            assert os.path.exists(model_path)
            assert os.path.exists(keywords_path)

            loaded = TopicModel.load(model_path, embedder=embedder)
            assert isinstance(loaded._model, FitTopicModel)
            assert loaded._model.fitted is True
            assert loaded._topic_keywords == {0: ["python"]}
            assert loaded._coherence == {}
            assert loaded._topic_docs == {}

    def test_keywords_json_is_serializable(self, embedder, tmp_path) -> None:
        keywords_path = str(tmp_path / "kw.json")
        coherence_path = str(tmp_path / "coherence.json")
        docs_path = str(tmp_path / "docs.json")
        with patch.object(TopicModel, "DEFAULT_KEYWORDS_PATH", keywords_path), \
                patch.object(TopicModel, "DEFAULT_COHERENCE_PATH", coherence_path), \
                patch.object(TopicModel, "DEFAULT_DOCS_PATH", docs_path):
            topic_model = TopicModel(embedder=embedder)
            topic_model._model = FitTopicModel()
            topic_model._topic_keywords = {0: ["python", "aws"], -1: []}
            topic_model.save(str(tmp_path / "model.pkl"))
        with open(keywords_path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        assert loaded["0"] == ["python", "aws"]

    def test_save_and_load_persists_coherence_and_docs(
        self, embedder, tmp_path
    ) -> None:
        model_path = str(tmp_path / "model.pkl")
        keywords_path = str(tmp_path / "kw.json")
        coherence_path = str(tmp_path / "coherence.json")
        docs_path = str(tmp_path / "docs.json")

        topic_model = TopicModel(embedder=embedder)
        topic_model._model = FitTopicModel()
        topic_model._topic_keywords = {0: ["python"]}
        topic_model._coherence = {0: 0.85, 1: 0.72}
        topic_model._topic_docs = {0: [1, 2], 1: [3]}

        with patch.object(TopicModel, "DEFAULT_KEYWORDS_PATH", keywords_path), \
                patch.object(TopicModel, "DEFAULT_COHERENCE_PATH", coherence_path), \
                patch.object(TopicModel, "DEFAULT_DOCS_PATH", docs_path):
            topic_model.save(model_path)
            assert os.path.exists(coherence_path)
            assert os.path.exists(docs_path)
            loaded = TopicModel.load(model_path, embedder=embedder)

        assert loaded._coherence == {0: 0.85, 1: 0.72}
        assert loaded._topic_docs == {0: [1, 2], 1: [3]}


class TestComputeCoherence:
    def test_compute_coherence_basic(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        # Two tight clusters of two points each.
        embeddings = np.array(
            [
                [1.0, 0.0],
                [0.95, 0.05],
                [0.0, 1.0],
                [0.05, 0.95],
            ],
            dtype=np.float32,
        )
        assignments = [0, 0, 1, 1]
        coherence = topic_model.compute_coherence(embeddings, assignments)
        assert set(coherence.keys()) == {0, 1}
        assert 0.0 < coherence[0] <= 1.0
        assert 0.0 < coherence[1] <= 1.0

    def test_compute_coherence_skips_topic_minus_one(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        coherence = topic_model.compute_coherence(embeddings, [-1, 0])
        assert -1 not in coherence
        # Topic 0 has only one doc -> coherence 0.0.
        assert coherence == {0: 0.0}

    def test_compute_coherence_single_doc_topic_is_zero(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        embeddings = np.array(
            [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]], dtype=np.float32
        )
        coherence = topic_model.compute_coherence(embeddings, [0, 0, 1])
        assert coherence[1] == 0.0

    def test_compute_coherence_length_mismatch_raises(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
        with pytest.raises(ValueError):
            topic_model.compute_coherence(embeddings, [0, 1])

    def test_get_coherence_returns_cached(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        embeddings = np.array(
            [[1.0, 0.0], [0.9, 0.1]], dtype=np.float32
        )
        topic_model.compute_coherence(embeddings, [0, 0])
        cached = topic_model.get_coherence()
        assert 0 in cached
        assert cached[0] == topic_model._coherence[0]

    def test_get_coherence_empty_when_unset(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        assert topic_model.get_coherence() == {}


class TestGetTopicDocs:
    def test_get_topic_docs_empty_when_unset(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        assert topic_model.get_topic_docs(0) == []

    def test_get_topic_docs_returns_populated_list(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        topic_model._topic_docs = {0: [10, 20], 1: [30]}
        assert topic_model.get_topic_docs(0) == [10, 20]
        assert topic_model.get_topic_docs(1) == [30]
        assert topic_model.get_topic_docs(99) == []

    def test_get_topic_docs_returns_copy_not_reference(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        topic_model._topic_docs = {0: [1, 2]}
        result = topic_model.get_topic_docs(0)
        result.append(999)
        assert topic_model._topic_docs[0] == [1, 2]


class TestInitDefaults:
    def test_default_min_topic_size_is_30(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        assert topic_model.min_topic_size == 30

    def test_init_initializes_coherence_and_docs(self, embedder) -> None:
        topic_model = TopicModel(embedder=embedder)
        assert topic_model._coherence == {}
        assert topic_model._topic_docs == {}


class TestConstants:
    def test_default_paths_are_constants(self) -> None:
        assert TopicModel.DEFAULT_MODEL_PATH == "src/nlp/models/bertopic_model.pkl"
        assert TopicModel.DEFAULT_KEYWORDS_PATH == "src/nlp/models/topic_keywords.json"
        assert TopicModel.DEFAULT_COHERENCE_PATH == "src/nlp/models/topic_coherence.json"
        assert TopicModel.DEFAULT_DOCS_PATH == "src/nlp/models/topic_docs.json"