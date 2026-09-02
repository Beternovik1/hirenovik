"""Dedup checkpoint — record that a job was evaluated for a given scope."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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


def current_evidence_hash(session: Session, job_id: int, scope: str) -> str:
    """Return the current scope-specific evidence hash for a persisted job.

    Args:
        session: SQLAlchemy session used to load the job.
        job_id: Persisted job identifier.
        scope: ``"same_source"`` or ``"cross_source"``.

    Returns:
        The deterministic hash of the job's current dedup evidence.

    Raises:
        ValueError: If the job does not exist or the scope is unknown.
    """
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


def record_checkpoint(
    session: Session,
    job_id: int,
    scope: str,
    *,
    dedup_version: Optional[str] = None,
    checked_at: Optional[datetime] = None,
) -> JobDedupCheck:
    """Record that *job_id* was evaluated for *scope*.

    If the key already exists with stale evidence, update ``evidence_hash``
    and ``checked_at`` under the same version. If the hash is unchanged,
    perform no update and preserve the original timestamp.

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
    ehash = current_evidence_hash(session, job_id, scope)

    insert = (
        sqlite_insert
        if session.get_bind().dialect.name == "sqlite"
        else pg_insert
    )
    stmt = insert(JobDedupCheck).values(
        job_id=job_id,
        scope=scope,
        dedup_version=ver,
        checked_at=ts,
        evidence_hash=ehash,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["job_id", "scope", "dedup_version"],
        set_={
            "checked_at": stmt.excluded.checked_at,
            "evidence_hash": stmt.excluded.evidence_hash,
        },
        where=JobDedupCheck.evidence_hash.is_distinct_from(
            stmt.excluded.evidence_hash
        ),
    )
    session.execute(stmt)

    return (
        session.query(JobDedupCheck)
        .populate_existing()
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
    checkpoint = (
        session.query(JobDedupCheck)
        .filter(
            JobDedupCheck.job_id == job_id,
            JobDedupCheck.scope == scope,
            JobDedupCheck.dedup_version == ver,
        )
        .one_or_none()
    )
    return (
        checkpoint is not None
        and checkpoint.evidence_hash
        == current_evidence_hash(session, job_id, scope)
    )


def missing_checkpoint_ids(
    session: Session,
    candidate_ids: Sequence[int],
    scope: str,
    *,
    dedup_version: Optional[str] = None,
) -> list[int]:
    """Return missing or stale candidate IDs in their input order.

    A checkpoint is current only when it exists for the requested scope and
    version and its stored hash equals freshly computed evidence for that job.
    """
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
            current = current_evidence_hash(session, jid, scope)
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
    """Count jobs pending dedup evaluation for *scope*.

    A job is pending if it lacks a current (non-stale) checkpoint for
    the given scope and version.

    For **same_source**: ALL Computrabajo rows participate, including
    confirmed duplicates — a duplicate may gain evidence during Phase 2
    and become a better canonical.

    For **cross_source**: confirmed duplicates are excluded (canonical
    analytics semantics).

    Args:
        scope: ``"same_source"`` or ``"cross_source"``.
        dedup_version: Version (defaults to scope current).
        eligible_only: Restrict to matcher-eligible jobs.
    """
    from src.data_quality import confirmed_duplicate_filter

    # Same-source freshness includes ALL Computrabajo rows;
    # cross-source uses canonical-analytics dedup filtering.
    if scope == "same_source":
        query = session.query(Job).filter(Job.site == "computrabajo")
    else:
        query = session.query(Job).filter(confirmed_duplicate_filter(Job))
        if eligible_only and scope == "cross_source":
            query = query.filter(
                Job.description.isnot(None),
                Job.description != "",
            )

    candidate_ids = [job_id for (job_id,) in query.with_entities(Job.id).all()]
    return len(
        missing_checkpoint_ids(
            session,
            candidate_ids,
            scope,
            dedup_version=dedup_version,
        )
    )
