"""Tests for the semantic search router, service layer, and query expansion."""

from unittest.mock import MagicMock

import pytest


def _mock_search_engine() -> MagicMock:
    """Return a SearchEngine mock with realistic query results."""
    engine = MagicMock()
    engine.query.return_value = [
        {"job_id": 42, "score": 0.95},
        {"job_id": 17, "score": 0.88},
        {"job_id": 103, "score": 0.72},
    ]
    return engine


def test_search_basic(app, client):
    """POST /search returns results from the search engine."""
    engine = _mock_search_engine()
    app.state.search_engine = engine
    try:
        payload = {"query": "data engineer python", "k": 10}
        response = client.post("/search", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "data engineer python"
        assert data["count"] == 3
        assert data["results"][0]["job_id"] == 42
        assert data["results"][0]["score"] == 0.95
    finally:
        app.state.search_engine = None


def test_search_custom_k(app, client):
    """POST /search passes k parameter to the search engine."""
    engine = MagicMock()
    engine.query.return_value = [{"job_id": 1, "score": 0.9}]
    app.state.search_engine = engine
    try:
        payload = {"query": "cloud engineer", "k": 5}
        response = client.post("/search", json=payload)
        assert response.status_code == 200
        engine.query.assert_called_once_with("cloud engineer", k=5)
    finally:
        app.state.search_engine = None


def test_search_engine_not_loaded(app, client):
    """POST /search returns 503 when search engine is unavailable."""
    app.state.search_engine = None
    payload = {"query": "data engineer"}
    response = client.post("/search", json=payload)
    assert response.status_code == 503


def test_expand_basic(app, client):
    """POST /topics/expand returns expanded results."""
    engine = _mock_search_engine()
    engine.expand.return_value = [
        {"job_id": 42, "score": 0.95},
        {"job_id": 17, "score": 0.88},
        {"job_id": 103, "score": 0.72},
    ]
    app.state.search_engine = engine
    try:
        payload = {"seed_text": "python developer", "rounds": 2, "threshold": 0.5, "top_k": 10}
        response = client.post("/topics/expand", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["seed_text"] == "python developer"
        assert data["rounds"] == 2
        assert data["count"] == 3
        engine.expand.assert_called_once_with("python developer", rounds=2, threshold=0.5, top_k=10)
    finally:
        app.state.search_engine = None


def test_expand_engine_not_loaded(app, client):
    """POST /topics/expand returns 503 when search engine is unavailable."""
    app.state.search_engine = None
    payload = {"seed_text": "python developer"}
    response = client.post("/topics/expand", json=payload)
    assert response.status_code == 503