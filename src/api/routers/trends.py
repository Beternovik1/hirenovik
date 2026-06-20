"""Router for weekly topic trend endpoints.

Trends come from the ``topic_stats.json`` artifact produced by the NLP
pipeline. If the artifact is missing, endpoints return HTTP 503.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas.trend import TrendResponse
from src.api.services import trend_service

router = APIRouter()


@router.get("", response_model=TrendResponse)
def get_trends(
    request: Request,
    min_count: int = Query(3, ge=1, description="Minimum count for trending flag"),
) -> TrendResponse:
    """Return weekly topic trend data and trending topic ids."""
    settings = request.app.state.settings if hasattr(request.app.state, "settings") else None
    stats_path = settings.topic_stats_path if settings else "src/nlp/models/topic_stats.json"

    try:
        return trend_service.get_trends(stats_path, min_count=min_count)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="Trend data not available; run the NLP pipeline first",
        )