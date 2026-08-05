"""Tests for analytics router and service behavior."""

from types import SimpleNamespace

from src.api.services.analytics_service import (
    ROLE_BUCKETS,
    classify_role_family,
    summarize_salary_by_role,
)


def test_analytics_status_returns_placeholder_message(client):
    """GET /analytics returns a static placeholder response."""
    response = client.get("/analytics")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "analytics endpoints coming soon",
    }


def test_salary_by_role_returns_expected_shape(client, mock_db_session):
    """GET /analytics/salary-by-role returns bucket summaries and totals."""
    response = client.get("/analytics/salary-by-role")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "items",
        "total_listings",
        "total_salary_visible_rows",
        "total_valid_salary_rows",
    }
    assert data["total_listings"] == 3
    assert data["total_salary_visible_rows"] == 2
    assert data["total_valid_salary_rows"] == 2
    assert len(data["items"]) == len(ROLE_BUCKETS)
    assert set(data["items"][0]) == {
        "role_family",
        "listings",
        "salary_visible_rows",
        "valid_salary_rows",
        "median_salary_midpoint",
        "min_salary_midpoint",
        "max_salary_midpoint",
        "salary_visibility_rate",
        "interpretation_ready",
    }


def test_classify_role_family_aliases_return_expected_buckets():
    """Role classifier should preserve Notebook 3 aliases used by the API."""
    assert classify_role_family("desarrollador python") == "backend"
    assert classify_role_family("machine learning engineer") == "data science/ml"
    assert classify_role_family("qa automation engineer") == "qa/testing"
    assert classify_role_family("cybersecurity engineer") == "security"


def test_summarize_salary_by_role_invalid_pairs_are_excluded():
    """Invalid salary pairs count as visible but not valid salary rows."""
    rows = [
        SimpleNamespace(title="backend engineer", salary_min=10000, salary_max=20000),
        SimpleNamespace(title="backend engineer", salary_min=30000, salary_max=20000),
        SimpleNamespace(title="backend engineer", salary_min=0, salary_max=10000),
        SimpleNamespace(title="backend engineer", salary_min=None, salary_max=25000),
        SimpleNamespace(title="backend engineer", salary_min=None, salary_max=None),
    ]

    response = summarize_salary_by_role(rows)
    backend = next(item for item in response.items if item.role_family == "backend")

    assert backend.listings == 5
    assert backend.salary_visible_rows == 4
    assert backend.valid_salary_rows == 1
    assert backend.median_salary_midpoint == 15000
    assert backend.min_salary_midpoint == 15000
    assert backend.max_salary_midpoint == 15000
    assert backend.salary_visibility_rate == 0.8
