"""Router for skill extraction endpoint.

Extracts technology keywords from text using the same 39-feature list
as the XGBoost model for consistency with ML training data.
"""

from fastapi import APIRouter

from src.api.schemas.skill import SkillExtractionRequest, SkillExtractionResponse
from src.api.services import skill_service

router = APIRouter()


@router.post("/extract", response_model=SkillExtractionResponse)
def extract_skills(request: SkillExtractionRequest) -> SkillExtractionResponse:
    """Extract technology keywords from job description text."""
    return skill_service.extract_skills(request.text)