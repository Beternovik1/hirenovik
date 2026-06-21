"""Pydantic schemas for semantic search and query expansion APIs."""

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


class ExpandRequest(BaseModel):
    """Request body for iterative query expansion (Pacheco-style)."""

    seed_text: str = Field(..., min_length=1, description="Seed text to start expansion from")
    rounds: int = Field(default=3, ge=1, le=5, description="Number of expansion rounds")
    threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Cosine similarity threshold")
    top_k: int = Field(default=20, ge=1, le=100, description="Number of results per round")


class ExpandResponse(BaseModel):
    """Response containing expanded query results."""

    seed_text: str
    rounds: int
    results: list[SearchResult]
    count: int