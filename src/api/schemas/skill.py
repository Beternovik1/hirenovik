"""Pydantic schemas for skill extraction API requests and responses."""

from pydantic import BaseModel, Field


class SkillExtractionRequest(BaseModel):
    """Request body for skill extraction from text."""

    text: str = Field(..., min_length=1, description="Job description text to extract skills from")


class SkillExtractionResponse(BaseModel):
    """Response containing extracted skills."""

    skills: list[str]
    count: int