"""Pydantic schemas for trend-related API responses."""

from typing import Optional

from pydantic import BaseModel


class TrendPoint(BaseModel):
    """A single week-topic data point in the trends response."""

    week: str
    topic_id: int
    count: int
    avg_salary: Optional[float] = None
    pct_change: Optional[float] = None
    is_trending: bool


class TrendResponse(BaseModel):
    """Full trends response with metadata."""

    items: list[TrendPoint]
    trending_topic_ids: list[int]