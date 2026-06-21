"""Tests for the skills extraction router and service layer."""


def test_extract_skills_basic(client):
    """POST /skills/extract detects multiple skills from text."""
    payload = {"text": "We need a Python developer with AWS and Docker experience"}
    response = client.post("/skills/extract", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "python" in data["skills"]
    assert "aws" in data["skills"]
    assert "docker" in data["skills"]
    assert data["count"] == 3


def test_extract_skills_no_match(client):
    """POST /skills/extract returns empty list when no skills match."""
    payload = {"text": "This is a generic description with no technology keywords"}
    response = client.post("/skills/extract", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["skills"] == []
    assert data["count"] == 0


def test_extract_skills_case_insensitive(client):
    """POST /skills/extract matches keywords regardless of case."""
    payload = {"text": "Experience with PYTHON, Sql, and Kubernetes"}
    response = client.post("/skills/extract", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "python" in data["skills"]
    assert "sql" in data["skills"]
    assert "kubernetes" in data["skills"]


def test_extract_skills_word_boundary(client):
    """POST /skills/extract uses word boundaries to avoid substring matches."""
    payload = {"text": "Experience with JavaScript and scalable systems"}
    response = client.post("/skills/extract", json=payload)
    assert response.status_code == 200
    data = response.json()
    # "java" should NOT match "JavaScript"
    assert "java" not in data["skills"]
    # "scala" should NOT match "scalable"
    assert "scala" not in data["skills"]


def test_extract_skills_empty_text(client):
    """POST /skills/extract returns 422 for empty text."""
    payload = {"text": ""}
    response = client.post("/skills/extract", json=payload)
    assert response.status_code == 422