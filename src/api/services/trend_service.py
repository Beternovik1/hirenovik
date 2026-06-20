"""Service layer for weekly topic trend operations.

Reads the pre-computed ``topic_stats.json`` artifact produced by
``TopicTrends.save_trends()`` during the NLP pipeline run.
"""

import json
import logging
from typing import Optional

from src.api.schemas.trend import TrendPoint, TrendResponse

logger = logging.getLogger(__name__)


def load_trends(stats_path: str) -> list[dict]:
    """Read the topic_stats.json artifact from disk.

    Args:
        stats_path: Path to the JSON file written by :meth:`TopicTrends.save_trends`.

    Returns:
        List of trend dictionaries (week, topic_id, count, etc.).

    Raises:
        FileNotFoundError: If the artifact file does not exist.
    """
    with open(stats_path, encoding="utf-8") as fh:
        data = json.load(fh)
    logger.info("Loaded %d trend records from %s", len(data), stats_path)
    return data


def get_trends(
    stats_path: str,
    min_count: int = 3,
) -> TrendResponse:
    """Return weekly trends computed from the saved artifact.

    Args:
        stats_path: Path to the JSON trend artifact.
        min_count: Minimum per-week count for a topic to be flagged trending.

    Returns:
        ``TrendResponse`` with all trend points and trending topic ids.
    """
    raw = load_trends(stats_path)
    items = [TrendPoint(**row) for row in raw]
    trending_ids = _find_trending(raw, min_count)
    return TrendResponse(items=items, trending_topic_ids=trending_ids)


def _find_trending(raw: list[dict], min_count: int) -> list[int]:
    """Extract topic ids that are trending from raw trend dicts."""
    ids: set[int] = set()
    for row in raw:
        if row.get("is_trending") and row.get("count", 0) >= min_count:
            ids.add(int(row["topic_id"]))
    return sorted(ids)