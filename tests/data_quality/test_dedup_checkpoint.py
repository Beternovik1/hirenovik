"""Tests for dedup checkpoint read/write API."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import JSON, StaticPool, create_engine

from src.database.models import Base, Job, JobDuplicateLink, JobDedupCheck
from src.data_quality.dedup_checkpoint import (
    record_checkpoint,
    has_checkpoint,
    missing_checkpoint_ids,
    count_pending,
)
from src.data_quality.same_source_initializer import (
    SameSourceCheckpointInitializer,
    SameSourceInitMetrics,
)
from src.data_quality.same_source_planner import plan_pending_same_source_groups

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


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
    from sqlalchemy.orm import Session
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _job(session, id_, **kw):
    j = Job(
        id=id_,
        site=kw.pop("site", "computrabajo"),
        job_url=kw.pop("job_url", f"https://mx.computrabajo.com/job/{id_}"),
        title=kw.pop("title", "Data Engineer"),
        company=kw.pop("company", "Acme Corp"),
        raw_location=kw.pop("raw_location", "CDMX"),
        description=kw.pop("description", None),
        salary_min=kw.pop("salary_min", None),
        salary_max=kw.pop("salary_max", None),
        date_scraped=kw.pop("date_scraped", NOW),
        **kw,
    )
    session.add(j)
    # Fix JSONB NULL on SQLite
    session.flush()
    from sqlalchemy import text
    for col in ("skills_json", "cleaned_description"):
        val = getattr(j, col, None)
        if val is None:
            session.execute(text(f"UPDATE jobs SET {col} = NULL WHERE id = :id"), {"id": j.id})
    session.commit()
    return j


# ---------------------------------------------------------------------------
# record_checkpoint
# ---------------------------------------------------------------------------

class TestRecordCheckpoint:
    def test_creates_checkpoint(self, session):
        _job(session, 1, description="Python SQL AWS Docker")
        record_checkpoint(session, 1, scope="same_source")
        assert session.query(JobDedupCheck).count() == 1

    def test_stores_evidence_hash(self, session):
        _job(session, 1, job_url="https://mx.computrabajo.com/job/42", description="Python")
        record_checkpoint(session, 1, scope="same_source")
        ck = session.query(JobDedupCheck).one()
        assert ck.evidence_hash is not None
        assert len(ck.evidence_hash) == 64

    def test_idempotent_same_scope_version(self, session):
        _job(session, 1, description="Python SQL")
        first_checked_at = datetime(2026, 8, 9, 10, 0)
        later_checked_at = datetime(2026, 8, 9, 11, 0)
        first = record_checkpoint(
            session,
            1,
            scope="same_source",
            checked_at=first_checked_at,
        )
        changes_before = session.connection().connection.driver_connection.total_changes
        second = record_checkpoint(
            session,
            1,
            scope="same_source",
            checked_at=later_checked_at,
        )
        assert session.query(JobDedupCheck).count() == 1
        assert second.id == first.id
        assert second.checked_at == first_checked_at
        assert session.connection().connection.driver_connection.total_changes == changes_before

    def test_stale_same_version_refreshes_hash_and_checked_at(self, session):
        _job(session, 1, description="Python SQL")
        first_checked_at = datetime(2026, 8, 9, 10, 0)
        refreshed_at = datetime(2026, 8, 9, 11, 0)
        first = record_checkpoint(
            session,
            1,
            scope="same_source",
            checked_at=first_checked_at,
        )
        first_id = first.id
        first_hash = first.evidence_hash

        session.query(Job).filter(Job.id == 1).update({"salary_min": 30_000})
        session.commit()
        refreshed = record_checkpoint(
            session,
            1,
            scope="same_source",
            checked_at=refreshed_at,
        )

        assert session.query(JobDedupCheck).count() == 1
        assert refreshed.id == first_id
        assert refreshed.evidence_hash != first_hash
        assert refreshed.checked_at == refreshed_at
        assert has_checkpoint(session, 1, scope="same_source") is True

    def test_different_scopes_independent(self, session):
        _job(session, 1, description="Python SQL")
        record_checkpoint(session, 1, scope="same_source")
        record_checkpoint(session, 1, scope="cross_source")
        assert session.query(JobDedupCheck).count() == 2


# ---------------------------------------------------------------------------
# has_checkpoint
# ---------------------------------------------------------------------------

class TestHasCheckpoint:
    def test_true_when_current(self, session):
        _job(session, 1, description="Python SQL")
        record_checkpoint(session, 1, scope="same_source")
        assert has_checkpoint(session, 1, scope="same_source") is True

    def test_false_when_missing(self, session):
        _job(session, 1, description="Python SQL")
        assert has_checkpoint(session, 1, scope="same_source") is False

    def test_false_when_evidence_changed(self, session):
        _job(session, 1, description="Python")
        record_checkpoint(session, 1, scope="cross_source")
        # Change description (Phase 2 enrichment)
        session.query(Job).filter(Job.id == 1).update({"description": "Java Spring"})
        session.commit()
        assert has_checkpoint(session, 1, scope="cross_source") is False

    def test_stays_true_when_nlp_field_changes(self, session):
        """skills_json changes should NOT invalidate checkpoint."""
        _job(session, 1, description="Python SQL")
        record_checkpoint(session, 1, scope="cross_source")
        # Simulate SkillEnricher writing skills_json
        session.query(Job).filter(Job.id == 1).update({"skills_json": ["python", "sql"]})
        session.commit()
        assert has_checkpoint(session, 1, scope="cross_source") is True

    def test_same_source_stays_true_when_nlp_fields_change(self, session):
        _job(session, 1, description="Python SQL AWS experience required")
        record_checkpoint(session, 1, scope="same_source")
        session.query(Job).filter(Job.id == 1).update(
            {
                "cleaned_description": "python sql aws experience required",
                "skills_json": ["python", "sql", "aws"],
                "keywords_json": {"topic": 1},
            }
        )
        session.commit()
        assert has_checkpoint(session, 1, scope="same_source") is True


# ---------------------------------------------------------------------------
# missing_checkpoint_ids
# ---------------------------------------------------------------------------

class TestMissingCheckpointIds:
    def test_includes_missing(self, session):
        _job(session, 1, description="Python")
        _job(session, 2, description="SQL")
        missing = missing_checkpoint_ids(session, [1, 2], scope="cross_source")
        assert set(missing) == {1, 2}

    def test_excludes_current(self, session):
        _job(session, 1, description="Python")
        _job(session, 2, description="SQL")
        record_checkpoint(session, 1, scope="cross_source")
        missing = missing_checkpoint_ids(session, [1, 2], scope="cross_source")
        assert missing == [2]

    def test_includes_stale(self, session):
        _job(session, 1, description="Python")
        record_checkpoint(session, 1, scope="cross_source")
        # Phase 2 enriches description
        session.query(Job).filter(Job.id == 1).update({"description": "Java Spring"})
        session.commit()
        missing = missing_checkpoint_ids(session, [1], scope="cross_source")
        assert missing == [1]


# ---------------------------------------------------------------------------
# count_pending
# ---------------------------------------------------------------------------

class TestCountPending:
    def test_all_pending_when_no_checkpoints(self, session):
        _job(session, 1, site="computrabajo", description="Python")
        assert count_pending(session, scope="same_source") == 1

    def test_zero_when_all_current(self, session):
        _job(session, 1, site="computrabajo", description="Python")
        record_checkpoint(session, 1, scope="same_source")
        assert count_pending(session, scope="same_source") == 0

    def test_stale_checkpoint_is_pending(self, session):
        _job(session, 1, site="computrabajo", description="Python")
        record_checkpoint(session, 1, scope="same_source")
        session.query(Job).filter(Job.id == 1).update({"salary_min": 30_000})
        session.commit()
        assert count_pending(session, scope="same_source") == 1

    def test_non_computrabajo_not_same_source_eligible(self, session):
        _job(session, 1, site="indeed", description="Python SQL")
        assert count_pending(session, scope="same_source") == 0

    def test_no_description_not_cross_source_eligible(self, session):
        _job(session, 1, site="indeed", description=None)
        assert count_pending(session, scope="cross_source") == 0

    def test_confirmed_duplicate_participates_in_same_source(self, session):
        _job(session, 1, site="computrabajo", description="Python")
        _job(session, 2, site="computrabajo", description="Python")
        session.add(JobDuplicateLink(
            duplicate_job_id=2, canonical_job_id=1,
            scope="same_source", method="url_match",
            confidence=1.0, status="confirmed",
            dedup_version="1.0.0", created_at=NOW,
        ))
        session.commit()
        assert count_pending(session, scope="same_source") == 2


# ---------------------------------------------------------------------------
# Checked-independent semantics
# ---------------------------------------------------------------------------

class TestCheckedIndependent:
    def test_checkpoint_without_link_means_independent(self, session):
        _job(session, 1, description="Python SQL")
        record_checkpoint(session, 1, scope="cross_source")
        # Checkpoint exists, no link → evaluated and independent
        assert session.query(JobDedupCheck).count() == 1
        assert session.query(JobDuplicateLink).count() == 0
        assert has_checkpoint(session, 1, scope="cross_source") is True

    def test_link_without_checkpoint_means_confirmed(self, session):
        _job(session, 1, site="computrabajo", description="Python")
        _job(session, 2, site="computrabajo", description="Python")
        session.add(JobDuplicateLink(
            duplicate_job_id=2, canonical_job_id=1,
            scope="same_source", method="url_match",
            confidence=1.0, status="confirmed",
            dedup_version="1.0.0", created_at=NOW,
        ))
        session.commit()
        # Link exists, no checkpoint → duplicate confirmed
        assert session.query(JobDuplicateLink).count() == 1
        # Same-source freshness includes confirmed duplicate observations.
        assert count_pending(session, scope="same_source") == 2


# ---------------------------------------------------------------------------
# Group-aware same-source scenario
# ---------------------------------------------------------------------------

class TestSameSourceGroupAwareness:
    """Per-job checkpoint + orchestrator group awareness pattern."""

    def test_phase2_other_member_changes_makes_it_pending(self, session):
        """Two jobs sharing same canonical URL. B gets Phase 2. B becomes pending."""
        # Use different raw URLs that would canonicalize identically
        url_a = "https://mx.computrabajo.com/job/group-a"
        url_b = "https://mx.computrabajo.com/job/group-b"
        _job(session, 1, job_url=url_a, salary_min=30000, description="Senior")
        _job(session, 2, job_url=url_b, salary_min=None, description=None)

        # Both evaluated
        record_checkpoint(session, 1, scope="same_source")
        record_checkpoint(session, 2, scope="same_source")

        # Phase 2 adds salary to job 2
        session.query(Job).filter(Job.id == 2).update({"salary_min": 35000, "salary_max": 50000})
        session.commit()

        # Job 2 should now be stale/pending
        assert has_checkpoint(session, 2, scope="same_source") is False
        # Job 1's own evidence didn't change — its checkpoint stays current
        assert has_checkpoint(session, 1, scope="same_source") is True
        # The orchestrator sees job 2 pending and re-evaluates the entire
        # URL group (both 1 and 2), which is the correct group-level behaviour.

    def test_planner_expands_one_pending_member_to_only_its_full_group(
        self, session
    ):
        group_url = "https://mx.computrabajo.com/job/group"
        _job(session, 1, job_url=f"{group_url}#lc=A", salary_min=30_000)
        _job(session, 2, job_url=f"{group_url}#lc=B")
        _job(session, 3, job_url="https://mx.computrabajo.com/job/other")
        session.add(
            JobDuplicateLink(
                duplicate_job_id=2,
                canonical_job_id=1,
                scope="same_source",
                method="url_match",
                confidence=1.0,
                status="confirmed",
                dedup_version="1.1.0",
                created_at=NOW,
            )
        )
        session.commit()
        for job_id in (1, 2, 3):
            record_checkpoint(session, job_id, scope="same_source")

        session.query(Job).filter(Job.id == 2).update({"salary_min": 35_000})
        session.commit()

        plan = plan_pending_same_source_groups(session)

        assert len(plan) == 1
        assert plan[0].canonical_url == group_url
        assert plan[0].pending_member_ids == (2,)
        assert plan[0].member_ids == (1, 2)

    def test_planner_returns_no_groups_when_every_member_is_current(self, session):
        _job(session, 1)
        record_checkpoint(session, 1, scope="same_source")
        assert plan_pending_same_source_groups(session) == []

    def test_multiple_pending_members_schedule_each_pending_group_once(self, session):
        first_url = "https://mx.computrabajo.com/job/first"
        second_url = "https://mx.computrabajo.com/job/second"
        for job_id, url in (
            (1, f"{first_url}#lc=A"),
            (2, f"{first_url}#lc=B"),
            (3, f"{second_url}#lc=A"),
            (4, f"{second_url}#lc=B"),
        ):
            _job(session, job_id, job_url=url)
            record_checkpoint(session, job_id, scope="same_source")

        session.query(Job).filter(Job.id.in_((1, 2))).update(
            {"salary_min": 35_000}, synchronize_session=False
        )
        session.commit()

        plan = plan_pending_same_source_groups(session)

        assert len(plan) == 1
        assert plan[0].canonical_url == first_url
        assert plan[0].member_ids == (1, 2)
        assert plan[0].pending_member_ids == (1, 2)

    def test_new_member_expands_existing_current_group(self, session):
        group_url = "https://mx.computrabajo.com/job/group"
        for job_id, fragment in ((1, "A"), (2, "B")):
            _job(session, job_id, job_url=f"{group_url}#lc={fragment}")
            record_checkpoint(session, job_id, scope="same_source")
        _job(session, 3, job_url=f"{group_url}#lc=C")

        plan = plan_pending_same_source_groups(session)

        assert len(plan) == 1
        assert plan[0].member_ids == (1, 2, 3)
        assert plan[0].pending_member_ids == (3,)

    def test_confirmed_duplicate_evidence_change_schedules_full_group(self, session):
        group_url = "https://mx.computrabajo.com/job/group"
        _job(session, 1, job_url=f"{group_url}#lc=A")
        _job(session, 2, job_url=f"{group_url}#lc=B")
        session.add(
            JobDuplicateLink(
                duplicate_job_id=2,
                canonical_job_id=1,
                scope="same_source",
                method="url_match",
                confidence=1.0,
                status="confirmed",
                dedup_version="1.1.0",
                created_at=NOW,
            )
        )
        session.commit()
        for job_id in (1, 2):
            record_checkpoint(session, job_id, scope="same_source")
        session.query(Job).filter(Job.id == 2).update({"salary_min": 35_000})
        session.commit()

        plan = plan_pending_same_source_groups(session)

        assert len(plan) == 1
        assert plan[0].member_ids == (1, 2)
        assert plan[0].pending_member_ids == (2,)

    def test_initializer_pending_group_evaluation_does_not_mutate(self, session):
        group_url = "https://mx.computrabajo.com/job/group"
        _job(session, 1, job_url=f"{group_url}#lc=A", salary_min=30_000)
        _job(session, 2, job_url=f"{group_url}#lc=B")
        for job_id in (1, 2):
            record_checkpoint(session, job_id, scope="same_source")
        session.query(Job).filter(Job.id == 2).update({"salary_min": 35_000})
        session.commit()
        checkpoint_count = session.query(JobDedupCheck).count()
        link_count = session.query(JobDuplicateLink).count()

        metrics = SameSourceInitMetrics()
        SameSourceCheckpointInitializer()._evaluate(session, metrics)

        assert metrics.canonical_groups == 1
        assert metrics.checkpoints_stale == 1
        assert metrics.checkpoints_current == 1
        assert metrics.checkpoint_targets == 2
        assert session.query(JobDedupCheck).count() == checkpoint_count
        assert session.query(JobDuplicateLink).count() == link_count
