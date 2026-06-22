"""Pydantic schemas for topic-related API responses."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class TopicResponse(BaseModel):
    """Schema for a single topic in API responses."""

    model_config = ConfigDict(from_attributes=True)

    topic_id: int
    count: int
    name: str
    coherence: Optional[float] = None


class TopicDetailResponse(BaseModel):
    """Schema for a topic with its keywords."""

    topic_id: int
    count: int
    name: str
    keywords: list[str]


class TopicExampleJob(BaseModel):
    """A representative job for a topic."""

    job_id: int
    title: str
    score: float  # cosine similarity to topic centroid


class TopicExamplesResponse(BaseModel):
    """List of representative jobs for a topic."""

    topic_id: int
    examples: list[TopicExampleJob]


class TopicListResponse(BaseModel):
    """Paginated list of topics."""

    items: list[TopicResponse]
    total: int
    size_distribution: Optional[dict] = None