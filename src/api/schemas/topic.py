"""Pydantic schemas for topic-related API responses."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class TopicResponse(BaseModel):
    """Schema for a single topic in API responses."""

    model_config = ConfigDict(from_attributes=True)

    topic_id: int
    count: int
    name: str


class TopicDetailResponse(BaseModel):
    """Schema for a topic with its keywords."""

    topic_id: int
    count: int
    name: str
    keywords: list[str]


class TopicListResponse(BaseModel):
    """Paginated list of topics."""

    items: list[TopicResponse]
    total: int