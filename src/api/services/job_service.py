"""Service layer for job-related database queries.

Functions in this module accept a SQLAlchemy ``Session`` and return
pydantic schemas. They never import or reference FastAPI so the
business logic stays framework-agnostic.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.api.schemas.job import JobListResponse, JobResponse
from src.database.models import Job

logger = logging.getLogger(__name__)


def list_jobs(
    db: Session,
    career: Optional[str] = None,
    country_code: Optional[str] = None,
    job_type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
) -> JobListResponse:
    """Query jobs with optional filters and pagination.

    Args:
        db: SQLAlchemy session.
        career: Filter by career name (exact match).
        country_code: Filter by ISO country code (exact match).
        job_type: Filter by job type (exact match).
        page: 1-based page number.
        size: Number of results per page (max 100).

    Returns:
        Paginated ``JobListResponse`` with matching jobs.
    """
    query = db.query(Job)

    if career is not None:
        query = query.filter(Job.career == career)
    if country_code is not None:
        query = query.filter(Job.country_code == country_code)
    if job_type is not None:
        query = query.filter(Job.job_type == job_type)

    total = query.count()
    offset = (page - 1) * size
    rows = query.order_by(Job.date_scraped.desc()).offset(offset).limit(size).all()

    items = [JobResponse.model_validate(row) for row in rows]
    return JobListResponse(items=items, total=total, page=page, size=size)


def get_job(db: Session, job_id: int) -> Optional[JobResponse]:
    """Fetch a single job by primary key.

    Args:
        db: SQLAlchemy session.
        job_id: Primary key of the job record.

    Returns:
        ``JobResponse`` if found, ``None`` otherwise.
    """
    row = db.query(Job).filter(Job.id == job_id).first()
    if row is None:
        return None
    return JobResponse.model_validate(row)