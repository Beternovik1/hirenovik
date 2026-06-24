"""NLP pipeline orchestrator.

Coordinates the NLP pipeline stages (preprocess -> embed ->
detect_outliers -> topic_model -> build_index -> compute_trends) into
a single callable so it can be invoked from CLI
(``python -m src.nlp.pipeline``) or from FastAPI.

Each stage runs independently and writes its artifacts under
``src/nlp/models/``. The :func:`run_pipeline` function accepts a
``steps`` list to run only a subset; omitted steps are skipped without
raising. The return value is a status dict with timing and path
metadata suitable for logging or API responses.
"""

import json
import logging
import os
import time
from pathlib import Path
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
    "detect_outliers",
    "topic_model",
    "build_index",
    "compute_trends",
]

#: Directory where model artifacts are persisted.
MODELS_DIR = "src/nlp/models"

#: Directory where outlier artifacts are persisted.
OUTLIERS_DIR = os.path.join(MODELS_DIR, "outliers")


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


def _run_detect_outliers(
    embedder: Embedder,
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Detect and separate outlier documents before topic modeling.

    Args:
        embedder: Embedder whose loaded SentenceTransformer is reused
            by the :class:`OutlierDetector` so embeddings are not
            recomputed from scratch.
        df: DataFrame with a ``cleaned_description`` column.

    Returns:
        Tuple of ``(df_clean, df_outliers, embeddings_clean)`` where
        ``embeddings_clean`` is aligned with ``df_clean`` rows.
    """
    from src.nlp.outlier_detector import OutlierDetector
    from src.nlp.wordcloud_gen import OutlierVisualizer

    logger.info("Step 'detect_outliers': starting")
    os.makedirs(OUTLIERS_DIR, exist_ok=True)

    detector = OutlierDetector(
        embedding_model=embedder._model,
        contamination=0.05,
    )
    df_clean, df_outliers, embeddings_clean = detector.run(df)

    # Persist outlier statistics.
    stats = {
        "total_documents": int(len(df)),
        "outliers": int(len(df_outliers)),
        "clean": int(len(df_clean)),
        "outlier_pct": round(
            (len(df_outliers) / len(df) * 100) if len(df) else 0.0, 2
        ),
    }
    stats_path = Path(OUTLIERS_DIR) / "outlier_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    logger.info("Saved outlier stats to %s: %s", stats_path, stats)

    # Persist outlier document ids for later inspection.
    outlier_ids = df_outliers["id"].tolist() if "id" in df_outliers.columns else []
    docs_path = Path(OUTLIERS_DIR) / "outlier_docs.json"
    docs_path.write_text(
        json.dumps(outlier_ids, indent=2), encoding="utf-8"
    )
    logger.info("Saved %d outlier doc ids to %s", len(outlier_ids), docs_path)

    # Generate visualisations.
    visualizer = OutlierVisualizer()
    visualizer.generate(df_outliers, Path(OUTLIERS_DIR))
    logger.info("Saved outlier visualisations to %s", OUTLIERS_DIR)

    logger.info(
        "Step 'detect_outliers': %d outliers (%.1f%%), %d clean",
        len(df_outliers),
        stats["outlier_pct"],
        len(df_clean),
    )
    return df_clean, df_outliers, embeddings_clean


def _cascade_noise_docs(
    topic_model: "TopicModel",
    embedder: "Embedder",
    df: pd.DataFrame,
    noise_mask: "pd.Series",
    noise_count: int,
    job_ids: list[int],
) -> None:
    """Second-stage BERTopic on noise docs to rescue small clusters.

    When the main HDBSCAN pass leaves many docs in topic -1, this
    function fits a separate BERTopic with ``min_topic_size=10`` on
    just the noise documents. Rescued docs are reassigned with topic
    IDs offset above the main pass maximum, and their keywords are
    merged into ``topic_model._topic_keywords``.

    Args:
        topic_model: Main-pass TopicModel whose keywords are extended.
        embedder: Shared embedder whose SentenceTransformer is reused.
        df: Full DataFrame — ``topic_id`` column is mutated in place.
        noise_mask: Boolean mask of ``df`` rows where topic_id == -1.
        noise_count: Pre-computed count (``noise_mask.sum()``).
        job_ids: Full list of job IDs aligned with ``df`` rows.
    """
    logger.info(
        "Cascade stage 2: reclustering %d noise docs (min_topic_size=10)",
        noise_count,
    )
    from bertopic import BERTopic
    from bertopic.representation import MaximalMarginalRelevance
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP
    from hdbscan import HDBSCAN

    noise_df = df.loc[noise_mask]
    noise_docs = noise_df["cleaned_description"].tolist()

    # Simpler UMAP for the residual noise space: fewer neighbours and
    # dimensions since these docs are already the hard leftovers.
    cascade_umap = UMAP(
        n_neighbors=5,
        n_components=2,
        metric="cosine",
        random_state=42,
        low_memory=False,
    )
    cascade_hdbscan = HDBSCAN(
        min_cluster_size=10,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    cascade_vectorizer = CountVectorizer(
        ngram_range=(1, 2),
        max_df=0.8,
        min_df=3,
    )
    cascade_mmr = MaximalMarginalRelevance(diversity=0.7)

    cascade = BERTopic(
        embedding_model=embedder._model,
        umap_model=cascade_umap,
        hdbscan_model=cascade_hdbscan,
        vectorizer_model=cascade_vectorizer,
        representation_model=cascade_mmr,
        verbose=False,
        calculate_probabilities=False,
    )
    cascade_topics, _ = cascade.fit_transform(noise_docs)

    # Offset cascade topic IDs to avoid colliding with main-pass topics.
    existing_max = max(
        (int(t) for t in df["topic_id"].unique() if int(t) >= 0),
        default=-1,
    )
    offset = existing_max + 1

    rescued = 0
    for (idx, _), cascade_tid in zip(noise_df.iterrows(), cascade_topics):
        if cascade_tid >= 0:
            df.at[idx, "topic_id"] = cascade_tid + offset
            rescued += 1

    # Merge cascade keywords into the main topic model's keyword store.
    cascade_kw = cascade.get_topics()
    cascade_topic_count = 0
    for cascade_tid, words in cascade_kw.items():
        if cascade_tid >= 0:
            topic_model._topic_keywords[cascade_tid + offset] = [
                w for w, _ in words
            ]
            cascade_topic_count += 1

    logger.info(
        "Cascade rescued %d docs into %d new topics (offset %d, "
        "%d docs remain in -1)",
        rescued,
        cascade_topic_count,
        offset,
        noise_count - rescued,
    )


def _run_topic_model(
    embedder: Embedder,
    documents: list[str],
    df: pd.DataFrame,
    df_clean: Optional[pd.DataFrame] = None,
) -> TopicModel:
    """Fit a topic model, save it, and assign topics to ``df``.

    When ``df_clean`` is provided (from the outlier detection step),
    the topic model is fit only on the clean (non-outlier) documents
    and outliers receive ``topic_id = -1``. Otherwise the model is fit
    and assigned on the full ``documents`` list.

    Args:
        embedder: Embedder bound to the topic model.
        documents: Cleaned description strings in row order with ``df``.
        df: DataFrame whose ``topic_id`` column is populated in place.
        df_clean: Optional outlier-free DataFrame. When provided, the
            model is fit on its ``cleaned_description`` values instead
            of the full ``documents`` list.

    Returns:
        Fitted :class:`TopicModel`.
    """
    logger.info("Step 'topic_model': starting")
    topic_model = TopicModel(embedder=embedder, min_topic_size=15)

    fit_documents = documents
    if df_clean is not None and len(df_clean) > 0:
        fit_documents = df_clean["cleaned_description"].tolist()
        logger.info(
            "Fitting topic model on %d clean documents (excluded %d outliers)",
            len(fit_documents),
            len(documents) - len(fit_documents),
        )

    if fit_documents:
        topic_model.fit(fit_documents)

        if df_clean is not None and len(df_clean) > 0:
            # Model was fitted on clean docs only. Assign topics only to
            # clean docs and give outliers topic_id=-1. This avoids NaN
            # errors in HDBSCAN approximate_predict when outlier embeddings
            # fall outside the fitted UMAP+HDBSCAN manifold.
            topics_clean = topic_model.assign_topics(fit_documents)
            clean_topic_map = dict(
                zip(df_clean["id"].tolist(), topics_clean)
            )
            job_ids = [int(i) for i in df["id"].tolist()]
            topics = [clean_topic_map.get(int(jid), -1) for jid in job_ids]
        else:
            topics = topic_model.assign_topics(documents)

        df["topic_id"] = topics
        # Populate the topic-to-document mapping so the representative-jobs
        # endpoint can resolve topic members after the model is reloaded.
        job_ids = [int(i) for i in df["id"].tolist()] if len(df) > 0 else []
        topic_docs: dict[int, list[int]] = {}
        for job_id, topic_id in zip(job_ids, topics):
            topic_docs.setdefault(int(topic_id), []).append(int(job_id))

        # ── Two-stage cascade ──────────────────────────────────────
        # Recluster noise docs (-1) with relaxed parameters to rescue
        # small but coherent clusters that couldn't meet the 15-doc
        # minimum in the main HDBSCAN pass.
        noise_mask = df["topic_id"] == -1
        noise_count = int(noise_mask.sum())

        if noise_count >= 100:
            _cascade_noise_docs(
                topic_model, embedder, df, noise_mask, noise_count, job_ids,
            )

        # Rebuild topic_docs after cascade may have reassigned docs.
        final_topics = df["topic_id"].tolist()
        topic_model._topic_docs = {}
        for job_id, topic_id in zip(job_ids, final_topics):
            topic_model._topic_docs.setdefault(
                int(topic_id), []
            ).append(int(job_id))

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
    df_clean: Optional[pd.DataFrame] = None

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

    if "detect_outliers" in requested:
        if df is None or embedder is None:
            logger.warning("Step 'detect_outliers' skipped: prerequisites missing")
        else:
            _time(
                "detect_outliers",
                lambda: _run_detect_outliers(embedder, df),
            )
            df_clean, _, _ = artifacts["detect_outliers"]

    if "topic_model" in requested:
        if df is None or embedder is None:
            logger.warning("Step 'topic_model' skipped: prerequisites missing")
        else:
            _time(
                "topic_model",
                lambda: _run_topic_model(embedder, documents, df, df_clean),
            )
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