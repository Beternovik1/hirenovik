"""Service layer for topic-related operations.

Functions in this module accept the loaded ``TopicModel`` and return
pydantic schemas. They never import or reference FastAPI.
"""

import logging
from typing import Optional

import pandas as pd

from src.api.schemas.topic import TopicDetailResponse, TopicListResponse, TopicResponse

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
        Paginated ``TopicListResponse`` with topic summaries.

    Raises:
        RuntimeError: If the topic model has not been loaded.
    """
    df: pd.DataFrame = topic_model.get_topic_info()
    total = len(df)
    offset = (page - 1) * size
    page_df = df.iloc[offset : offset + size]

    items = [
        TopicResponse(
            topic_id=int(row["Topic"]),
            count=int(row["Count"]),
            name=str(row["Name"]),
        )
        for row in page_df.to_dict("records")
    ]
    return TopicListResponse(items=items, total=total)


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