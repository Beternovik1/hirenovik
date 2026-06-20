"""Tests for the jobs router and service layer.

Uses a SQLite in-memory database to exercise the full request pipeline:
router -> service -> ORM -> pydantic schema -> JSON response.

The ``mock_db_session`` fixture in conftest.py handles DB setup and the
``get_db`` dependency override automatically.
"""

from src.api.schemas.job import JobListResponse, JobResponse


# ---------------------------------------------------------------------------
# GET /jobs — list endpoint
# ---------------------------------------------------------------------------


def test_list_jobs_no_filters(client, mock_db_session):
    """GET /jobs returns all jobs when no filters are applied."""
    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["size"] == 20
    assert len(data["items"]) == 3


def test_list_jobs_with_career_filter(client, mock_db_session):
    """GET /jobs?career=Data Engineer returns only matching jobs."""
    response = client.get("/jobs?career=Data%20Engineer")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["career"] == "Data Engineer"


def test_list_jobs_with_country_code_filter(client, mock_db_session):
    """GET /jobs?country_code=MX returns MX jobs."""
    response = client.get("/jobs?country_code=MX")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    for item in data["items"]:
        assert item["country_code"] == "MX"


def test_list_jobs_with_job_type_filter(client, mock_db_session):
    """GET /jobs?job_type=remoto returns only remote jobs."""
    response = client.get("/jobs?job_type=remoto")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert item["job_type"] == "remoto"


def test_list_jobs_with_pagination(client, mock_db_session):
    """GET /jobs?page=1&size=2 returns paginated results."""
    response = client.get("/jobs?page=1&size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["size"] == 2
    assert len(data["items"]) == 2


def test_list_jobs_empty_result(client, mock_db_session):
    """GET /jobs?career=nonexistent returns empty list with total 0."""
    response = client.get("/jobs?career=NonexistentCareer")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


# ---------------------------------------------------------------------------
# GET /jobs/{job_id} — detail endpoint
# ---------------------------------------------------------------------------


def test_get_job_found(client, mock_db_session):
    """GET /jobs/{id} returns a single job."""
    response = client.get("/jobs/1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1
    assert data["title"] == "DATA ENGINEER"
    assert data["career"] == "Data Engineer"
    assert data["company"] == "Tech Corp"


def test_get_job_not_found(client, mock_db_session):
    """GET /jobs/{id} returns 404 for nonexistent job."""
    response = client.get("/jobs/9999")
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]