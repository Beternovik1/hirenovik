"""Tests for the SkillEnricher backfill runner (Slice 3)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import JSON, StaticPool, create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, Job
from src.nlp.skill_enricher import SkillEnricher, EnrichmentMetrics
from src.nlp.skill_extractor import SkillExtractor, reset_extractor
from src.nlp.skill_taxonomy import load_taxonomy, reset_taxonomy_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches():
    reset_taxonomy_cache()
    reset_extractor()
    yield
    reset_taxonomy_cache()
    reset_extractor()


@pytest.fixture
def engine():
    """In-memory SQLite with JSONB columns swapped to JSON."""
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


@pytest.fixture
def extractor():
    return SkillExtractor()


@pytest.fixture
def version():
    return load_taxonomy().version


def _make_job(id_: int, title: str, desc: str, **kw) -> Job:
    return Job(
        id=id_,
        site=kw.pop("site", "indeed"),
        job_url=f"https://test.example/{id_}",
        title=title,
        company="Test Corp",
        raw_location="Test",
        cleaned_description=desc,
        **kw,
    )


# ---------------------------------------------------------------------------
# Unit tests — _filter_eligible
# ---------------------------------------------------------------------------


class TestFilterEligible:
    def test_null_skills_json_is_eligible(self, extractor, version) -> None:
        enricher = SkillEnricher(extractor, version)
        job = _make_job(1, "T", "desc", skills_json=None)
        eligible = enricher._filter_eligible([job], force=False)
        assert len(eligible) == 1

    def test_current_version_is_skipped(self, extractor, version) -> None:
        enricher = SkillEnricher(extractor, version)
        job = _make_job(1, "T", "desc",
                        skills_json=["python"],
                        skill_extractor_version=version)
        eligible = enricher._filter_eligible([job], force=False)
        assert len(eligible) == 0

    def test_outdated_version_is_eligible(self, extractor, version) -> None:
        enricher = SkillEnricher(extractor, version)
        job = _make_job(1, "T", "desc",
                        skills_json=["python"],
                        skill_extractor_version="0.9.0")
        eligible = enricher._filter_eligible([job], force=False)
        assert len(eligible) == 1

    def test_force_reprocesses_current(self, extractor, version) -> None:
        enricher = SkillEnricher(extractor, version)
        job = _make_job(1, "T", "desc",
                        skills_json=["python"],
                        skill_extractor_version=version)
        eligible = enricher._filter_eligible([job], force=True)
        assert len(eligible) == 1

    def test_empty_skills_json_skipped_if_current(self, extractor, version) -> None:
        enricher = SkillEnricher(extractor, version)
        job = _make_job(1, "T", "desc",
                        skills_json=[],
                        skill_extractor_version=version)
        eligible = enricher._filter_eligible([job], force=False)
        assert len(eligible) == 0


# ---------------------------------------------------------------------------
# Integration tests — full pipeline (patched DB)
# ---------------------------------------------------------------------------


class TestRunDefaultMode:
    def test_processes_null_skills_json(self, session, extractor, version) -> None:
        job = _make_job(1, "PYTHON DEV", "Python and SQL experience")
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 1
        assert metrics.with_skills == 1
        session.refresh(job)
        assert "python" in job.skills_json
        assert "sql" in job.skills_json
        assert job.skill_extractor_version == version
        assert job.skills_extracted_at is not None

    def test_skips_already_current(self, session, extractor, version) -> None:
        job = _make_job(1, "T", "desc",
                        skills_json=["python"],
                        skill_extractor_version=version)
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 0
        assert metrics.skipped == 1

    def test_no_description_is_not_fetched(self, session, extractor, version) -> None:
        job = _make_job(1, "T", "")
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 0

    def test_null_description_is_not_fetched(self, session, extractor, version) -> None:
        job = _make_job(1, "T", "original desc")
        job.cleaned_description = None
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 0


class TestRunZeroMatch:
    def test_zero_match_persists_empty_list(self, session, extractor, version) -> None:
        job = _make_job(1, "CALL CENTER", "Answer phones and emails")
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 1
        assert metrics.zero_skills == 1
        session.refresh(job)
        assert job.skills_json == []
        assert job.skill_extractor_version == version


class TestRunDryRun:
    def test_dry_run_does_not_write(self, session, extractor, version) -> None:
        job = _make_job(1, "PYTHON DEV", "Python experience required")
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=True)

        assert metrics.processed == 1
        assert metrics.with_skills == 1
        # Verify no writes
        session.refresh(job)
        assert job.skills_json is None
        assert job.skill_extractor_version is None


class TestRunIdempotency:
    def test_rerun_is_idempotent(self, session, extractor, version) -> None:
        jobs = [
            _make_job(1, "A", "Python dev"),
            _make_job(2, "B", "SQL analyst"),
            _make_job(3, "C", "Docker and Kubernetes engineer"),
        ]
        session.add_all(jobs)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)

            # First run
            m1 = enricher.run(dry_run=False)
            assert m1.processed == 3

            # Second run — all already current, should skip
            m2 = enricher.run(dry_run=False)
            assert m2.processed == 0
            assert m2.skipped == 3

    def test_force_reprocesses_all(self, session, extractor, version) -> None:
        job = _make_job(1, "A", "Python dev",
                        skills_json=["python"],
                        skill_extractor_version=version)
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(force=True, dry_run=False)

        assert metrics.processed == 1


class TestRunVersionAware:
    def test_reprocesses_outdated_version(self, session, extractor, version) -> None:
        job = _make_job(1, "A", "Python SQL",
                        skills_json=["python"],
                        skill_extractor_version="0.5.0",
                        skills_extracted_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 1
        session.refresh(job)
        assert job.skill_extractor_version == version
        assert "sql" in job.skills_json  # Now catches SQL too


class TestRunLimit:
    def test_limit_respected(self, session, extractor, version) -> None:
        jobs = [_make_job(i, f"J{i}", "Python") for i in range(1, 11)]
        session.add_all(jobs)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=5)
            metrics = enricher.run(limit=3, dry_run=False)

        assert metrics.processed == 3


class TestRunSourceFilter:
    def test_source_filter(self, session, extractor, version) -> None:
        j1 = _make_job(1, "A", "Python", site="indeed")
        j2 = _make_job(2, "B", "SQL", site="computrabajo")
        session.add_all([j1, j2])
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(source="indeed", dry_run=False)

        assert metrics.processed == 1
        session.refresh(j1)
        assert j1.skills_json is not None
        session.refresh(j2)
        assert j2.skills_json is None


class TestRunKeywordsJsonUntouched:
    def test_keywords_json_not_modified(self, session, extractor, version) -> None:
        existing_kw = {"topic_id": 4, "topic_keywords": ["cloud", "aws"]}
        job = _make_job(1, "A", "Python", keywords_json=existing_kw)
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            enricher.run(dry_run=False)

        session.refresh(job)
        assert job.keywords_json == existing_kw
        assert "python" in job.skills_json


class TestRunPagination:
    def test_pagination_does_not_skip_or_duplicate(self, session, extractor, version) -> None:
        jobs = [_make_job(i, f"J{i}", "Python SQL Docker") for i in range(1, 11)]
        session.add_all(jobs)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=3)
            metrics = enricher.run(dry_run=False)

        assert metrics.processed == 10
        # Verify all 10 have skills
        for job in jobs:
            session.refresh(job)
            assert job.skills_json is not None
            assert len(job.skills_json) > 0


class TestRunFailedRowDoesNotStopBatch:
    def test_failure_continues(self, session, extractor, version) -> None:
        j1 = _make_job(1, "OK", "Python")
        j2 = _make_job(2, "OK", "SQL")
        session.add_all([j1, j2])
        session.commit()

        # Simulate one row failing
        original_extract = extractor.extract
        call_count = [0]

        def flaky_extract(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return original_extract(text)
            if call_count[0] == 2:
                raise RuntimeError("simulated failure")
            return original_extract(text)

        extractor.extract = flaky_extract

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            enricher = SkillEnricher(extractor, version, batch_size=100)
            metrics = enricher.run(dry_run=False)

        # One processed, one failed
        assert metrics.processed >= 1
        assert metrics.failed >= 1


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_metrics_smoke(self) -> None:
        m = EnrichmentMetrics(
            scanned=100, eligible=80, processed=75, with_skills=60,
            zero_skills=15, skipped=20, failed=2, total_skills_assigned=240,
            skills_per_listing=[3]*60 + [0]*15,
            start_time=100.0, end_time=110.0,
            extractor_version="1.0.0",
        )
        assert m.mean_skills == 2.4
        assert m.median_skills == 3.0
        assert m.max_skills == 3
        assert m.throughput_per_sec == 7.5
        summary = m.summary()
        assert "1.0.0" in summary
        assert "75" in summary
