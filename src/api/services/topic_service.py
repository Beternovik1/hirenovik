"""Service layer for topic-related operations.

Functions in this module accept the loaded ``TopicModel`` and return
pydantic schemas. They never import or reference FastAPI.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from src.api.schemas.topic import (
    TopicDetailResponse,
    TopicExampleJob,
    TopicExamplesResponse,
    TopicListResponse,
    TopicResponse,
)

logger = logging.getLogger(__name__)


def list_topics(
    topic_model: object,
    page: int = 1,
    size: int = 20,
) -> TopicListResponse:
    """Return a paginated list of topics from a fitted TopicModel.

    Args:
        topic_model: A loaded TopicModel instance with ``get_topic_info``.
        page: 1-based page number.
        size: Number of results per page (max 100).

    Returns:
        Paginated ``TopicListResponse`` with topic summaries enriched
        with per-topic coherence scores and a topic size distribution
        summary.

    Raises:
        RuntimeError: If the topic model has not been loaded.
    """
    df: pd.DataFrame = topic_model.get_topic_info()
    total = len(df)
    offset = (page - 1) * size
    page_df = df.iloc[offset : offset + size]

    # Coherence is optional; absent coherence is left as None.
    coherence: dict[int, float] = {}
    get_coherence = getattr(topic_model, "get_coherence", None)
    if get_coherence is not None:
        try:
            coherence = get_coherence() or {}
        except Exception:  # pragma: no cover - defensive
            coherence = {}

    items = [
        TopicResponse(
            topic_id=int(row["Topic"]),
            count=int(row["Count"]),
            name=str(row["Name"]),
            coherence=coherence.get(int(row["Topic"])),
        )
        for row in page_df.to_dict("records")
    ]

    # Compute a compact size distribution summary across all topics.
    size_distribution: Optional[dict] = None
    if total > 0 and "Count" in df.columns:
        counts = df["Count"].astype(float)
        size_distribution = {
            "min": int(counts.min()),
            "max": int(counts.max()),
            "median": float(counts.median()),
            "std": float(counts.std(ddof=0)) if len(counts) > 1 else 0.0,
        }

    return TopicListResponse(
        items=items, total=total, size_distribution=size_distribution
    )


def get_topic(topic_model: object, topic_id: int) -> Optional[TopicDetailResponse]:
    """Return details for a single topic.

    Args:
        topic_model: A loaded TopicModel instance.
        topic_id: BERTopic topic identifier.

    Returns:
        ``TopicDetailResponse`` if the topic exists, ``None`` otherwise.
    """
    keywords_map: dict[int, list[str]] = topic_model.get_topic_keywords()
    if topic_id not in keywords_map:
        return None

    df: pd.DataFrame = topic_model.get_topic_info()
    row = df[df["Topic"] == topic_id]
    if row.empty:
        return None

    first = row.iloc[0]
    return TopicDetailResponse(
        topic_id=int(first["Topic"]),
        count=int(first["Count"]),
        name=str(first["Name"]),
        keywords=keywords_map[topic_id],
    )


def get_topic_examples(
    topic_model: object,
    search_engine: object,
    topic_id: int,
    k: int = 5,
) -> Optional[TopicExamplesResponse]:
    """Return the ``k`` most representative jobs for a topic.

    The representative jobs are the documents closest (by cosine
    similarity) to the topic's centroid embedding.

    Args:
        topic_model: A loaded TopicModel instance with ``get_topic_docs``.
        search_engine: A SearchEngine exposing ``_embeddings`` and a
             ``_search_vector`` helper.
        topic_id: BERTopic topic identifier.
        k: Number of representative jobs to return.

    Returns:
        ``TopicExamplesResponse`` if the topic exists and the engine is
        ready, ``None`` otherwise.
    """
    if search_engine is None:
        return None

    keywords_map: dict[int, list[str]] = topic_model.get_topic_keywords()
    if topic_id not in keywords_map:
        return None

    get_docs = getattr(topic_model, "get_topic_docs", None)
    topic_doc_ids: list[int] = []
    if get_docs is not None:
        topic_doc_ids = list(get_docs(topic_id))
    if not topic_doc_ids:
        return None

    embeddings = getattr(search_engine, "_embeddings", None)
    id_mapping = getattr(search_engine, "_id_mapping", None)
    if embeddings is None or id_mapping is None:
        return None

    # Locate the index positions of the topic's documents inside the
    # search engine's id mapping.
    positions: list[int] = []
    for jid in topic_doc_ids:
        try:
            pos = id_mapping.index(int(jid))
        except ValueError:
            continue
        positions.append(pos)
    if not positions:
        return None

    member_embeddings = np.asarray(embeddings, dtype=np.float32)[positions]
    centroid = member_embeddings.mean(axis=0, keepdims=True)
    # L2-normalize the centroid so FAISS inner-product == cosine similarity.
    norm = np.linalg.norm(centroid, axis=1, keepdims=True)
    norm = np.where(norm == 0, 1.0, norm)
    centroid = centroid / norm

    search_vector = getattr(search_engine, "_search_vector", None)
    if search_vector is None:
        return None

    results = search_vector(centroid.astype(np.float32), k)
    if not results:
        return TopicExamplesResponse(topic_id=topic_id, examples=[])

    job_ids = [r["job_id"] for r in results]
    titles = _fetch_job_titles(job_ids)

    examples = [
        TopicExampleJob(
            job_id=r["job_id"],
            title=titles.get(r["job_id"], "Unknown"),
            score=float(r["score"]),
        )
        for r in results
    ]
    examples.sort(key=lambda item: item.score, reverse=True)
    return TopicExamplesResponse(topic_id=topic_id, examples=examples)


def _fetch_job_titles(job_ids: list[int]) -> dict[int, str]:
    """Return ``{job_id: title}`` for the given ids from the database."""
    if not job_ids:
        return {}
    from src.database.models import Job, db_connect
    from sqlalchemy.orm import Session

    engine = None
    try:
        engine = db_connect()
        with Session(engine) as session:
            rows = (
                session.query(Job.id, Job.title)
                .filter(Job.id.in_(job_ids))
                .all()
            )
            return {int(row[0]): str(row[1]) for row in rows}
    except Exception:  # pragma: no cover - defensive
        return {jid: "Unknown" for jid in job_ids}
    finally:
        if engine is not None:
            engine.dispose()