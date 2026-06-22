"""NLP pipeline orchestrator.

Coordinates the NLP pipeline stages (preprocess -> embed -> topic_model
-> build_index -> compute_trends) into a single callable so it can be
invoked from CLI (``python -m src.nlp.pipeline``) or from FastAPI.

Each stage runs independently and writes its artifacts under
``src/nlp/models/``. The :func:`run_pipeline` function accepts a
``steps`` list to run only a subset; omitted steps are skipped without
raising. The return value is a status dict with timing and path
metadata suitable for logging or API responses.
"""

import logging
import os
import time
from typing import Optional

import numpy as np
import pandas as pd

from src.nlp.embedder import Embedder, DEFAULT_CACHE_DIR
from src.nlp.preprocess import TextPreprocessor
from src.nlp.search_engine import SearchEngine
from src.nlp.topic_model import TopicModel
from src.nlp.trends import TopicTrends

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

#: All supported pipeline stages, in execution order.
DEFAULT_STEPS: list[str] = [
    "preprocess",
    "embed",
    "topic_model",
    "build_index",
    "compute_trends",
]

#: Directory where model artifacts are persisted.
MODELS_DIR = "src/nlp/models"


def _ensure_models_dir() -> None:
    """Create the model artifacts directory if it does not exist."""
    os.makedirs(MODELS_DIR, exist_ok=True)


def _run_preprocess() -> pd.DataFrame:
    """Load and clean raw job descriptions from Supabase.

    Returns:
        Cleaned descriptions DataFrame with a ``cleaned_description``
        column.
    """
    logger.info("Step 'preprocess': starting")
    preprocessor = TextPreprocessor()
    df = preprocessor.load_and_clean()
    logger.info("Step 'preprocess': cleaned %d descriptions", len(df))
    return df


def _run_embed(
    preprocessor: TextPreprocessor,
    df: Optional[pd.DataFrame] = None,
) -> tuple[Embedder, np.ndarray, list[str]]:
    """Encode all cleaned descriptions and return the embedder.

    Args:
        preprocessor: TextPreprocessor used to refresh data if ``df``
            was not provided.
        df: Optional pre-cleaned DataFrame. If ``None``, the
            preprocessor's :meth:`load_and_clean` is called.

    Returns:
        Tuple of (embedder, embeddings matrix, list of cleaned documents).
    """
    logger.info("Step 'embed': starting")
    if df is None:
        df = preprocessor.load_and_clean()
    documents = df["cleaned_description"].tolist() if len(df) > 0 else []
    embedder = Embedder(cache_dir=DEFAULT_CACHE_DIR)
    if documents:
        embeddings = embedder.encode_batch(documents, show_progress=True)
        embeddings = np.asarray(embeddings)
    else:
        embeddings = np.empty((0, 0), dtype=np.float32)
    logger.info("Step 'embed': produced %d embeddings", len(documents))
    return embedder, embeddings, documents


def _run_topic_model(
    embedder: Embedder,
    documents: list[str],
    df: pd.DataFrame,
) -> TopicModel:
    """Fit a topic model, save it, and assign topics to ``df``.

    Args:
        embedder: Embedder bound to the topic model.
        documents: Cleaned description strings in row order with ``df``.
        df: DataFrame whose ``topic_id`` column is populated in place.

    Returns:
        Fitted :class:`TopicModel`.
    """
    logger.info("Step 'topic_model': starting")
    topic_model = TopicModel(embedder=embedder, min_topic_size=30)
    if documents:
        topic_model.fit(documents)
        topics = topic_model.assign_topics(documents)
        df["topic_id"] = topics
        # Populate the topic-to-document mapping so the representative-jobs
        # endpoint can resolve topic members after the model is reloaded.
        job_ids = [int(i) for i in df["id"].tolist()] if len(df) > 0 else []
        topic_docs: dict[int, list[int]] = {}
        for job_id, topic_id in zip(job_ids, topics):
            topic_docs.setdefault(int(topic_id), []).append(int(job_id))
        topic_model._topic_docs = topic_docs
        topic_model.save()
    else:
        df["topic_id"] = []
        topic_model._model = None
    logger.info("Step 'topic_model': assigned topics to %d documents", len(documents))
    return topic_model


def _run_build_index(
    embedder: Embedder,
    topic_model: TopicModel,
    df: pd.DataFrame,
) -> SearchEngine:
    """Build and persist a FAISS search index over cleaned descriptions.

    Returns:
        Built :class:`SearchEngine`.
    """
    logger.info("Step 'build_index': starting")
    documents = df["cleaned_description"].tolist() if len(df) > 0 else []
    doc_ids = [int(i) for i in df["id"].tolist()] if len(df) > 0 else []
    engine = SearchEngine(embedder=embedder)
    if documents:
        engine.build_index(documents, doc_ids)
        engine.save()
    logger.info("Step 'build_index': indexed %d documents", len(documents))
    return engine


def _run_compute_trends(topic_model: TopicModel, df: pd.DataFrame) -> pd.DataFrame:
    """Compute and persist weekly topic trends.

    Returns:
        Trends DataFrame.
    """
    logger.info("Step 'compute_trends': starting")
    trends = TopicTrends(topic_model=topic_model)
    if "topic_id" in df.columns and len(df) > 0:
        trends_df = trends.compute_weekly_trends(df)
        trends.save_trends(trends_df)
    else:
        trends_df = pd.DataFrame(
            columns=["week", "topic_id", "count", "avg_salary", "pct_change", "is_trending"]
        )
    logger.info("Step 'compute_trends': produced %d trend rows", len(trends_df))
    return trends_df


def run_pipeline(steps: Optional[list[str]] = None) -> dict:
    """Run the NLP pipeline.

    Args:
        steps: Subset of :data:`DEFAULT_STEPS` to execute. ``None``
            runs every stage in order. Unknown stages are ignored.

    Returns:
        Status dict with keys ``status``, ``steps_run``,
        ``skipped``, ``artifacts``, and ``timings`` (in seconds).
    """
    requested = steps if steps is not None else list(DEFAULT_STEPS)
    steps_run: list[str] = []
    skipped: list[str] = [s for s in DEFAULT_STEPS if s not in requested]
    timings: dict[str, float] = {}
    artifacts: dict[str, object] = {}

    _ensure_models_dir()

    df: Optional[pd.DataFrame] = None
    embedder: Optional[Embedder] = None
    embeddings: Optional[np.ndarray] = None
    documents: list[str] = []
    topic_model: Optional[TopicModel] = None
    search_engine: Optional[SearchEngine] = None

    def _time(stage: str, fn) -> None:
        start = time.perf_counter()
        logger.info("Pipeline step '%s' starting", stage)
        result = fn()
        elapsed = time.perf_counter() - start
        timings[stage] = round(elapsed, 4)
        logger.info("Pipeline step '%s' finished in %.3fs", stage, elapsed)
        artifacts[stage] = result

    if "preprocess" in requested:
        _time("preprocess", _run_preprocess)
        df = artifacts["preprocess"]
    if "embed" in requested:
        _time("embed", lambda: _run_embed(TextPreprocessor(), df))
        embedder, embeddings, documents = artifacts["embed"]

    if "topic_model" in requested:
        if df is None or embedder is None:
            logger.warning("Step 'topic_model' skipped: prerequisites missing")
        else:
            _time("topic_model", lambda: _run_topic_model(embedder, documents, df))
            topic_model = artifacts["topic_model"]

    if "build_index" in requested:
        if df is None or embedder is None:
            logger.warning("Step 'build_index' skipped: prerequisites missing")
        else:
            _time("build_index", lambda: _run_build_index(embedder, topic_model, df))
            search_engine = artifacts["build_index"]

            # Compute per-topic coherence once both the topic model and the
            # search index are available, then re-save the topic model so the
            # coherence artifact is persisted to disk.
            if topic_model is not None and search_engine is not None:
                embeddings = getattr(search_engine, "_embeddings", None)
                if (
                    embeddings is not None
                    and "topic_id" in df.columns
                    and len(df) > 0
                ):
                    coherence = topic_model.compute_coherence(
                        np.asarray(embeddings),
                        df["topic_id"].astype(int).tolist(),
                    )
                    logger.info(
                        "Computed coherence for %d topics", len(coherence)
                    )
                    topic_model.save()

    if "compute_trends" in requested:
        if df is None or topic_model is None:
            logger.warning("Step 'compute_trends' skipped: prerequisites missing")
        else:
            _time("compute_trends", lambda: _run_compute_trends(topic_model, df))
            artifacts["compute_trends"] = artifacts["compute_trends"]

    steps_run = [s for s in requested if s in timings]
    return {
        "status": "ok" if steps_run else "skipped",
        "steps_run": steps_run,
        "skipped": skipped,
        "artifacts": list(artifacts.keys()),
        "timings": timings,
    }


if __name__ == "__main__":  # pragma: no cover
    run_pipeline()