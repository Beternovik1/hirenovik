"""Integration tests: dedup-aware NLP eligibility (Slice 4E)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import JSON, StaticPool, create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, Job, JobDuplicateLink
from src.nlp.description_preparer import DescriptionPreparer
from src.nlp.skill_enricher import SkillEnricher
from src.nlp.skill_extractor import reset_extractor
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


def _job(id_, desc, cleaned=None, **kw) -> Job:
    return Job(
        id=id_,
        site="indeed",
        job_url=f"https://t/{id_}",
        title=kw.pop("title", "T"),
        company="C",
        raw_location="L",
        description=desc,
        cleaned_description=cleaned,
        **kw,
    )


def _dup_link(dup_id, canon_id, scope, status) -> None:
    """Helper to be called inside a session."""
    from sqlalchemy import text
    return text(
        "INSERT INTO job_duplicate_links "
        "(duplicate_job_id, canonical_job_id, scope, method, confidence, "
        "status, dedup_version, created_at) "
        "VALUES (:dup, :canon, :scope, 'test', 1.0, :status, '1.0', :ts)"
    )


NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# DescriptionPreparer
# ---------------------------------------------------------------------------


class TestDescriptionPreparerDedup:
    def test_eligible_canonical_processed(self, session) -> None:
        job = _job(1, "Python developer " * 5)
        session.add(job)
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(dry_run=False)

        assert m.prepared == 1

    def test_confirmed_same_source_skipped(self, session) -> None:
        canon = _job(1, "Python developer with Django PostgreSQL experience " * 3)
        dup = _job(2, "Python developer with Django PostgreSQL experience " * 3)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "same_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "same_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(dry_run=False)

        assert m.prepared == 1  # only canonical processed

    def test_confirmed_cross_source_skipped(self, session) -> None:
        canon = _job(1, "Python developer with Django PostgreSQL experience " * 3)
        dup = _job(2, "Python developer with Django PostgreSQL experience " * 3)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "cross_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "cross_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(dry_run=False)

        assert m.prepared == 1

    def test_canonical_side_remains_eligible(self, session) -> None:
        canon = _job(1, "Python developer with Django PostgreSQL experience " * 3)
        dup = _job(2, "Python developer with Django PostgreSQL experience " * 3)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "same_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "same_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(dry_run=False)

        assert m.prepared == 1
        session.refresh(canon)
        assert canon.cleaned_description is not None

    def test_candidate_not_skipped(self, session) -> None:
        canon = _job(1, "Python developer with Django PostgreSQL experience " * 3)
        cand = _job(2, "Python developer with Django PostgreSQL experience " * 3)
        session.add_all([canon, cand])
        session.commit()
        session.execute(
            _dup_link(2, 1, "cross_source", "candidate"),
            {"dup": 2, "canon": 1, "scope": "cross_source", "status": "candidate", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(dry_run=False)

        assert m.prepared == 2  # both processed

    def test_force_does_not_bypass_dedup(self, session) -> None:
        canon = _job(1, "Python developer with Django PostgreSQL experience " * 3)
        dup = _job(2, "Python developer with Django PostgreSQL experience " * 3)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "same_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "same_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(force=True, dry_run=False)

        assert m.prepared == 1  # --force does not bypass dedup exclusion


# ---------------------------------------------------------------------------
# SkillEnricher
# ---------------------------------------------------------------------------


class TestSkillEnricherDedup:
    def test_eligible_canonical_processed(self, session) -> None:
        job = _job(1, "raw", cleaned="Python SQL Docker " * 5)
        session.add(job)
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            ext = SkillEnricher(batch_size=100)
            m = ext.run(dry_run=False)

        assert m.processed == 1

    def test_confirmed_same_source_skipped(self, session) -> None:
        canon = _job(1, "raw", cleaned="Python SQL " * 5)
        dup = _job(2, "raw", cleaned="Python SQL " * 5)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "same_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "same_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            m = SkillEnricher(batch_size=100).run(dry_run=False)

        assert m.processed == 1

    def test_confirmed_cross_source_skipped(self, session) -> None:
        canon = _job(1, "raw", cleaned="Python SQL " * 5)
        dup = _job(2, "raw", cleaned="Python SQL " * 5)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "cross_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "cross_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            m = SkillEnricher(batch_size=100).run(dry_run=False)

        assert m.processed == 1

    def test_candidate_not_skipped(self, session) -> None:
        canon = _job(1, "raw", cleaned="Python SQL " * 5)
        cand = _job(2, "raw", cleaned="Python SQL " * 5)
        session.add_all([canon, cand])
        session.commit()
        session.execute(
            _dup_link(2, 1, "cross_source", "candidate"),
            {"dup": 2, "canon": 1, "scope": "cross_source", "status": "candidate", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            m = SkillEnricher(batch_size=100).run(dry_run=False)

        assert m.processed == 2

    def test_force_does_not_bypass_dedup(self, session) -> None:
        canon = _job(1, "raw", cleaned="Python SQL " * 5)
        dup = _job(2, "raw", cleaned="Python SQL " * 5)
        session.add_all([canon, dup])
        session.commit()
        session.execute(
            _dup_link(2, 1, "same_source", "confirmed"),
            {"dup": 2, "canon": 1, "scope": "same_source", "status": "confirmed", "ts": NOW},
        )
        session.commit()

        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            m = SkillEnricher(batch_size=100).run(force=True, dry_run=False)

        assert m.processed == 1


# ---------------------------------------------------------------------------
# Integration: combined scenario
# ---------------------------------------------------------------------------


class TestCombinedScenario:
    def test_all_statuses(self, session) -> None:
        """A=canonical, B=same-source dup, C=cross-source dup, D=candidate, E=unrelated"""
        jobs = [
            _job(1, "A raw description for a Python developer role " * 3),
            _job(2, "B raw description for a Python developer role " * 3),
            _job(3, "C raw description for a Python developer role " * 3),
            _job(4, "D raw description for a Python developer role " * 3),
            _job(5, "E raw description for a Python developer role " * 3),
        ]
        session.add_all(jobs)
        session.commit()

        for dup_id, canon_id, scope, status in [
            (2, 1, "same_source", "confirmed"),
            (3, 1, "cross_source", "confirmed"),
            (4, 1, "cross_source", "candidate"),
        ]:
            session.execute(
                _dup_link(dup_id, canon_id, scope, status),
                {"dup": dup_id, "canon": canon_id, "scope": scope, "status": status, "ts": NOW},
            )
        session.commit()

        # DescriptionPreparer
        with patch("src.nlp.description_preparer.db_connect", return_value=session.bind):
            m = DescriptionPreparer(batch_size=100).run(dry_run=False)
        assert m.prepared == 3  # A(1), D(4), E(5) — B and C skipped

        # SkillEnricher
        with patch("src.nlp.skill_enricher.db_connect", return_value=session.bind):
            m = SkillEnricher(batch_size=100).run(dry_run=False)
        # A(1) = processed, B/C excluded at query level, D(4) and E(5) processed
        assert m.processed == 3  # A, D, E
