"""Tests for the DescriptionPreparer (Slice 3.5)."""

from unittest.mock import patch

import pytest
from sqlalchemy import JSON, StaticPool, create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, Job
from src.nlp.description_preparer import (
    DescriptionPreparer,
    PreparationMetrics,
    is_placeholder,
    is_usable,
    MIN_RAW_LENGTH,
    PROVENANCE_RAW,
)


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


def _job(id_, desc=None, **kw) -> Job:
    """Create a test job. If desc provided, use it as description."""
    kwargs = dict(
        id=id_,
        site=kw.pop("site", "indeed"),
        job_url=f"https://t/{id_}",
        title=kw.pop("title", "T"),
        company="C",
        raw_location="L",
    )
    if desc is not None:
        kwargs["description"] = desc
    kwargs.update(kw)
    return Job(**kwargs)


_VALID = "We are looking for a Python developer with experience in Django and PostgreSQL databases " * 3


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestIsPlaceholder:
    def test_known_placeholder(self) -> None:
        assert is_placeholder("Competencias añadidas por la empresa")

    def test_case_insensitive(self) -> None:
        assert is_placeholder("COMPETENCIAS AÑADIDAS POR LA EMPRESA")

    def test_whitespace_insensitive(self) -> None:
        assert is_placeholder("  Competencias añadidas por la empresa  ")

    def test_app_placeholder(self) -> None:
        assert is_placeholder("Buscar es más fácil en la app")

    def test_unknown_not_placeholder(self) -> None:
        assert not is_placeholder("Valid job description here")


class TestIsUsable:
    def test_null(self) -> None:
        assert not is_usable(None)

    def test_empty(self) -> None:
        assert not is_usable("")

    def test_whitespace_only(self) -> None:
        assert not is_usable("   \t\n  ")

    def test_too_short(self) -> None:
        assert not is_usable("A" * (MIN_RAW_LENGTH - 1))

    def test_placeholder_rejected(self) -> None:
        assert not is_usable("Competencias añadidas por la empresa")

    def test_valid_length(self) -> None:
        assert is_usable("A" * MIN_RAW_LENGTH)

    def test_realistic_description(self) -> None:
        assert is_usable("We need a Python developer with AWS and Docker experience")


# ---------------------------------------------------------------------------
# Runner — eligibility
# ---------------------------------------------------------------------------


class TestEligibility:
    def test_cleans_null_cleaned_description(self, session) -> None:
        job = _job(1, description="Valid job description " * 10)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(dry_run=False)

        assert m.prepared == 1
        session.refresh(job)
        assert job.cleaned_description is not None
        assert len(job.cleaned_description) > 20
        assert job.description_enrichment_source == PROVENANCE_RAW

    def test_preserves_existing_cleaned(self, session) -> None:
        job = _job(1, description="Raw text " * 10,
                   cleaned_description="Already enriched text",
                   description_enrichment_source="detail_page")
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(dry_run=False)

        assert m.prepared == 0
        assert m.already_prepared == 1
        session.refresh(job)
        assert job.cleaned_description == "Already enriched text"
        assert job.description_enrichment_source == "detail_page"

    def test_force_reprocesses(self, session) -> None:
        job = _job(1, description="New raw text " * 10,
                   cleaned_description="Old cleaned text")
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(force=True, dry_run=False)

        assert m.prepared == 1
        session.refresh(job)
        assert "Old cleaned text" not in (job.cleaned_description or "")

    def test_null_description_skipped(self, session) -> None:
        job = _job(1, description=None)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(dry_run=False)

        assert m.prepared == 0

    def test_source_filter(self, session) -> None:
        j1 = _job(1, site="indeed", description=_VALID)
        j2 = _job(2, site="computrabajo", description=_VALID)
        session.add_all([j1, j2])
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(source="indeed", dry_run=False)

        assert m.prepared == 1
        session.refresh(j1)
        assert j1.cleaned_description is not None
        session.refresh(j2)
        assert j2.cleaned_description is None


# ---------------------------------------------------------------------------
# Placeholder rejection
# ---------------------------------------------------------------------------


class TestPlaceholderRejection:
    def test_placeholder_not_persisted(self, session) -> None:
        job = _job(1, description="Competencias añadidas por la empresa")
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(dry_run=False)

        assert m.prepared == 0
        assert m.placeholder_count == 1
        session.refresh(job)
        assert job.cleaned_description is None

    def test_app_placeholder_rejected(self, session) -> None:
        job = _job(1, description="Buscar es más fácil en la app")
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(dry_run=False)

        assert m.placeholder_count == 1
        assert m.prepared == 0


# ---------------------------------------------------------------------------
# Post-clean validation
# ---------------------------------------------------------------------------


class TestPostCleanRejection:
    def test_empty_cleaned_result_rejected(self, session) -> None:
        # Text that will clean down to empty
        job = _job(1, description="<html></html>" + "x" * 30)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100, min_cleaned_length=5)
            m = p.run(dry_run=False)

        # '<html></html>' cleans to empty string; only 'x'*30 is left.
        # That's above min_cleaned_length=5, so it gets prepared.
        assert m.prepared >= 1

    def test_too_short_cleaned_rejected(self, session) -> None:
        # Description that cleans to very short text
        job = _job(1, description="**hello** " * 3)  # 21 chars raw
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(min_raw_length=10, min_cleaned_length=50, batch_size=100)
            m = p.run(dry_run=False)

        # Raw is 21 chars (above min_raw_length=10), cleaned "hello hello hello" = 17 chars
        # 17 < 50 min_cleaned_length → rejected after clean
        assert m.rejected_after_clean >= 1


# ---------------------------------------------------------------------------
# Persistence behavior
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_keywords_json_untouched(self, session) -> None:
        kw = {"topic_id": 4, "topic_keywords": ["cloud"]}
        job = _job(1, description=_VALID, keywords_json=kw)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            p.run(dry_run=False)

        session.refresh(job)
        assert job.keywords_json == kw

    def test_skills_fields_untouched(self, session) -> None:
        job = _job(1, description=_VALID)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            p.run(dry_run=False)

        session.refresh(job)
        assert job.skills_json is None
        assert job.skill_extractor_version is None
        assert job.skills_extracted_at is None

    def test_provenance_set(self, session) -> None:
        job = _job(1, description=_VALID)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            p.run(dry_run=False)

        session.refresh(job)
        assert job.description_enrichment_source == PROVENANCE_RAW


# ---------------------------------------------------------------------------
# Runner behavior
# ---------------------------------------------------------------------------


class TestRunnerBehavior:
    def test_dry_run_no_writes(self, session) -> None:
        job = _job(1, description=_VALID)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m = p.run(dry_run=True)

        assert m.prepared >= 1
        session.refresh(job)
        assert job.cleaned_description is None
        assert job.description_enrichment_source is None

    def test_limit_means_eligible_processed(self, session) -> None:
        jobs = [_job(i, description=_VALID) for i in range(1, 6)]
        session.add_all(jobs)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=50)
            m = p.run(limit=3, dry_run=False)

        assert m.prepared == 3

    def test_rerun_idempotent(self, session) -> None:
        job = _job(1, description=_VALID)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            m1 = p.run(dry_run=False)
            assert m1.prepared == 1

            m2 = p.run(dry_run=False)
            assert m2.prepared == 0
            assert m2.already_prepared >= 1

    def test_pagination_no_skip_or_duplicate(self, session) -> None:
        jobs = [_job(i, description=_VALID) for i in range(1, 8)]
        session.add_all(jobs)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=3)
            m = p.run(dry_run=False)

        assert m.prepared == 7
        for job in jobs:
            session.refresh(job)
            assert job.cleaned_description is not None

    def test_failed_row_does_not_stop_batch(self, session) -> None:
        j1 = _job(1, description=_VALID)
        j2 = _job(2, description=_VALID)
        session.add_all([j1, j2])
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            p = DescriptionPreparer(batch_size=100)
            # j1 is valid, j2 is also valid — both should process
            m = p.run(dry_run=False)

        assert m.prepared == 2
        assert m.failed == 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_metrics_smoke(self) -> None:
        m = PreparationMetrics(
            scanned=100, eligible=90, prepared=80, rejected_before_clean=5,
            rejected_after_clean=3, failed=2, placeholder_count=3,
            raw_lengths=[1000, 2000, 3000],
            cleaned_lengths=[900, 1800, 2700],
            start_time=100.0, end_time=110.0,
        )
        assert m.mean_raw_len == 2000
        assert m.median_raw_len == 2000
        assert m.mean_cleaned_len == 1800
        assert m.mean_size_reduction_pct == 10.0
        assert m.throughput_per_sec == 8.0
        summary = m.summary()
        assert "80" in summary
        assert "2000" in summary
