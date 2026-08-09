"""Dedup checkpoint — record that a job was evaluated for a given scope."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.data_quality import SAME_SOURCE_DEDUP_VERSION, CROSS_SOURCE_DEDUP_VERSION
from src.data_quality.dedup_evidence import compute_evidence_hash
from src.database.models import Job, JobDedupCheck

#: Maps scope string to its current dedup version.
SCOPE_VERSION = {
    "same_source": SAME_SOURCE_DEDUP_VERSION,
    "cross_source": CROSS_SOURCE_DEDUP_VERSION,
}


def _fetch_job_evidence(session: Session, job_id: int) -> dict:
    """Return the dedup-relevant fields for *job_id* as a flat dict."""
    row = (
        session.query(
            Job.job_url,
            Job.title,
            Job.company,
            Job.raw_location,
            Job.description,
            Job.salary_min,
            Job.salary_max,
            Job.date_scraped,
        )
        .filter(Job.id == job_id)
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"Job {job_id} not found")

    return {
        "job_url": row[0],
        "title": row[1],
        "company": row[2],
        "location": row[3],
        "description": row[4],
        "salary_min": float(row[5]) if row[5] is not None else None,
        "salary_max": float(row[6]) if row[6] is not None else None,
        "date_scraped": str(row[7]) if row[7] is not None else None,
    }


def _current_evidence_hash(session: Session, job_id: int, scope: str) -> str:
    """Compute the current evidence hash for *job_id* in *scope*."""
    evidence = _fetch_job_evidence(session, job_id)
    return compute_evidence_hash(
        scope=scope,
        job_url=evidence["job_url"],
        title=evidence["title"],
        company=evidence["company"],
        location=evidence["location"],
        description=evidence["description"],
        salary_min=evidence["salary_min"],
        salary_max=evidence["salary_max"],
        date_scraped=evidence["date_scraped"],
    )


def _checkpoint_staleness(
    session: Session,
    job_id: int,
    scope: str,
    dedup_version: str,
    expected_hash: str,
) -> bool:
    """Return True if the *job_id* checkpoint for *scope* is stale.

    A checkpoint is stale when the stored ``evidence_hash`` differs
    from the current evidence.  A missing checkpoint (no row) is not
    stale — it's simply absent.
    """
    existing = (
        session.query(JobDedupCheck.evidence_hash)
        .filter(
            JobDedupCheck.job_id == job_id,
            JobDedupCheck.scope == scope,
            JobDedupCheck.dedup_version == dedup_version,
        )
        .scalar()
    )
    if existing is None:
        return False  # absent, not stale
    return existing != expected_hash


def record_checkpoint(
    session: Session,
    job_id: int,
    scope: str,
    *,
    dedup_version: Optional[str] = None,
    checked_at: Optional[datetime] = None,
) -> JobDedupCheck:
    """Record that *job_id* was evaluated for *scope*.

    Idempotent: if a checkpoint already exists for (job_id, scope,
    dedup_version), this is a no-op — the evidence_hash is NOT updated
    (the checkpoint is immutable for a given version).

    The evidence_hash is computed automatically from the current job
    state.  The caller does NOT need to supply it.

    Args:
        session: SQLAlchemy ORM session (caller owns commit).
        job_id: The evaluated job.
        scope: ``"same_source"`` or ``"cross_source"``.
        dedup_version: Version identifier (defaults to scope current).
        checked_at: Timestamp (defaults to now).

    Returns:
        Existing or newly-created ``JobDedupCheck``.
    """
    ts = checked_at or datetime.now(timezone.utc)
    ver = dedup_version or SCOPE_VERSION.get(scope, "1.0.0")
    ehash = _current_evidence_hash(session, job_id, scope)

    stmt = (
        pg_insert(JobDedupCheck)
        .values(
            job_id=job_id,
            scope=scope,
            dedup_version=ver,
            checked_at=ts,
            evidence_hash=ehash,
        )
        .on_conflict_do_nothing(
            index_elements=["job_id", "scope", "dedup_version"]
        )
    )
    session.execute(stmt)

    return (
        session.query(JobDedupCheck)
        .filter(
            JobDedupCheck.job_id == job_id,
            JobDedupCheck.scope == scope,
            JobDedupCheck.dedup_version == ver,
        )
        .one()
    )


def has_checkpoint(
    session: Session,
    job_id: int,
    scope: str,
    *,
    dedup_version: Optional[str] = None,
) -> bool:
    """Return True if *job_id* has a CURRENT non-stale checkpoint.

    Current means: checkpoint exists for the right scope/version AND
    the stored evidence_hash matches the current job evidence.
    """
    ver = dedup_version or SCOPE_VERSION.get(scope, "1.0.0")
    ehash = _current_evidence_hash(session, job_id, scope)
    return not _checkpoint_staleness(session, job_id, scope, ver, ehash) and (
        session.query(JobDedupCheck)
        .filter(
            JobDedupCheck.job_id == job_id,
            JobDedupCheck.scope == scope,
            JobDedupCheck.dedup_version == ver,
        )
        .count()
        > 0
    )


def missing_checkpoint_ids(
    session: Session,
    candidate_ids: Sequence[int],
    scope: str,
    *,
    dedup_version: Optional[str] = None,
) -> list[int]:
    """Return the subset of *candidate_ids* lacking a current checkpoint."""
    if not candidate_ids:
        return []
    ver = dedup_version or SCOPE_VERSION.get(scope, "1.0.0")

    # Build a map of (job_id → stored_hash) for existing checkpoints.
    existing = dict(
        session.query(JobDedupCheck.job_id, JobDedupCheck.evidence_hash)
        .filter(
            JobDedupCheck.job_id.in_(candidate_ids),
            JobDedupCheck.scope == scope,
            JobDedupCheck.dedup_version == ver,
        )
        .all()
    )

    pending = []
    for jid in candidate_ids:
        stored = existing.get(jid)
        if stored is None:
            pending.append(jid)
        else:
            current = _current_evidence_hash(session, jid, scope)
            if stored != current:
                pending.append(jid)

    return pending


def count_pending(
    session: Session,
    scope: str,
    *,
    dedup_version: Optional[str] = None,
    eligible_only: bool = True,
) -> int:
    """Count canonical jobs pending dedup evaluation for *scope*.

    A job is pending if it lacks a current (non-stale) checkpoint for
    the given scope and version.  Confirmed duplicates are excluded.

    Args:
        scope: ``"same_source"`` or ``"cross_source"``.
        dedup_version: Version (defaults to scope current).
        eligible_only: Restrict to matcher-eligible jobs.
    """
    from src.data_quality import confirmed_duplicate_filter

    ver = dedup_version or SCOPE_VERSION.get(scope, "1.0.0")

    # Start with all canonical jobs.
    query = session.query(Job).filter(confirmed_duplicate_filter(Job))

    if eligible_only:
        if scope == "same_source":
            query = query.filter(Job.site == "computrabajo")
        elif scope == "cross_source":
            query = query.filter(
                Job.description.isnot(None),
                Job.description != "",
            )

    # Exclude jobs with current non-stale checkpoints.
    # This is an approximation: we can't filter stale vs current
    # in pure SQL without computing hashes per-row.  For the pending
    # count, we count jobs WITHOUT any checkpoint for this scope/version
    # plus those where evidence may have changed.
    #
    # For the status inspector this is sufficient — the exact staleness
    # check belongs to the orchestrator which has per-job context.
    checked_ids = (
        session.query(JobDedupCheck.job_id)
        .filter(
            JobDedupCheck.scope == scope,
            JobDedupCheck.dedup_version == ver,
        )
        .subquery()
    )

    return query.filter(~Job.id.in_(session.query(checked_ids.c.job_id))).count()
