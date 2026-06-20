"""Integration tests for the NLP pipeline orchestrator."""

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.nlp import pipeline as nlp_pipeline


@pytest.fixture
def fake_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3],
            "cleaned_description": ["doc one", "doc two", "doc three"],
            "date_scraped": pd.to_datetime(
                ["2026-05-04", "2026-05-11", "2026-05-04"]
            ),
            "salary_min": [25000.0, 30000.0, np.nan],
            "salary_max": [35000.0, 40000.0, np.nan],
        }
    )


@pytest.fixture
def mocks(fake_df):
    """Patch all stage helpers and key dependencies with MagicMocks."""
    fake_embedder = MagicMock()
    fake_embeddings = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
    fake_documents = fake_df["cleaned_description"].tolist()
    fake_topic_model = MagicMock()
    fake_search_engine = MagicMock()
    fake_trends_df = pd.DataFrame(
        {"week": ["2026-W19"], "topic_id": [0], "count": [3]}
    )

    targets = {
        "_run_preprocess": MagicMock(return_value=fake_df),
        "_run_embed": MagicMock(
            return_value=(fake_embedder, fake_embeddings, fake_documents)
        ),
        "_run_topic_model": MagicMock(return_value=fake_topic_model),
        "_run_build_index": MagicMock(return_value=fake_search_engine),
        "_run_compute_trends": MagicMock(return_value=fake_trends_df),
        "_ensure_models_dir": MagicMock(),
    }
    patchers = [patch(f"src.nlp.pipeline.{name}", target) for name, target in targets.items()]
    for p in patchers:
        p.start()

    yield {
        "embedder": fake_embedder,
        "embeddings": fake_embeddings,
        "documents": fake_documents,
        "df": fake_df,
        "topic_model": fake_topic_model,
        "search_engine": fake_search_engine,
        "trends_df": fake_trends_df,
        "targets": targets,
    }
    for p in patchers:
        p.stop()


class TestRunPipelineAllSteps:
    def test_run_pipeline_with_all_steps(self, mocks) -> None:
        result = nlp_pipeline.run_pipeline()
        assert result["status"] == "ok"
        assert set(result["steps_run"]) == set(nlp_pipeline.DEFAULT_STEPS)
        mocks["targets"]["_run_preprocess"].assert_called_once()
        mocks["targets"]["_run_embed"].assert_called_once()
        mocks["targets"]["_run_topic_model"].assert_called_once()
        mocks["targets"]["_run_build_index"].assert_called_once()
        mocks["targets"]["_run_compute_trends"].assert_called_once()
        # Confirm topic_model received the embedder from the embed step.
        args = mocks["targets"]["_run_topic_model"].call_args.args
        assert args[0] is mocks["embedder"]

    def test_run_pipeline_with_subset_steps(self, mocks) -> None:
        result = nlp_pipeline.run_pipeline(steps=["preprocess", "embed"])
        assert "preprocess" in result["steps_run"]
        assert "embed" in result["steps_run"]
        # Topic-model/index/trends should be skipped, not executed.
        mocks["targets"]["_run_topic_model"].assert_not_called()
        mocks["targets"]["_run_build_index"].assert_not_called()
        mocks["targets"]["_run_compute_trends"].assert_not_called()
        assert set(result["skipped"]) == {"topic_model", "build_index", "compute_trends"}

    def test_run_pipeline_subset_skips_dep_missing(self, mocks) -> None:
        # If we request only topic_model (skipping prerequisites), it must skip.
        result = nlp_pipeline.run_pipeline(steps=["topic_model"])
        assert result["status"] in ("ok", "skipped")
        mocks["targets"]["_run_topic_model"].assert_not_called()


class TestReturnType:
    def test_run_pipeline_returns_status_dict(self, mocks) -> None:
        result = nlp_pipeline.run_pipeline()
        assert isinstance(result, dict)
        for key in ("status", "steps_run", "skipped", "artifacts", "timings"):
            assert key in result
        assert isinstance(result["timings"], dict)
        for stage, elapsed in result["timings"].items():
            assert isinstance(stage, str)
            assert isinstance(elapsed, float)


class TestLogging:
    def test_run_pipeline_logs_step_timing(self, mocks, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="src.nlp.pipeline"):
            nlp_pipeline.run_pipeline()
        messages = [r.getMessage() for r in caplog.records]
        started = [m for m in messages if "starting" in m]
        finished = [m for m in messages if "finished in" in m]
        # Each executed step logs both a start and finish.
        for stage in nlp_pipeline.DEFAULT_STEPS:
            assert any(stage in m for m in started)
            assert any(stage in m for m in finished)


class TestModelsDir:
    def test_run_pipeline_creates_models_directory(self, mocks) -> None:
        mocks["targets"]["_ensure_models_dir"].reset_mock()
        nlp_pipeline.run_pipeline()
        mocks["targets"]["_ensure_models_dir"].assert_called_once()


class TestEmptyDescriptions:
    def test_pipeline_handles_empty_descriptions(self, fake_df) -> None:
        empty_df = fake_df.iloc[0:0].copy()
        with patch("src.nlp.pipeline._run_preprocess", return_value=empty_df), \
                patch(
                    "src.nlp.pipeline._run_embed",
                    return_value=(MagicMock(), np.empty((0, 0)), []),
                ), \
                patch("src.nlp.pipeline._run_topic_model") as mock_topic, \
                patch("src.nlp.pipeline._run_build_index") as mock_index, \
                patch("src.nlp.pipeline._run_compute_trends") as mock_trends, \
                patch("src.nlp.pipeline._ensure_models_dir"):
            result = nlp_pipeline.run_pipeline()
        # No exception; topic_model and others still invoked (empty branches).
        assert result["status"] == "ok"
        mock_topic.assert_called_once()
        mock_index.assert_called_once()
        mock_trends.assert_called_once()