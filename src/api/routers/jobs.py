"""Router for job listing and detail endpoints.

Routers handle HTTP concerns only: path parameters, query strings,
status codes, and response schemas. All business logic lives in
``src.api.services.job_service``.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.database import get_db
from src.api.schemas.job import JobListResponse, JobResponse
from src.api.services import job_service

router = APIRouter()


@router.get("", response_model=JobListResponse)
def list_jobs(
    career: Optional[str] = Query(None, description="Filter by career name"),
    country_code: Optional[str] = Query(
        None, description="Filter by ISO country code"
    ),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
) -> JobListResponse:
    """List jobs with optional filters and pagination."""
    return job_service.list_jobs(
        db,
        career=career,
        country_code=country_code,
        job_type=job_type,
        page=page,
        size=size,
    )


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobResponse:
    """Retrieve a single job by ID."""
    result = job_service.get_job(db, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return result