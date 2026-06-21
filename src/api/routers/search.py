"""Router for semantic search endpoint.

Uses the FAISS SearchEngine loaded at startup. Returns HTTP 503 when
the search engine or embedder is not available.
"""

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas.search import SearchRequest, SearchResponse
from src.api.services import search_service

router = APIRouter()


@router.post("", response_model=SearchResponse)
def search(request: SearchRequest, app_request: Request) -> SearchResponse:
    """Search jobs by semantic similarity to the query text."""
    search_engine = app_request.app.state.search_engine
    if search_engine is None:
        raise HTTPException(
            status_code=503,
            detail="Search engine not loaded; run the NLP pipeline first",
        )
    return search_service.search(search_engine, query=request.query, k=request.k)