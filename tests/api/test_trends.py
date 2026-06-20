"""Tests for the trends router and service layer."""

import json
import os
import tempfile

import pytest


def _write_trend_json(path: str) -> None:
    """Write a sample topic_stats.json to the given path."""
    data = [
        {
            "week": "2026-W20",
            "topic_id": 0,
            "count": 42,
            "avg_salary": 35000.0,
            "pct_change": None,
            "is_trending": False,
        },
        {
            "week": "2026-W21",
            "topic_id": 0,
            "count": 55,
            "avg_salary": 36000.0,
            "pct_change": 30.95,
            "is_trending": True,
        },
        {
            "week": "2026-W21",
            "topic_id": 1,
            "count": 12,
            "avg_salary": None,
            "pct_change": None,
            "is_trending": False,
        },
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


# ---------------------------------------------------------------------------
# GET /trends — list endpoint
# ---------------------------------------------------------------------------


def test_get_trends_success(app, client):
    """GET /trends returns trend data from the artifact file."""
    tmpdir = tempfile.mkdtemp()
    stats_path = os.path.join(tmpdir, "topic_stats.json")
    _write_trend_json(stats_path)

    # Inject a minimal settings mock that provides topic_stats_path.
    class FakeSettings:
        topic_stats_path = stats_path

    app.state.settings = FakeSettings()
    try:
        response = client.get("/trends")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 3
        assert data["items"][0]["week"] == "2026-W20"
        assert data["trending_topic_ids"] == [0]
    finally:
        del app.state.settings
        os.remove(stats_path)
        os.rmdir(tmpdir)


def test_get_trends_with_min_count(app, client):
    """GET /trends?min_count=50 filters trending topics by count."""
    tmpdir = tempfile.mkdtemp()
    stats_path = os.path.join(tmpdir, "topic_stats.json")
    _write_trend_json(stats_path)

    class FakeSettings:
        topic_stats_path = stats_path

    app.state.settings = FakeSettings()
    try:
        response = client.get("/trends?min_count=50")
        assert response.status_code == 200
        data = response.json()
        # Topic 0 has count=55 (> 50) and is_trending=True -> included
        # Topic 0 week 20 has count=42 (< 50) but week 21 has 55
        assert data["trending_topic_ids"] == [0]
    finally:
        del app.state.settings
        os.remove(stats_path)
        os.rmdir(tmpdir)


def test_get_trends_file_not_found(app, client):
    """GET /trends returns 503 when the artifact file is missing."""
    class FakeSettings:
        topic_stats_path = "/nonexistent/path/topic_stats.json"

    app.state.settings = FakeSettings()
    try:
        response = client.get("/trends")
        assert response.status_code == 503
    finally:
        del app.state.settings