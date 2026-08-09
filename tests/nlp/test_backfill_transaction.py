"""Isolated tests for transaction-failure isolation in backfill runners.

These tests use in-memory SQLite to prove that one failed row does not
poison the session or roll back previously-committed batches.

Do NOT run against the real Supabase database.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import JSON, StaticPool, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import Base, Job
from src.nlp.skill_enricher import SkillEnricher
from src.nlp.skill_extractor import SkillExtractor, reset_extractor
from src.nlp.skill_taxonomy import reset_taxonomy_cache


@pytest.fixture(autouse=True)
def _clear_caches():
    reset_taxonomy_cache()
    reset_extractor()
    yield
    reset_taxonomy_cache()
    reset_extractor()


@pytest.fixture
def engine():
    original_kw = Job.__table__.c.keywords_json.type
    original_skills = Job.__table__.c.skills_json.type
    Job.__table__.c.keywords_json.type = JSON()
    Job.__table__.c.skills_json.type = JSON()

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)

    Job.__table__.c.keywords_json.type = original_kw
    Job.__table__.c.skills_json.type = original_skills

    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _job(id_, desc, **kw) -> Job:
    return Job(
        id=id_,
        site="indeed",
        job_url=f"https://t/{id_}",
        title="T",
        company="C",
        raw_location="L",
        cleaned_description=desc,
        **kw,
    )


# ---------------------------------------------------------------------------
# Test: one failed UPDATE doesn't poison the session
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    def test_failed_row_does_not_block_next_batch(self, session) -> None:
        """Row A succeeds, Row B fails SQL, Row C in next batch succeeds."""
        import json

        extractor = SkillExtractor()
        version = extractor.taxonomy.version

        # Batch 1: job 1 succeeds
        j1 = _job(1, "Python developer " * 10)
        session.add(j1)
        session.commit()

        # Batch 2: job 2 fails (invalid JSONB that causes SQL error in persist)
        # We simulate this by making _persist raise an IntegrityError for job 2
        j2 = _job(2, "SQL developer " * 10)
        session.add(j2)
        session.commit()

        # Job 3: normal row
        j3 = _job(3, "Docker Kubernetes " * 10)
        session.add(j3)
        session.commit()

        call_count = [0]

        original_persist = SkillEnricher._persist

        def flaky_persist(self, sess, job, skills):
            call_count[0] += 1
            if job.id == 2:
                raise IntegrityError("SIMULATED", {}, None)
            return original_persist(self, sess, job, skills)

        with patch.object(SkillEnricher, "_persist", flaky_persist):
            with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
                enricher = SkillEnricher(extractor, version, batch_size=1)
                metrics = enricher.run(dry_run=False)

        # Job 1 and 3 should be processed; job 2 failed
        session.refresh(j1)
        session.refresh(j3)

        assert j1.skills_json is not None
        assert "python" in json.loads(j1.skills_json) if isinstance(j1.skills_json, str) else "python" in j1.skills_json
        assert j3.skills_json is not None
        assert metrics.processed >= 2
        assert metrics.failed >= 1

    def test_commit_failure_rolls_back_batch_only(self, session) -> None:
        """A batch commit failure rolls back that batch; prior batches survive."""
        extractor = SkillExtractor()
        version = extractor.taxonomy.version

        j1 = _job(1, "Python " * 10)
        j2 = _job(2, "SQL " * 10)
        session.add_all([j1, j2])
        session.commit()

        original_commit = Session.commit
        commit_counts = [0]

        def flaky_commit(self_session):
            commit_counts[0] += 1
            if commit_counts[0] == 2:  # second batch fails
                raise RuntimeError("Simulated commit failure")
            return original_commit(self_session)

        with patch.object(Session, "commit", flaky_commit):
            with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
                enricher = SkillEnricher(extractor, version, batch_size=1)
                try:
                    enricher.run(dry_run=False)
                except RuntimeError:
                    pass  # expected

        # Job 1 (first batch) should be committed; job 2 (second batch) rolled back
        session.expire_all()
        session.refresh(j1)
        session.refresh(j2)

        assert j1.skills_json is not None
        # j2 should be NULL because its batch was rolled back
        assert j2.skills_json is None
