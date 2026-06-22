"""Router for topic listing, detail, and query expansion endpoints.

Topics come from the BERTopic model loaded at startup and stored in
``app.state.topic_model``. Query expansion uses the FAISS SearchEngine
stored in ``app.state.search_engine``. If either is unavailable,
endpoints return HTTP 503.
"""

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas.search import ExpandRequest, ExpandResponse
from src.api.schemas.topic import (
    TopicDetailResponse,
    TopicExamplesResponse,
    TopicListResponse,
)
from src.api.services import search_service, topic_service

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
        raise HTTPException(
            status_code=503, detail="Topic model not loaded; run pipeline first"
        )
    return topic_service.list_topics(topic_model, page=page, size=size)


@router.get("/{topic_id}", response_model=TopicDetailResponse)
def get_topic(topic_id: int, request: Request) -> TopicDetailResponse:
    """Retrieve a single topic with its keywords."""
    topic_model = request.app.state.topic_model
    if topic_model is None:
        raise HTTPException(
            status_code=503, detail="Topic model not loaded; run pipeline first"
        )
    result = topic_service.get_topic(topic_model, topic_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")
    return result


@router.get("/{topic_id}/examples", response_model=TopicExamplesResponse)
def get_topic_examples(
    topic_id: int,
    request: Request,
    k: int = Query(5, ge=1, le=20, description="Number of examples"),
) -> TopicExamplesResponse:
    """Return the k most representative jobs for a topic."""
    topic_model = request.app.state.topic_model
    search_engine = request.app.state.search_engine
    if topic_model is None or search_engine is None:
        raise HTTPException(status_code=503, detail="Models not loaded")
    result = topic_service.get_topic_examples(topic_model, search_engine, topic_id, k=k)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Topic {topic_id} not found or engine unavailable",
        )
    return result


@router.post("/expand", response_model=ExpandResponse)
def expand_query(
    expand_request: ExpandRequest,
    app_request: Request,
) -> ExpandResponse:
    """Iteratively expand a seed query into matching jobs (Pacheco-style)."""
    search_engine = app_request.app.state.search_engine
    if search_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Search engine not loaded; run the NLP pipeline first",
        )
    return search_service.expand(
        search_engine,
        seed_text=expand_request.seed_text,
        rounds=expand_request.rounds,
        threshold=expand_request.threshold,
        top_k=expand_request.top_k,
    )