"""Pydantic schemas for job-related API responses.

Uses pydantic v2 ``ConfigDict(from_attributes=True)`` so that ORM
``Job`` objects can be converted with ``model_validate()`` without
manual field mapping.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    """Schema for a single job in API responses.

    Fields map directly to the ``jobs`` table columns. Optional
    fields correspond to nullable database columns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    site: Optional[str] = None
    job_url: str
    title: str
    company: str
    raw_location: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    state: Optional[str] = None
    career: Optional[str] = None
    industry_niche: Optional[str] = None
    job_type: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    cleaned_description: Optional[str] = None
    keywords_json: Optional[dict] = None
    date_posted: Optional[str] = None
    date_scraped: Optional[datetime] = None
    status: Optional[str] = None


class JobListResponse(BaseModel):
    """Paginated list of jobs with total count and page metadata."""

    items: list[JobResponse]
    total: int
    page: int
    size: int