"""Pydantic schemas for semantic search API requests and responses."""

from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request body for semantic search."""

    query: str = Field(..., min_length=1, description="Search query text")
    k: int = Field(default=10, ge=1, le=100, description="Number of results to return")


class SearchResult(BaseModel):
    """A single search result with similarity score."""

    job_id: int
    score: float


class SearchResponse(BaseModel):
    """Response containing search results."""

    query: str
    results: list[SearchResult]
    count: int