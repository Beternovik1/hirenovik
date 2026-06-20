"""Service layer for semantic search and query expansion operations.

Delegates to the FAISS-based SearchEngine loaded at startup.
"""

import logging

from src.api.schemas.search import ExpandResponse, SearchResult, SearchResponse

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


def expand(
    search_engine: object,
    seed_text: str,
    rounds: int = 3,
    threshold: float = 0.7,
    top_k: int = 20,
) -> ExpandResponse:
    """Iteratively expand a seed query into matching jobs.

    Args:
        search_engine: A loaded SearchEngine instance.
        seed_text: Initial text to start expansion from.
        rounds: Number of expansion iterations.
        threshold: Cosine similarity cutoff per round.
        top_k: Maximum results per round.

    Returns:
        ``ExpandResponse`` with expanded job ids and scores.
    """
    raw_results = search_engine.expand(
        seed_text, rounds=rounds, threshold=threshold, top_k=top_k
    )
    results = [
        SearchResult(job_id=r["job_id"], score=r["score"]) for r in raw_results
    ]
    return ExpandResponse(
        seed_text=seed_text, rounds=rounds, results=results, count=len(results)
    )