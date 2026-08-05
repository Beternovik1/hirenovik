"""Router for analytics endpoint placeholders."""

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
def analytics_status() -> dict[str, str]:
    """Return analytics router availability status."""
    return {"status": "ok", "message": "analytics endpoints coming soon"}
