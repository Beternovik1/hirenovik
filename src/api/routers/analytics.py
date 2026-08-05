"""Router for DB-only analytics endpoints."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.database import get_db
from src.api.schemas.analytics import (
    GeographyResponse,
    IndustryDemandResponse,
    SalaryByRoleResponse,
    SkillFrequencyResponse,
    TimeTrendResponse,
)
from src.api.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def analytics_status() -> dict[str, str]:
    """Return analytics router availability status."""
    return {"status": "ok", "message": "analytics endpoints coming soon"}


@router.get("/salary-by-role", response_model=SalaryByRoleResponse)
def get_salary_by_role(db: Session = Depends(get_db)) -> SalaryByRoleResponse:
    """Return role-family salary summaries from jobs table rows only."""
    return analytics_service.get_salary_by_role(db)


@router.get("/industry-demand", response_model=IndustryDemandResponse)
def get_industry_demand(
    db: Session = Depends(get_db),
) -> IndustryDemandResponse:
    """Return industry demand summaries grouped by niche, career, type, and site."""
    return analytics_service.get_industry_demand(db)


@router.get("/geography", response_model=GeographyResponse)
def get_geography(db: Session = Depends(get_db)) -> GeographyResponse:
    """Return geography summaries grouped by country, state, and raw_location."""
    return analytics_service.get_geography(db)


@router.get("/time-trends", response_model=TimeTrendResponse)
def get_time_trends(
    granularity: Literal["week", "month"] = Query(
        default="week",
        description="Time grouping granularity: 'week' or 'month'",
    ),
    db: Session = Depends(get_db),
) -> TimeTrendResponse:
    """Return job postings time-series trends grouped by week or month."""
    return analytics_service.get_time_trends(db, granularity)


@router.get("/skill-frequency", response_model=SkillFrequencyResponse)
def get_skill_frequency(
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of keywords to return",
    ),
    db: Session = Depends(get_db),
) -> SkillFrequencyResponse:
    """Return global keyword frequency from the keywords_json column."""
    return analytics_service.get_skill_frequency(db, limit=limit)
