"""Database-facing retrieval for the Industrial Bajío alert digest.

Keeps all SQLAlchemy/DB I/O here so :mod:`notifications.digest` stays pure and
unit-testable without a database. This module fetches NEW Industrial Bajío jobs
with a non-empty description and delegates ranking and payload composition to
:func:`notifications.digest.select_digest`.

Freshness is applied in TWO layers:

* **SQL coarse lower bound** -- ``date_scraped >= now - freshness_days`` narrows
  the candidate set so historical NEW described rows do not all load as they
  accumulate. The ``Job.date_scraped`` column is ``DateTime(timezone=True)``
  (Postgres ``timestamptz``), so an aware UTC bind param compares correctly
  regardless of driver. NULL ``date_scraped`` rows are excluded by this
  predicate (``NULL >= x`` is falsy in SQL), which is consistent with the pure
  selector's "missing date -> stale -> excluded" semantics, so no eligible job
  is lost.
* **Python exact cutoff** -- :func:`select_digest` re-applies the precise
  freshness window in Python where both sides are normalized to aware UTC via
  :func:`shared.utils.aware_utc`, handling naive driver values safely. The SQL
  bound is a coarse optimization; the Python filter is the authority.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database.models import Job
from notifications.digest import (
    DIGEST_DEFAULT_FALLBACK_LIMIT,
    DIGEST_DEFAULT_FRESHNESS_DAYS,
    DIGEST_DEFAULT_LIMIT,
    DIGEST_NICHE,
    DIGEST_PROFILE_NAME,
    DigestPayload,
    select_digest,
)
from notifications.profiles import AlertProfile, get_alert_profile
from shared.utils import aware_utc

logger = logging.getLogger(__name__)


def fetch_digest_candidates(
    session: Session,
    *,
    niche: str = DIGEST_NICHE,
    now: datetime | None = None,
    freshness_days: int = DIGEST_DEFAULT_FRESHNESS_DAYS,
    exclude_job_ids: set[int] | None = None,
) -> list[Job]:
    """Query NEW Industrial Bajío jobs with a non-empty description.

    Applies the cheap, indexable column predicates (niche, status, description
    non-null and non-empty) in SQL to narrow the candidate set. When ``now`` is
    provided, a coarse ``date_scraped >= now - freshness_days`` lower bound is
    added so historical NEW rows do not load as they accumulate; the exact
    freshness cutoff and CV-fit gate remain applied by :func:`select_digest` in
    Python. Passing ``now=None`` skips the date lower bound (legacy behavior) for
    callers that prefer to load the full candidate set.

    Profile-scoped send history is honored via ``exclude_job_ids``: when a
    non-empty set is provided (typically from
    :func:`notifications.notification_log.get_sent_job_ids`), a
    ``Job.id NOT IN (...)`` predicate drops jobs already recorded as sent for
    this profile, so a job is selected at most once per profile across digest
    runs. An empty set or ``None`` skips the predicate entirely -- this avoids
    emitting ``NOT IN (NULL)``-shaped queries on the empty-history path and
    keeps the common fresh-install case cheap.

    Args:
        session: SQLAlchemy ORM session.
        niche: Industry niche to scope the query to.
        now: Reference datetime (aware or naive) for the coarse freshness lower
            bound. Normalized to aware UTC before binding.
        freshness_days: Coarse freshness window length in days.
        exclude_job_ids: Job ids to drop from the candidate set (already sent
            for the digest profile). ``None`` or empty skips the exclusion.

    Returns:
        List of ``Job`` rows matching the predicates, in unspecified database
        order. :func:`select_digest` re-ranks them.
    """
    filters = [
        Job.industry_niche == niche,
        Job.status == "NEW",
        Job.description.isnot(None),
        Job.description != "",
    ]
    if now is not None:
        lower_bound = aware_utc(now) - timedelta(days=freshness_days)
        filters.append(Job.date_scraped >= lower_bound)
    if exclude_job_ids:
        filters.append(Job.id.notin_(exclude_job_ids))
    return session.query(Job).filter(*filters).all()


def build_digest(
    session: Session,
    now: datetime,
    *,
    profile: AlertProfile | None = None,
    niche: str = DIGEST_NICHE,
    freshness_days: int = DIGEST_DEFAULT_FRESHNESS_DAYS,
    limit: int = DIGEST_DEFAULT_LIMIT,
    fallback_limit: int = DIGEST_DEFAULT_FALLBACK_LIMIT,
    exclude_job_ids: set[int] | None = None,
) -> DigestPayload:
    """Fetch digest candidates from the DB and build the ranked digest payload.

    End-to-end DB-facing entry point: queries NEW Industrial Bajío jobs with a
    non-empty description and a coarse freshness lower bound, then delegates the
    exact eligibility (freshness + CV-fit), ranking, and payload composition to
    :func:`select_digest`. Both the primary cap (``limit``) and the secondary
    fallback cap (``fallback_limit``) are forwarded so the DB path stays
    configurable alongside the pure selector.

    Profile-scoped sent history is passed through to
    :func:`fetch_digest_candidates` via ``exclude_job_ids``: jobs already
    recorded for the digest profile are dropped in SQL before the selector ever
    sees them, so a job is sent at most once per profile. Callers that supply
    the set are responsible for using the same SQLAlchemy session used to build
    the digest, so the read and the candidate query share a single connection.

    Args:
        session: SQLAlchemy ORM session.
        now: Reference datetime (aware or naive) for the freshness window.
            Required and passed to :func:`fetch_digest_candidates` for the coarse
            SQL lower bound, and to :func:`select_digest` for the exact cutoff.
        profile: Alert profile to score against. ``None`` resolves the profile
            registered under :data:`DIGEST_PROFILE_NAME`.
        niche: Industry niche to scope the digest to.
        freshness_days: Hard freshness cutoff in days.
        limit: Maximum PRIMARY jobs to return.
        fallback_limit: Maximum SECONDARY (fallback) jobs to return. Set to 0 to
            disable the secondary section.
        exclude_job_ids: Job ids to drop from the candidate set (already sent for
            the digest profile). ``None`` or empty skips the SQL exclusion and is
            the safe default for callers that do not yet wire the notification log.

    Returns:
        A :class:`DigestPayload` with the ranked selected primary jobs and the
        lower-confidence fallback jobs.

    Raises:
        ValueError: If ``profile`` is ``None`` and no profile is registered under
            :data:`DIGEST_PROFILE_NAME` (propagated from :func:`select_digest`).
    """
    resolved_profile = profile
    if resolved_profile is None:
        resolved_profile = get_alert_profile(DIGEST_PROFILE_NAME)

    rows = fetch_digest_candidates(
        session,
        niche=niche,
        now=now,
        freshness_days=freshness_days,
        exclude_job_ids=exclude_job_ids,
    )
    logger.info(
        "Fetched %d NEW '%s' digest candidates from DB (before exact freshness/fit filter; "
        "excluded %d sent job id(s)).",
        len(rows),
        niche,
        len(exclude_job_ids) if exclude_job_ids else 0,
    )
    return select_digest(
        rows,
        now,
        profile=resolved_profile,
        niche=niche,
        freshness_days=freshness_days,
        limit=limit,
        fallback_limit=fallback_limit,
    )
