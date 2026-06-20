"""Service layer for semantic search operations.

Delegates to the FAISS-based SearchEngine loaded at startup.
"""

import logging
from typing import Optional

from src.api.schemas.search import SearchResult, SearchResponse

logger = logging.getLogger(__name__)


def search(
    search_engine: object,
    query: str,
    k: int = 10,
) -> SearchResponse:
    """Query the FAISS search engine with text.

    Args:
        search_engine: A loaded SearchEngine instance.
        query: Free-text search query.
        k: Number of results to return.

    Returns:
        ``SearchResponse`` with matched job ids and scores.
    """
    raw_results = search_engine.query(query, k=k)
    results = [
        SearchResult(job_id=r["job_id"], score=r["score"]) for r in raw_results
    ]
    return SearchResponse(query=query, results=results, count=len(results))