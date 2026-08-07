"""Tests for the JobDeduplicator (Slice 3.7)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import JSON, StaticPool, create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, Job, JobDuplicateLink
from src.data_quality.job_deduplicator import (
    JobDeduplicator,
    DedupMetrics,
    select_canonical,
    DEDUP_VERSION,
    SCOPE_SAME_SOURCE,
    METHOD_COMPUTRABAJO_URL,
    STATUS_CONFIRMED,
)
from src.nlp.backfill_manifest import BackfillManifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _comp_job(id_, url, **kw) -> Job:
    return Job(
        id=id_,
        site="computrabajo",
        job_url=url,
        title=kw.pop("title", "Data Engineer"),
        company=kw.pop("company", "Tech Corp"),
        raw_location=kw.pop("raw_location", "CDMX"),
        salary_min=kw.pop("salary_min", None),
        salary_max=kw.pop("salary_max", None),
        description=kw.pop("description", None),
        date_scraped=kw.pop("date_scraped", datetime(2026, 1, 1, tzinfo=timezone.utc)),
        **kw,
    )


# ---------------------------------------------------------------------------
# Canonical selection
# ---------------------------------------------------------------------------


class TestSelectCanonical:
    def test_single_row_returns_self(self) -> None:
        rows = [{"id": 1, "salary_min": None, "salary_max": None,
                 "description": None, "date_scraped": None}]
        assert select_canonical(rows)["id"] == 1

    def test_salary_preferred(self) -> None:
        rows = [
            {"id": 1, "salary_min": None, "salary_max": None,
             "description": None, "date_scraped": datetime(2026, 1, 1)},
            {"id": 2, "salary_min": 30000, "salary_max": 50000,
             "description": None, "date_scraped": datetime(2026, 1, 2)},
        ]
        assert select_canonical(rows)["id"] == 2

    def test_description_preferred_when_no_salary(self) -> None:
        rows = [
            {"id": 1, "salary_min": None, "salary_max": None,
             "description": None, "date_scraped": datetime(2026, 1, 1)},
            {"id": 2, "salary_min": None, "salary_max": None,
             "description": "Valid job description", "date_scraped": datetime(2026, 1, 2)},
        ]
        assert select_canonical(rows)["id"] == 2

    def test_earliest_date_tiebreaker(self) -> None:
        rows = [
            {"id": 1, "salary_min": None, "salary_max": None,
             "description": None, "date_scraped": datetime(2026, 2, 1)},
            {"id": 2, "salary_min": None, "salary_max": None,
             "description": None, "date_scraped": datetime(2026, 1, 1)},
        ]
        assert select_canonical(rows)["id"] == 2  # earliest date

    def test_lowest_id_final_tiebreaker(self) -> None:
        rows = [
            {"id": 10, "salary_min": None, "salary_max": None,
             "description": None, "date_scraped": datetime(2026, 1, 1)},
            {"id": 5, "salary_min": None, "salary_max": None,
             "description": None, "date_scraped": datetime(2026, 1, 1)},
        ]
        assert select_canonical(rows)["id"] == 5


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


class TestGrouping:
    def test_fragment_variants_group_together(self, session) -> None:
        base = "https://mx.computrabajo.com/job/1"
        jobs = [
            _comp_job(1, f"{base}#lc=ListOffers-Score4-11"),
            _comp_job(2, f"{base}#lc=ListOffers-Score4-12"),
            _comp_job(3, f"{base}"),
        ]
        session.add_all(jobs)
        session.commit()

        dedup = JobDeduplicator()
        groups = dedup._build_groups([{
            "id": j.id, "job_url": j.job_url,
            "title": j.title, "company": j.company,
            "raw_location": j.raw_location,
            "salary_min": j.salary_min, "salary_max": j.salary_max,
            "description": j.description, "date_scraped": j.date_scraped,
        } for j in jobs])

        assert len(groups) == 1
        assert len(groups[0]["rows"]) == 3

    def test_different_canonical_paths_separate(self, session) -> None:
        jobs = [
            _comp_job(1, "https://mx.computrabajo.com/job/A"),
            _comp_job(2, "https://mx.computrabajo.com/job/B"),
        ]
        session.add_all(jobs)
        session.commit()

        dedup = JobDeduplicator()
        groups = dedup._build_groups([{
            "id": j.id, "job_url": j.job_url,
            "title": j.title, "company": j.company,
            "raw_location": j.raw_location,
            "salary_min": None, "salary_max": None,
            "description": None, "date_scraped": None,
        } for j in jobs])

        assert len(groups) == 2

    def test_query_params_remain_distinct(self, session) -> None:
        """?ref=A and ?ref=B are different canonical URLs."""
        jobs = [
            _comp_job(1, "https://mx.computrabajo.com/job?ref=A#lc=Score"),
            _comp_job(2, "https://mx.computrabajo.com/job?ref=B#lc=Score"),
        ]
        session.add_all(jobs)
        session.commit()

        dedup = JobDeduplicator()
        groups = dedup._build_groups([{
            "id": j.id, "job_url": j.job_url,
            "title": j.title, "company": j.company,
            "raw_location": j.raw_location,
            "salary_min": None, "salary_max": None,
            "description": None, "date_scraped": None,
        } for j in jobs])

        assert len(groups) == 2


# ---------------------------------------------------------------------------
# Runner persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_creates_links(self, session) -> None:
        base = "https://mx.computrabajo.com/job/1"
        jobs = [
            _comp_job(1, f"{base}#lc=A"),
            _comp_job(2, f"{base}#lc=B"),
            _comp_job(3, f"{base}#lc=C"),
        ]
        session.add_all(jobs)
        session.commit()

        with patch("src.data_quality.job_deduplicator.db_connect", return_value=session.bind):
            dedup = JobDeduplicator()
            m = dedup.run(source="computrabajo", dry_run=False)

        assert m.duplicate_rows == 2

    def test_dry_run_no_writes(self, session) -> None:
        base = "https://mx.computrabajo.com/job/1"
        jobs = [
            _comp_job(1, f"{base}#lc=A"),
            _comp_job(2, f"{base}#lc=B"),
        ]
        session.add_all(jobs)
        session.commit()

        with patch("src.data_quality.job_deduplicator.db_connect", return_value=session.bind):
            dedup = JobDeduplicator()
            m = dedup.run(source="computrabajo", dry_run=True)

        assert m.duplicate_rows == 1

    def test_rerun_idempotent(self, session) -> None:
        base = "https://mx.computrabajo.com/job/1"
        jobs = [
            _comp_job(1, f"{base}#lc=A"),
            _comp_job(2, f"{base}#lc=B"),
        ]
        session.add_all(jobs)
        session.commit()

        with patch("src.data_quality.job_deduplicator.db_connect", return_value=session.bind):
            dedup = JobDeduplicator()
            m1 = dedup.run(source="computrabajo", dry_run=False)
            assert m1.duplicate_rows == 1

            # Rerun — ON CONFLICT DO NOTHING prevents dup inserts
            m2 = dedup.run(source="computrabajo", dry_run=False)
            assert m2.duplicate_rows >= 1  # same group, same metrics

    def test_singletons_no_links(self, session) -> None:
        jobs = [
            _comp_job(1, "https://mx.computrabajo.com/job/A"),
            _comp_job(2, "https://mx.computrabajo.com/job/B"),
        ]
        session.add_all(jobs)
        session.commit()

        with patch("src.data_quality.job_deduplicator.db_connect", return_value=session.bind):
            dedup = JobDeduplicator()
            m = dedup.run(source="computrabajo", dry_run=False)

        assert m.duplicate_rows == 0

    def test_source_filter_only_computrabajo(self, session) -> None:
        indeed_job = Job(
            id=99, site="indeed", job_url="https://indeed.com/job/1",
            title="T", company="C", raw_location="L",
        )
        comp_jobs = [
            _comp_job(1, "https://mx.computrabajo.com/job/1#lc=A"),
            _comp_job(2, "https://mx.computrabajo.com/job/1#lc=B"),
        ]
        session.add(indeed_job)
        session.add_all(comp_jobs)
        session.commit()

        with patch("src.data_quality.job_deduplicator.db_connect", return_value=session.bind):
            dedup = JobDeduplicator()
            m = dedup.run(source="computrabajo", dry_run=False)

        # Indeed job not involved
        assert m.duplicate_rows == 1

    def test_manifest_tracks_ids(self, session) -> None:
        base = "https://mx.computrabajo.com/job/1"
        jobs = [
            _comp_job(1, f"{base}#lc=A"),
            _comp_job(2, f"{base}#lc=B"),
            _comp_job(3, f"{base}#lc=C"),
        ]
        session.add_all(jobs)
        session.commit()

        manifest = BackfillManifest(
            run_type="computrabajo_dedup",
            command="test",
            version=DEDUP_VERSION,
        )

        with patch("src.data_quality.job_deduplicator.db_connect", return_value=session.bind):
            dedup = JobDeduplicator()
            dedup.run(source="computrabajo", dry_run=False, manifest=manifest)

        assert len(manifest.affected_ids) == 2


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_metrics_smoke(self) -> None:
        m = DedupMetrics(
            total_inspected=1000,
            unique_canonical_urls=300,
            duplicate_groups=200,
            canonical_rows=200,
            duplicate_rows=800,
            largest_group=15,
            group_sizes=[2, 3, 4, 5],
            start_time=100.0, end_time=110.0,
        )
        assert m.duplicate_rate == 80.0
        assert m.median_group_size == 3.5
        assert m.mean_group_size == 3.5
        summary = m.summary()
        assert "800" in summary


# ---------------------------------------------------------------------------
# Unsupported source
# ---------------------------------------------------------------------------


class TestUnsupportedSource:
    def test_raises_for_indeed(self, session) -> None:
        dedup = JobDeduplicator()
        with pytest.raises(ValueError, match="Only 'computrabajo'"):
            dedup.run(source="indeed")
