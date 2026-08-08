"""Tests for analytics router and service behavior."""

from datetime import datetime, timezone
from types import SimpleNamespace

from src.api.services.analytics_service import (
    ROLE_BUCKETS,
    _parse_skills_array,
    classify_role_family,
    summarize_geography,
    summarize_industry_demand,
    summarize_salary_by_role,
    summarize_skill_frequency,
    summarize_time_trends,
)
from src.api.schemas.analytics import (
    SkillFrequencyResponse,
    TimeTrendResponse,
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
    """GET /analytics/skill-frequency returns skills from skills_json."""
    from src.database.models import Job

    session = mock_db_session
    session.add_all([
        Job(id=100, site="test", job_url="https://t.com/100", title="Dev",
            company="C", raw_location="R", status="NEW",
            skills_json=["python", "sql", "aws"]),
        Job(id=101, site="test", job_url="https://t.com/101", title="Analyst",
            company="C", raw_location="R", status="NEW",
            skills_json=["sql", "excel"]),
        Job(id=102, site="test", job_url="https://t.com/102", title="Mgr",
            company="C", raw_location="R", status="NEW",
            skills_json=None),
    ])
    session.commit()

    response = client.get("/analytics/skill-frequency")
    assert response.status_code == 200
    data = response.json()
    for key in ("items", "processed_canonical_jobs", "canonical_jobs_total",
                "skill_coverage", "total_unique_skills_observed"):
        assert key in data, f"Missing key: {key}"
    assert data["processed_canonical_jobs"] >= 1
    assert len(data["items"]) >= 1
    assert set(data["items"][0]) == {"skill", "job_count", "prevalence"}


def test_skill_frequency_excludes_null_and_empty():
    """skills_json NULL and [] are handled: NULL excluded, [] in denominator."""
    assert _parse_skills_array(None) == []
    assert _parse_skills_array([]) == []
    assert _parse_skills_array(["python", "sql"]) == ["python", "sql"]
    assert _parse_skills_array('["python", "SQL", null]') == ["python", "sql"]


def test_skill_frequency_limit_parameter(client, mock_db_session):
    """limit query parameter truncates returned items."""
    from src.database.models import Job

    session = mock_db_session
    skills_list = [f"skill_{i}" for i in range(10)]
    session.add(Job(id=200, site="test", job_url="https://t.com/200",
                     title="T", company="C", raw_location="R", status="NEW",
                     skills_json=skills_list))
    session.commit()

    response = client.get("/analytics/skill-frequency?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["total_unique_skills_observed"] == 10
    assert data["processed_canonical_jobs"] == 1


def test_parse_skills_array_handles_edge_cases():
    """_parse_skills_array handles various input types safely."""
    assert _parse_skills_array(None) == []
    assert _parse_skills_array("") == []
    assert _parse_skills_array("[]") == []
    assert _parse_skills_array("not json") == []
    assert _parse_skills_array('["python", "SQL", null]') == ["python", "sql"]
    assert _parse_skills_array(["Python", "  aws  ", ""]) == ["python", "aws"]


def test_geography_returns_expected_shape(client, mock_db_session):
    """GET /analytics/geography returns groups and totals."""
    response = client.get("/analytics/geography")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "items",
        "total_listings",
        "total_salary_visible_rows",
        "total_valid_salary_rows",
        "total_locations",
    }
    assert data["total_listings"] == 3
    assert data["total_salary_visible_rows"] == 2
    assert data["total_valid_salary_rows"] == 2
    assert data["total_locations"] == 3
    assert len(data["items"]) == 3
    assert set(data["items"][0]) == {
        "country",
        "state",
        "raw_location",
        "listings",
        "salary_visible_rows",
        "valid_salary_rows",
        "median_salary_midpoint",
        "min_salary_midpoint",
        "max_salary_midpoint",
        "salary_visibility_rate",
        "interpretation_ready",
    }


def test_summarize_geography_nulls_coalesced_to_unknown():
    """Null country, state, or raw_location must be replaced with 'Unknown'."""
    rows = [
        SimpleNamespace(
            title="dev",
            salary_min=10000,
            salary_max=20000,
            country=None,
            state=None,
            raw_location=None,
        ),
        SimpleNamespace(
            title="dev",
            salary_min=30000,
            salary_max=50000,
            country=None,
            state=None,
            raw_location=None,
        ),
    ]

    response = summarize_geography(rows)

    assert response.total_locations == 1
    assert response.total_listings == 2
    group = response.items[0]
    assert group.country == "Unknown"
    assert group.state == "Unknown"
    assert group.raw_location == "Unknown"


def test_summarize_geography_salary_filtering():
    """Invalid salary pairs count as visible but not valid salary rows."""
    rows = [
        SimpleNamespace(
            title="engineer",
            salary_min=10000,
            salary_max=20000,
            country="Mexico",
            state="CDMX",
            raw_location="CDMX",
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=30000,
            salary_max=20000,
            country="Mexico",
            state="CDMX",
            raw_location="CDMX",
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=0,
            salary_max=10000,
            country="Mexico",
            state="CDMX",
            raw_location="CDMX",
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=None,
            salary_max=25000,
            country="Mexico",
            state="CDMX",
            raw_location="CDMX",
        ),
        SimpleNamespace(
            title="engineer",
            salary_min=None,
            salary_max=None,
            country="Mexico",
            state="CDMX",
            raw_location="CDMX",
        ),
    ]

    response = summarize_geography(rows)

    assert len(response.items) == 1
    group = response.items[0]
    assert group.listings == 5
    assert group.salary_visible_rows == 4
    assert group.valid_salary_rows == 1
    assert group.median_salary_midpoint == 15000
    assert group.min_salary_midpoint == 15000
    assert group.max_salary_midpoint == 15000
    assert group.salary_visibility_rate == 0.8


def test_time_trends_returns_expected_shape(client, mock_db_session):
    """GET /analytics/time-trends returns period groups and totals."""
    response = client.get("/analytics/time-trends")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "items",
        "total_listings",
        "total_salary_visible_rows",
        "total_valid_salary_rows",
        "period_count",
    }
    assert data["total_listings"] == 3
    assert data["total_salary_visible_rows"] == 2
    assert data["total_valid_salary_rows"] == 2
    assert data["period_count"] == 1
    assert len(data["items"]) == 1
    assert set(data["items"][0]) == {
        "period_start",
        "listings",
        "salary_visible_rows",
        "valid_salary_rows",
        "median_salary_midpoint",
        "date_posted_listings",
    }


def test_time_trends_default_granularity_is_week(client, mock_db_session):
    """Default granularity parameter is 'week' and returns valid period."""
    response = client.get("/analytics/time-trends")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    period_start = data["items"][0]["period_start"]
    assert "-" in period_start


def test_time_trends_month_granularity(client, mock_db_session):
    """Month granularity returns monthly period_start."""
    response = client.get("/analytics/time-trends?granularity=month")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    period_start = data["items"][0]["period_start"]
    assert "-" in period_start


def test_time_trends_invalid_granularity_returns_422(client, mock_db_session):
    """Invalid granularity query param returns 422."""
    response = client.get("/analytics/time-trends?granularity=day")

    assert response.status_code == 422


def test_summarize_time_trends_week_grouping():
    """Week granularity groups rows by ISO week and computes correct stats."""
    t1 = datetime(2026, 3, 9, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 11, tzinfo=timezone.utc)
    t3 = datetime(2026, 3, 16, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            title="dev", salary_min=10000, salary_max=20000,
            date_scraped=t1, date_posted="2026-03-05",
        ),
        SimpleNamespace(
            title="dev", salary_min=15000, salary_max=25000,
            date_scraped=t2, date_posted="2026-03-06",
        ),
        SimpleNamespace(
            title="dev", salary_min=None, salary_max=None,
            date_scraped=t3, date_posted=None,
        ),
    ]

    result = summarize_time_trends(rows, "week")

    assert isinstance(result, TimeTrendResponse)
    assert result.period_count == 2
    assert result.total_listings == 3
    assert result.total_salary_visible_rows == 2
    assert result.total_valid_salary_rows == 2

    week1 = result.items[0]
    assert week1.listings == 2
    assert week1.valid_salary_rows == 2
    assert week1.median_salary_midpoint == 17500.0
    assert week1.date_posted_listings == 2

    week2 = result.items[1]
    assert week2.listings == 1
    assert week2.salary_visible_rows == 0
    assert week2.valid_salary_rows == 0
    assert week2.median_salary_midpoint is None
    assert week2.date_posted_listings is None


def test_summarize_time_trends_month_grouping():
    """Month granularity groups rows by year-month and computes correct stats."""
    t1 = datetime(2026, 3, 9, tzinfo=timezone.utc)
    t2 = datetime(2026, 3, 31, tzinfo=timezone.utc)
    t3 = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            title="dev", salary_min=10000, salary_max=20000,
            date_scraped=t1, date_posted="2026-03-05",
        ),
        SimpleNamespace(
            title="dev", salary_min=None, salary_max=None,
            date_scraped=t2, date_posted=None,
        ),
        SimpleNamespace(
            title="dev", salary_min=50000, salary_max=50000,
            date_scraped=t3, date_posted="2026-04-01",
        ),
    ]

    result = summarize_time_trends(rows, "month")

    assert isinstance(result, TimeTrendResponse)
    assert result.period_count == 2
    assert result.total_listings == 3

    month1 = result.items[0]
    assert month1.period_start == "2026-03-01"
    assert month1.listings == 2
    assert month1.salary_visible_rows == 1
    assert month1.valid_salary_rows == 1
    assert month1.median_salary_midpoint == 15000.0
    assert month1.date_posted_listings == 1

    month2 = result.items[1]
    assert month2.period_start == "2026-04-01"
    assert month2.listings == 1
    assert month2.valid_salary_rows == 1
    assert month2.median_salary_midpoint == 50000.0
    assert month2.date_posted_listings == 1


def test_summarize_time_trends_skips_null_date_scraped():
    """Rows with null date_scraped are excluded from time trends."""
    t1 = datetime(2026, 3, 9, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            title="dev", salary_min=10000, salary_max=20000,
            date_scraped=t1, date_posted=None,
        ),
        SimpleNamespace(
            title="dev", salary_min=50000, salary_max=70000,
            date_scraped=None, date_posted="2026-03-01",
        ),
    ]

    result = summarize_time_trends(rows, "month")

    assert result.total_listings == 1
    assert result.period_count == 1
    assert result.items[0].listings == 1
