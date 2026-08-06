"""Tests for the jobs table skill-extraction columns (Slice 2).

These tests verify the NULL semantics, JSONB typing, and model-level
contract of the three new columns before any backfill or enrichment
code populates them.
"""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, create_engine, StaticPool
from sqlalchemy.orm import Session

from src.database.models import Base, Job


@pytest.fixture
def engine():
    """In-memory SQLite engine with the jobs table schema.

    JSONB columns are swapped to JSON during table creation so SQLite
    can render the DDL, then restored afterwards.
    """
    original_kw_type = Job.__table__.c.keywords_json.type
    original_skills_type = Job.__table__.c.skills_json.type
    Job.__table__.c.keywords_json.type = JSON()
    Job.__table__.c.skills_json.type = JSON()

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)

    # Restore types so other test modules get the real column types.
    Job.__table__.c.keywords_json.type = original_kw_type
    Job.__table__.c.skills_json.type = original_skills_type

    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine):
    """SQLAlchemy session bound to the test engine."""
    with Session(engine, expire_on_commit=False) as s:
        yield s


# ---------------------------------------------------------------------------
# Column existence and type
# ---------------------------------------------------------------------------


class TestColumnExistence:
    def test_skills_json_column_exists(self, engine) -> None:
        cols = {c.name for c in Job.__table__.columns}
        assert "skills_json" in cols

    def test_skill_extractor_version_column_exists(self, engine) -> None:
        cols = {c.name for c in Job.__table__.columns}
        assert "skill_extractor_version" in cols

    def test_skills_extracted_at_column_exists(self, engine) -> None:
        cols = {c.name for c in Job.__table__.columns}
        assert "skills_extracted_at" in cols

    def test_keywords_json_still_exists(self, engine) -> None:
        cols = {c.name for c in Job.__table__.columns}
        assert "keywords_json" in cols


# ---------------------------------------------------------------------------
# NULL semantics
# ---------------------------------------------------------------------------


class TestNullSemantics:
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_default_null(self, session) -> None:
        """New row has NULL for all three skill columns."""
        job = Job(
            id=999601,
            site="test",
            job_url="https://test.example/1",
            title="TEST JOB",
            company="Test Inc",
            raw_location="Test",
            status="NEW",
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.skills_json is None
        assert job.skill_extractor_version is None
        assert job.skills_extracted_at is None

    def test_can_set_skills_json_to_list(self, session) -> None:
        """skills_json accepts a JSON list of canonical keys."""
        job = Job(
            id=999602,
            site="test",
            job_url="https://test.example/2",
            title="PYTHON DEV",
            company="Test Inc",
            raw_location="Test",
            skills_json=["python", "sql", "aws"],
            skill_extractor_version="1.0.0",
            skills_extracted_at=self.now,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.skills_json == ["python", "sql", "aws"]
        assert job.skill_extractor_version == "1.0.0"
        # SQLite stores datetime without timezone; compare the value
        assert job.skills_extracted_at is not None
        assert job.skills_extracted_at.replace(tzinfo=timezone.utc) == self.now

    def test_can_set_skills_json_to_empty_list(self, session) -> None:
        """skills_json = [] means processed, no skills found (≠ NULL)."""
        job = Job(
            id=999603,
            site="test",
            job_url="https://test.example/3",
            title="CALL CENTER AGENT",
            company="Test Inc",
            raw_location="Test",
            skills_json=[],
            skill_extractor_version="1.0.0",
            skills_extracted_at=self.now,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.skills_json == []
        assert job.skill_extractor_version == "1.0.0"

    def test_null_vs_empty_semantics_distinct(self, session) -> None:
        """NULL (unprocessed) and [] (processed, zero matches) are different states."""
        unprocessed = Job(
            id=999604,
            site="test",
            job_url="https://test.example/4",
            title="UNPROCESSED",
            company="T",
            raw_location="T",
        )
        processed_empty = Job(
            id=999605,
            site="test",
            job_url="https://test.example/5",
            title="PROCESSED EMPTY",
            company="T",
            raw_location="T",
            skills_json=[],
            skill_extractor_version="1.0.0",
        )
        session.add_all([unprocessed, processed_empty])
        session.commit()

        # Query: count unprocessed rows
        null_count = session.query(Job).filter(Job.skills_json.is_(None)).count()
        assert null_count >= 1

        # Query: count processed-empty rows
        empty_count = session.query(Job).filter(Job.skills_json == []).first()
        assert empty_count is not None
        assert empty_count.skills_json == []


# ---------------------------------------------------------------------------
# JSONB serialisation round-trip
# ---------------------------------------------------------------------------


class TestJsonbRoundTrip:
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_round_trip_preserves_order(self, session) -> None:
        """Canonical skill lists preserve insertion order on read-back."""
        skills = ["terraform", "kubernetes", "docker", "aws"]
        job = Job(
            id=999606,
            site="test",
            job_url="https://test.example/6",
            title="DEVOPS",
            company="Test Inc",
            raw_location="Test",
            skills_json=skills,
            skill_extractor_version="1.0.0",
            skills_extracted_at=self.now,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.skills_json == skills

    def test_can_serialize_to_json(self, session) -> None:
        job = Job(
            id=999607,
            site="test",
            job_url="https://test.example/7",
            title="DATA ENG",
            company="Test Inc",
            raw_location="Test",
            skills_json=["python", "spark", "kafka", "airflow", "dbt"],
            skill_extractor_version="1.0.0",
            skills_extracted_at=self.now,
        )
        session.add(job)
        session.commit()

        serialized = json.dumps(job.skills_json)
        assert '"python"' in serialized
        assert json.loads(serialized) == ["python", "spark", "kafka", "airflow", "dbt"]

    def test_empty_list_serializes(self, session) -> None:
        job = Job(
            id=999608,
            site="test",
            job_url="https://test.example/8",
            title="NO SKILLS",
            company="T",
            raw_location="T",
            skills_json=[],
            skill_extractor_version="1.0.0",
        )
        session.add(job)
        session.commit()
        assert json.dumps(job.skills_json) == "[]"


# ---------------------------------------------------------------------------
# Existing columns unaffected
# ---------------------------------------------------------------------------


class TestExistingColumnsUnaffected:
    def test_keywords_json_still_works(self, session) -> None:
        """keywords_json still accepts its existing BERTopic payload shape."""
        job = Job(
            id=999609,
            site="test",
            job_url="https://test.example/9",
            title="TOPIC JOB",
            company="T",
            raw_location="T",
            keywords_json={"topic_id": 4, "topic_keywords": ["cloud", "aws"]},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.keywords_json["topic_id"] == 4
        assert job.keywords_json["topic_keywords"] == ["cloud", "aws"]

    def test_both_columns_independent(self, session) -> None:
        """skills_json and keywords_json can coexist on the same row."""
        job = Job(
            id=999610,
            site="test",
            job_url="https://test.example/10",
            title="BOTH",
            company="T",
            raw_location="T",
            keywords_json={"topic_id": 0, "topic_keywords": ["python", "ml"]},
            skills_json=["python", "scikit_learn", "pandas"],
            skill_extractor_version="1.0.0",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.keywords_json is not None
        assert job.skills_json is not None
        assert "python" in job.skills_json
        assert job.keywords_json["topic_id"] == 0
