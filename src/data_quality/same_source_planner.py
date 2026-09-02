"""Read-only planning for stale-aware Computrabajo deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from src.data_quality.dedup_checkpoint import missing_checkpoint_ids
from src.data_quality.same_source_url import canonicalize_computrabajo_url
from src.database.models import Job


@dataclass(frozen=True)
class PendingSameSourceGroup:
    """One full URL group selected because at least one member is pending.

    Attributes:
        canonical_url: Fragment-free URL used as the group identity.
        member_ids: Every Computrabajo member in the group.
        pending_member_ids: Members whose checkpoint is missing or stale.
    """

    canonical_url: str
    member_ids: tuple[int, ...]
    pending_member_ids: tuple[int, ...]


def plan_pending_same_source_groups(
    session: Session,
    *,
    dedup_version: Optional[str] = None,
) -> list[PendingSameSourceGroup]:
    """Map pending Computrabajo members to their complete canonical-URL groups.

    A member is pending when its current scope/version checkpoint is missing or
    its stored evidence hash differs from freshly computed evidence. Each result
    includes every Computrabajo row with the same normalized URL, including
    confirmed duplicates. Results are ordered by canonical URL; member and
    pending-member IDs are ordered numerically. The function performs no writes.

    Args:
        session: SQLAlchemy session used only for SELECT queries.
        dedup_version: Same-source version, defaulting to the current version.

    Returns:
        Deterministically ordered pending groups with full and pending membership.
    """
    rows = (
        session.query(Job.id, Job.job_url)
        .filter(Job.site == "computrabajo")
        .order_by(Job.id)
        .all()
    )
    candidate_ids = [job_id for job_id, _ in rows]
    pending_ids = set(
        missing_checkpoint_ids(
            session,
            candidate_ids,
            "same_source",
            dedup_version=dedup_version,
        )
    )

    grouped: dict[str, list[int]] = {}
    for job_id, job_url in rows:
        canonical_url = canonicalize_computrabajo_url(job_url or "")
        grouped.setdefault(canonical_url, []).append(job_id)

    plan = []
    for canonical_url, member_ids in sorted(grouped.items()):
        pending_member_ids = tuple(
            job_id for job_id in member_ids if job_id in pending_ids
        )
        if pending_member_ids:
            plan.append(
                PendingSameSourceGroup(
                    canonical_url=canonical_url,
                    member_ids=tuple(member_ids),
                    pending_member_ids=pending_member_ids,
                )
            )
    return plan
