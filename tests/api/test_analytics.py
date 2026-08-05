"""Tests for analytics router and service behavior."""

from datetime import datetime, timezone
from types import SimpleNamespace

from src.api.services.analytics_service import (
    ROLE_BUCKETS,
    _parse_keywords,
    classify_role_family,
    summarize_industry_demand,
    summarize_salary_by_role,
    summarize_skill_frequency,
)
from src.api.schemas.analytics import SkillFrequencyResponse


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


def test_industry_demand_returns_expected_shape(client, mock_db_session):
    """GET /analytics/industry-demand returns groups and counts."""
    response = client.get("/analytics/industry-demand")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "items",
        "total_listings",
        "total_salary_visible_rows",
        "total_valid_salary_rows",
        "total_groups",
    }
    assert data["total_listings"] == 3
    assert data["total_salary_visible_rows"] == 2
    assert data["total_valid_salary_rows"] == 2
    assert data["total_groups"] == 3
    assert len(data["items"]) == 3
    assert set(data["items"][0]) == {
        "industry_niche",
        "career",
        "job_type",
        "site",
        "listings",
        "salary_visible_rows",
        "valid_salary_rows",
        "median_salary_midpoint",
        "salary_visibility_rate",
        "first_date_scraped",
        "last_date_scraped",
        "first_date_posted",
        "last_date_posted",
        "interpretation_ready",
    }


def test_summarize_industry_demand_valid_salary_filtering():
    """Invalid salary pairs count as visible but not valid salary rows."""
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            title="engineer",
            salary_min=10000,
            salary_max=20000,
            industry_niche="Tech",
            career="Engineer",
            job_type="remoto",
            site="indeed",
            date_scraped=t0,
            date_posted=None,
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=30000,
            salary_max=20000,
            industry_niche="Tech",
            career="Engineer",
            job_type="remoto",
            site="indeed",
            date_scraped=t0,
            date_posted=None,
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=0,
            salary_max=10000,
            industry_niche="Tech",
            career="Engineer",
            job_type="remoto",
            site="indeed",
            date_scraped=t0,
            date_posted=None,
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=None,
            salary_max=25000,
            industry_niche="Tech",
            career="Engineer",
            job_type="remoto",
            site="indeed",
            date_scraped=t0,
            date_posted=None,
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=None,
            salary_max=None,
            industry_niche="Tech",
            career="Engineer",
            job_type="remoto",
            site="indeed",
            date_scraped=t0,
            date_posted=None,
        ),
    ]

    response = summarize_industry_demand(rows)

    assert len(response.items) == 1
    group = response.items[0]
    assert group.listings == 5
    assert group.salary_visible_rows == 4
    assert group.valid_salary_rows == 1
    assert group.median_salary_midpoint == 15000
    assert group.salary_visibility_rate == 0.8
    assert response.total_groups == 1


def test_skill_frequency_returns_expected_shape(client, mock_db_session):
    """GET /analytics/skill-frequency returns keywords with expected shape."""
    from src.database.models import Job

    session = mock_db_session
    session.add_all([
        Job(
            id=100,
            site="test",
            job_url="https://test.com/job/100",
            title="Python Developer",
            company="Dev Co",
            raw_location="Remote",
            career="Developer",
            job_type="remoto",
            description="Build apps",
            status="NEW",
            keywords_json=["python", "sql", "aws"],
        ),
        Job(
            id=101,
            site="test",
            job_url="https://test.com/job/101",
            title="SQL Analyst",
            company="Data Co",
            raw_location="Remote",
            career="Analyst",
            job_type="remoto",
            description="Analyze data",
            status="NEW",
            keywords_json=["sql", "excel"],
        ),
        Job(
            id=102,
            site="test",
            job_url="https://test.com/job/102",
            title="Manager",
            company="Biz Co",
            raw_location="Remote",
            career="Manager",
            job_type="presencial",
            description="Manage things",
            status="NEW",
            keywords_json=None,
        ),
    ])
    session.commit()

    response = client.get("/analytics/skill-frequency")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"items", "total_unique_keywords", "total_listings_with_keywords"}
    assert data["total_listings_with_keywords"] == 2
    assert len(data["items"]) >= 1
    assert set(data["items"][0]) == {"keyword", "rows"}

    sql_item = next(it for it in data["items"] if it["keyword"] == "sql")
    assert sql_item["rows"] == 2


def test_skill_frequency_excludes_null_and_empty_keywords():
    """Rows with null or empty keywords_json must not count towards listings or keywords."""
    rows = [
        SimpleNamespace(id=1, title="t1", salary_min=None, salary_max=None, keywords_json=None),
        SimpleNamespace(id=2, title="t2", salary_min=None, salary_max=None, keywords_json="[]"),
        SimpleNamespace(id=3, title="t3", salary_min=None, salary_max=None, keywords_json='["python"]'),
    ]
    result = summarize_skill_frequency(rows)

    assert isinstance(result, SkillFrequencyResponse)
    assert result.total_listings_with_keywords == 1
    assert result.total_unique_keywords == 1
    assert len(result.items) == 1
    assert result.items[0].keyword == "python"
    assert result.items[0].rows == 1


def test_skill_frequency_limit_parameter(client, mock_db_session):
    """limit query parameter truncates returned items to the requested number."""
    from src.database.models import Job

    session = mock_db_session
    keywords_list = [f"skill_{i}" for i in range(10)]
    session.add(
        Job(
            id=200,
            site="test",
            job_url="https://test.com/job/200",
            title="Multi-skill Engineer",
            company="Skills Co",
            raw_location="Remote",
            career="Engineer",
            job_type="remoto",
            description="Many skills",
            status="NEW",
            keywords_json=keywords_list,
        ),
    )
    session.commit()

    response = client.get("/analytics/skill-frequency?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["total_unique_keywords"] == 10
    assert data["total_listings_with_keywords"] == 1


def test_parse_keywords_handles_edge_cases():
    """_parse_keywords handles None, empty, invalid JSON, and mixed types."""
    assert _parse_keywords(None) == []
    assert _parse_keywords("") == []
    assert _parse_keywords("[]") == []
    assert _parse_keywords("not json") == []
    assert _parse_keywords('["python", "SQL", null]') == ["python", "sql"]
    assert _parse_keywords(["Python", "  aws  ", ""]) == ["python", "aws"]
