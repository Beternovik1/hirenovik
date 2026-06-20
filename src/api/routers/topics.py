"""Router for topic listing and detail endpoints.

Topics come from the BERTopic model loaded at startup and stored in
``app.state.topic_model``. If the model is unavailable, endpoints
return HTTP 503.
"""

from typing import Optional

from fastapi import APIRouter, Query, Request

from src.api.schemas.topic import TopicDetailResponse, TopicListResponse
from src.api.services import topic_service

router = APIRouter()


@router.get("", response_model=TopicListResponse)
def list_topics(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Results per page"),
) -> TopicListResponse:
    """List BERTopic topics with pagination."""
    topic_model = request.app.state.topic_model
    if topic_model is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503, detail="Topic model not loaded; run pipeline first"
        )
    return topic_service.list_topics(topic_model, page=page, size=size)


@router.get("/{topic_id}", response_model=TopicDetailResponse)
def get_topic(topic_id: int, request: Request) -> TopicDetailResponse:
    """Retrieve a single topic with its keywords."""
    topic_model = request.app.state.topic_model
    if topic_model is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503, detail="Topic model not loaded; run pipeline first"
        )
    result = topic_service.get_topic(topic_model, topic_id)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    return result