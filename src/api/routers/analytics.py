"""Router for DB-only analytics endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.database import get_db
from src.api.schemas.analytics import SalaryByRoleResponse
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
