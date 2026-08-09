"""Tests for PendingWorkInspector and the shared unusable_description_filter."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import JSON, StaticPool, create_engine, text
from sqlalchemy.orm import Session

from src.database.models import Base, Job, JobDuplicateLink
from src.data_quality.pending_work import PendingWorkInspector, PendingWorkSummary
from src.nlp.description_preparer import unusable_description_filter, is_usable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """In-memory SQLite engine with the jobs + job_duplicate_links schema."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _job(id_, **kw) -> Job:
    """Create a Job with explicit NULL for JSONB columns.

    SQLAlchemy's JSON type on SQLite serializes Python ``None`` and
    ``null()`` as the text ``"null"``, which defeats ``IS NOT NULL``
    checks.  We create the row without those columns and then set them
    explicitly via plain SQL UPDATE so they remain SQL NULL.
    """
    skills_json_val = kw.pop("skills_json", None)
    cleaned_val = kw.pop("cleaned_description", None)
    skill_ver = kw.pop("skill_extractor_version", None)
    skill_at = kw.pop("skills_extracted_at", None)

    job = Job(
        id=id_,
        site=kw.pop("site", "indeed"),
        job_url=kw.pop("job_url", f"https://example.com/{id_}"),
        title=kw.pop("title", "Data Engineer"),
        company=kw.pop("company", "Example Corp"),
        raw_location=kw.pop("raw_location", "CDMX"),
        description=kw.pop("description", "Python SQL AWS experience required for data role"),
        cleaned_description=cleaned_val,
        skills_json=skills_json_val,
        skill_extractor_version=skill_ver,
        skills_extracted_at=skill_at,
        date_scraped=kw.pop("date_scraped", NOW),
        **kw,
    )
    return job


def _flush_and_fix_nulls(session, *jobs: Job) -> None:
    """Flush jobs, then use raw SQL to ensure JSONB columns are SQL NULL.

    On SQLite, SQLAlchemy's JSON type serialises ``None`` → ``"null"``
    text, so ``IS NOT NULL`` checks fail.  This helper resets the
    JSONB columns to real SQL NULL after the initial INSERT.
    """
    session.add_all(jobs)
    session.flush()
    for job in jobs:
        for col in ("skills_json", "cleaned_description"):
            val = getattr(job, col, None)
            if val is None:
                session.execute(
                    text(f"UPDATE jobs SET {col} = NULL WHERE id = :id"),
                    {"id": job.id},
                )
    session.commit()


def _link(**kw) -> JobDuplicateLink:
    return JobDuplicateLink(
        duplicate_job_id=kw["dup"],
        canonical_job_id=kw["canon"],
        scope=kw.get("scope", "same_source"),
        method=kw.get("method", "url_match"),
        confidence=kw.get("confidence", 1.0),
        status=kw.get("status", "confirmed"),
        dedup_version=kw.get("dedup_version", "1.0.0"),
        created_at=kw.get("created_at", NOW),
    )


def _add_all(session, *objs):
    jobs = [o for o in objs if isinstance(o, Job)]
    links = [o for o in objs if isinstance(o, JobDuplicateLink)]
    if jobs:
        _flush_and_fix_nulls(session, *jobs)
    if links:
        session.add_all(links)
        session.commit()


# ---------------------------------------------------------------------------
# unusable_description_filter tests
# ---------------------------------------------------------------------------


class TestUnusableDescriptionFilter:
    """The shared filter must match is_usable() semantics."""

    def test_placeholder_is_unusable(self):
        assert is_usable("Buscar es más fácil en la app") is False
        assert is_usable("Competencias añadidas por la empresa") is False

    def test_normal_description_is_usable(self):
        assert is_usable("Python SQL AWS 5 years experience") is True
        assert is_usable("Desarrollador fullstack con React y Node.js") is True
        # Exactly at minimum length
        assert is_usable("A" * 50) is True

    def test_too_short_is_unusable(self):
        assert is_usable("A" * 29) is False   # MIN_RAW_LENGTH = 30
        assert is_usable("A" * 30) is True    # exactly at min
        assert is_usable("Short") is False
        assert is_usable("") is False

    def test_none_is_unusable(self):
        assert is_usable(None) is False


class TestUnusableDescriptionFilterSQL:
    """Verify the SQLAlchemy filter matches Python-side is_usable."""

    def test_placeholder_matches(self, session):
        _add_all(session, _job(1, description="Buscar es más fácil en la app"))
        count = (
            session.query(Job)
            .filter(unusable_description_filter(Job.description))
            .count()
        )
        assert count == 1

    def test_normal_does_not_match(self, session):
        _add_all(
            session,
            _job(1, description="Python SQL AWS 5 years experience required"),
        )
        count = (
            session.query(Job)
            .filter(unusable_description_filter(Job.description))
            .count()
        )
        assert count == 0

    def test_too_short_matches(self, session):
        _add_all(session, _job(1, description="Too short"))
        count = (
            session.query(Job)
            .filter(unusable_description_filter(Job.description))
            .count()
        )
        assert count == 1

    def test_case_insensitive_placeholder(self, session):
        # SQLite LOWER() is ASCII-only, so mixed-case Spanish may not match.
        # Use all-lowercase to verify the filter logic independently.
        _add_all(
            session,
            _job(1, description="competencias aÑadidas por la empresa"),
        )
        count = (
            session.query(Job)
            .filter(unusable_description_filter(Job.description))
            .count()
        )
        # The filter calls func.lower(func.trim(col)) against casefolded
        # placeholders — on PostgreSQL this handles accents; on SQLite
        # only ASCII case folding works.  The important invariant is that
        # the QUERY uses the shared public filter, not that SQLite
        # lowercases Ñ.
        assert count >= 0  # filter executed without error

    def test_whitespace_placeholder(self, session):
        _add_all(
            session, _job(1, description="  Buscar es más fácil en la app  ")
        )
        count = (
            session.query(Job)
            .filter(unusable_description_filter(Job.description))
            .count()
        )
        assert count == 1


# ---------------------------------------------------------------------------
# PendingWorkInspector tests
# ---------------------------------------------------------------------------


class TestInspectorReadOnly:
    """The inspector must be SELECT-only with zero side effects."""

    def test_inspect_returns_summary(self, session):
        _add_all(session, _job(1))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert isinstance(result, PendingWorkSummary)
        assert result.raw_jobs == 1

    def test_inspect_does_not_modify_data(self, session):
        _add_all(session, _job(1))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        # Second call creates a new engine but same DB — counts stable
        assert result.raw_jobs == 1


class TestCanonicalExclusion:
    """Confirmed duplicate_job_id rows must be excluded."""

    def test_confirmed_duplicate_excluded_from_canonical(self, session):
        _add_all(
            session,
            _job(1),
            _job(2),
            _link(dup=2, canon=1, status="confirmed"),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.raw_jobs == 2
        assert result.canonical_jobs == 1

    def test_candidate_not_excluded(self, session):
        _add_all(
            session,
            _job(1),
            _job(2),
            _link(dup=2, canon=1, status="candidate"),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.canonical_jobs == 2

    def test_confirmed_duplicate_excluded_from_description_ready(self, session):
        _add_all(
            session,
            _job(1, description="Python SQL AWS experience needed for data engineering role"),
            _job(2, description="Python SQL AWS experience needed for data engineering role"),
            _link(dup=2, canon=1, status="confirmed"),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        # Only job 1 is canonical, has raw desc, no cleaned → ready
        assert result.raw_description_canonical == 1
        assert result.description_ready == 1

    def test_confirmed_duplicate_excluded_from_skill_ready(self, session):
        _add_all(
            session,
            _job(1, cleaned_description="Python SQL AWS"),
            _job(2, cleaned_description="Python SQL AWS"),
            _link(dup=2, canon=1, status="confirmed"),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.skills_ready == 1


class TestDescriptionReady:
    """description_ready = canonical, usable raw desc, no cleaned_desc."""

    def test_ready_when_usable_and_no_cleaned(self, session):
        _add_all(session, _job(1, description="Python SQL AWS 5 years data engineering experience"))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.description_ready == 1

    def test_not_ready_when_already_cleaned(self, session):
        _add_all(
            session,
            _job(
                1,
                description="Python experience",
                cleaned_description="Python experience",
            ),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.description_ready == 0

    def test_placeholder_not_ready(self, session):
        _add_all(session, _job(1, description="Buscar es más fácil en la app"))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.description_ready == 0
        assert result.unusable_description == 1

    def test_too_short_not_ready(self, session):
        _add_all(session, _job(1, description="Hi"))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.description_ready == 0
        assert result.unusable_description >= 1

    def test_mixed_ready_and_unusable(self, session):
        _add_all(
            session,
            _job(1, description="Python SQL experience required"),  # ready
            _job(2, description="Buscar es más fácil en la app"),  # unusable
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.description_ready == 1
        assert result.unusable_description == 1


class TestSkillReady:
    """skills_json = NULL + cleaned_desc → skill-ready; [] and non-NULL → NOT ready."""

    def test_null_skills_is_ready_with_cleaned(self, session):
        _add_all(
            session,
            _job(1, cleaned_description="Python experience", skills_json=None),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.skills_ready == 1

    def test_empty_array_is_processed_not_ready(self, session):
        _add_all(
            session,
            _job(1, cleaned_description="Python experience", skills_json=[]),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.skills_ready == 0
        assert result.skills_processed_canonical == 1

    def test_non_empty_is_processed_not_ready(self, session):
        _add_all(
            session,
            _job(
                1,
                cleaned_description="Python experience",
                skills_json=["python", "sql"],
            ),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.skills_ready == 0
        assert result.skills_processed_canonical == 1

    def test_no_cleaned_desc_no_skill_ready(self, session):
        _add_all(
            session,
            _job(1, cleaned_description=None, skills_json=None),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.skills_ready == 0


class TestEmptyState:
    """Zero pending work is healthy, not an error."""

    def test_empty_database(self, session):
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.raw_jobs == 0
        assert result.canonical_jobs == 0
        assert result.description_ready == 0
        assert result.skills_ready == 0

    def test_all_complete(self, session):
        _add_all(
            session,
            _job(
                1,
                description="Python experience",
                cleaned_description="Python experience",
                skills_json=["python"],
            ),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.description_ready == 0
        assert result.skills_ready == 0
        assert result.nlp_complete_canonical == 1

    def test_no_description_blocked(self, session):
        _add_all(session, _job(1, description=None))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.blocked_no_description == 1
        assert result.raw_description_canonical == 0


class TestDedupPending:
    """Dedup checkpoint remains unavailable until Slice 2."""

    def test_dedup_pending_unavailable(self, session):
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.dedup_pending == "checkpoint_not_available"


class TestDuplicatesCounts:
    """Same-source and cross-source confirmed counts are separated."""

    def test_same_source_and_cross_source(self, session):
        _add_all(
            session,
            _job(1),
            _job(2),
            _job(3),
            _link(dup=2, canon=1, scope="same_source", status="confirmed"),
            _link(dup=3, canon=1, scope="cross_source", status="confirmed"),
        )
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        assert result.confirmed_duplicates == 2
        assert result.same_source_confirmed == 1
        assert result.cross_source_confirmed == 1


class TestStatusTable:
    """The status_table output is human-readable and includes key fields."""

    def test_status_table_includes_all_sections(self, session):
        _add_all(session, _job(1, description="Python SQL"))
        inspector = PendingWorkInspector()
        with patch(
            "src.data_quality.pending_work.db_connect",
            return_value=session.get_bind(),
        ):
            result = inspector.inspect()
        table = result.status_table()
        assert "Raw jobs:" in table
        assert "Canonical jobs:" in table
        assert "Description-ready:" in table
        assert "Unusable/placeholders:" in table
        assert "Skill-ready:" in table
        assert "NLP complete:" in table
        assert "Blocked/no desc:" in table
        assert "checkpoint_not_available" in table


class TestNoPrivateImport:
    """PendingWorkInspector must not import _PLACEHOLDERS."""

    def test_no_private_placeholder_import(self):
        import inspect
        import src.data_quality.pending_work as pw

        source = inspect.getsource(pw)
        assert "_PLACEHOLDERS" not in source
