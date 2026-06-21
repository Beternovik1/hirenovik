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
    return topic_model


# ---------------------------------------------------------------------------
# GET /topics — list endpoint
# ---------------------------------------------------------------------------


def test_list_topics(app, client):
    """GET /topics returns paginated topic list."""
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