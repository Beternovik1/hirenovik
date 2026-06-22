"""Tests for the topics router and service layer."""

from unittest.mock import MagicMock

import pandas as pd
import pytest


def _mock_topic_model() -> MagicMock:
    """Return a TopicModel mock with realistic topic info data."""
    topic_model = MagicMock()
    topic_model.get_topic_info.return_value = pd.DataFrame(
        {
            "Topic": [-1, 0, 1, 2],
            "Count": [150, 320, 180, 95],
            "Name": [
                "outlier_topics",
                "0_data_engineer_python_sql",
                "1_cloud_aws_terraform_devops",
                "2_frontend_react_javascript",
            ],
        }
    )
    topic_model.get_topic_keywords.return_value = {
        -1: [],
        0: ["data", "engineer", "python", "sql", "pipeline"],
        1: ["cloud", "aws", "terraform", "devops", "kubernetes"],
        2: ["frontend", "react", "javascript", "css", "typescript"],
    }
    topic_model.get_coherence.return_value = {0: 0.85, 1: 0.72, 2: 0.63}
    topic_model.get_topic_docs.return_value = [1, 2]
    return topic_model


def _mock_search_engine_with_topics(embedding_dim: int = 4) -> MagicMock:
    """Return a SearchEngine mock usable for topic examples queries."""
    import numpy as np

    engine = MagicMock()
    # Two embeddings for two doc ids (1 and 2) for the topic.
    engine._id_mapping = [1, 2, 3]
    engine._embeddings = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    engine._search_vector.return_value = [
        {"job_id": 1, "score": 0.95},
        {"job_id": 2, "score": 0.88},
    ]
    return engine


# ---------------------------------------------------------------------------
# GET /topics — list endpoint
# ---------------------------------------------------------------------------


def test_list_topics(app, client):
    """GET /topics returns paginated topic list with coherence and distribution."""
    topic_model = _mock_topic_model()
    app.state.topic_model = topic_model
    try:
        response = client.get("/topics")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4
        assert len(data["items"]) == 4
        assert data["items"][0]["topic_id"] == -1
        assert data["items"][1]["count"] == 320
        # Coherence is attached for the topics that have it.
        coherence_values = {item["topic_id"]: item["coherence"] for item in data["items"]}
        assert coherence_values.get(0) == pytest.approx(0.85)
        assert coherence_values.get(1) == pytest.approx(0.72)
        # Size distribution summary is present.
        size_dist = data.get("size_distribution")
        assert size_dist is not None
        assert "min" in size_dist and "max" in size_dist
        assert size_dist["min"] == 95
        assert size_dist["max"] == 320
    finally:
        app.state.topic_model = None


def test_list_topics_with_pagination(app, client):
    """GET /topics?page=1&size=2 returns only first two topics."""
    topic_model = _mock_topic_model()
    app.state.topic_model = topic_model
    try:
        response = client.get("/topics?page=1&size=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4
        assert len(data["items"]) == 2
    finally:
        app.state.topic_model = None


def test_list_topics_model_not_loaded(app, client):
    """GET /topics returns 503 when topic model is unavailable."""
    app.state.topic_model = None
    response = client.get("/topics")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /topics/{topic_id} — detail endpoint
# ---------------------------------------------------------------------------


def test_get_topic_found(app, client):
    """GET /topics/{id} returns topic details with keywords."""
    topic_model = _mock_topic_model()
    app.state.topic_model = topic_model
    try:
        response = client.get("/topics/0")
        assert response.status_code == 200
        data = response.json()
        assert data["topic_id"] == 0
        assert data["count"] == 320
        assert data["name"] == "0_data_engineer_python_sql"
        assert "python" in data["keywords"]
    finally:
        app.state.topic_model = None


def test_get_topic_not_found(app, client):
    """GET /topics/{id} returns 404 for nonexistent topic."""
    topic_model = _mock_topic_model()
    app.state.topic_model = topic_model
    try:
        response = client.get("/topics/99")
        assert response.status_code == 404
    finally:
        app.state.topic_model = None


def test_get_topic_model_not_loaded(app, client):
    """GET /topics/{id} returns 503 when topic model is unavailable."""
    app.state.topic_model = None
    response = client.get("/topics/0")
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /topics/{topic_id}/examples — representative jobs endpoint
# ---------------------------------------------------------------------------


def test_get_topic_examples(app, client, mock_db_session):
    """GET /topics/{id}/examples returns representative jobs."""
    topic_model = _mock_topic_model()
    engine = _mock_search_engine_with_topics()
    app.state.topic_model = topic_model
    app.state.search_engine = engine
    try:
        response = client.get("/topics/0/examples?k=2")
        assert response.status_code == 200
        data = response.json()
        assert data["topic_id"] == 0
        assert isinstance(data["examples"], list)
        assert len(data["examples"]) <= 2
        # Examples should be sorted by score descending.
        scores = [ex["score"] for ex in data["examples"]]
        assert scores == sorted(scores, reverse=True)
        for ex in data["examples"]:
            assert "job_id" in ex and "title" in ex and "score" in ex
    finally:
        app.state.topic_model = None
        app.state.search_engine = None


def test_get_topic_examples_not_found(app, client):
    """GET /topics/{id}/examples returns 404 for unknown topic."""
    topic_model = _mock_topic_model()
    engine = _mock_search_engine_with_topics()
    app.state.topic_model = topic_model
    app.state.search_engine = engine
    try:
        response = client.get("/topics/99/examples")
        assert response.status_code == 404
    finally:
        app.state.topic_model = None
        app.state.search_engine = None


def test_get_topic_examples_models_not_loaded(app, client):
    """GET /topics/{id}/examples returns 503 when models unavailable."""
    app.state.topic_model = None
    app.state.search_engine = None
    response = client.get("/topics/0/examples")
    assert response.status_code == 503