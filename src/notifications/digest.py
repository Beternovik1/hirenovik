"""Deterministic digest selector for the Industrial Bajío alert profile.

Given job-like records and a reference time, this module decides WHICH jobs are
worth sending in a daily digest and composes a serializable payload for a future
renderer/sender. It does NOT send email, render HTML, persist anything, log
notifications, or touch NLP. The selector is deterministic: NLP-aware ranking is
a deliberate later slice, after the deterministic loop is validated.

Eligibility (hard filter; EVERY condition must hold):

* ``industry_niche == DIGEST_NICHE`` (``"Industrial Bajío"``).
* ``status == "NEW"`` (enriched but not yet notified).
* ``description`` present and non-empty (whitespace-only is rejected).
* ``date_scraped`` within ``freshness_days`` of ``now`` (default 5 days, reusing
  ``ALERT_FRESHNESS_DAYS`` so the digest and the enrichment queue share one
  freshness definition).
* passes :func:`notifications.scoring.score_job` for the subscriber profile.
  ``score_job`` encodes the full fit contract -- strict Guanajuato geography,
  hard-reject keywords (internships / unpaid), and a relevant role signal -- so a
  ``None`` verdict is the explicit rejection of unsuitable jobs. Because
  ``score_job`` reuses the matcher's geography and reject union, ``score_job`` is
  a superset of :func:`notifications.matcher.match_job`; calling both would be
  redundant, so ``score_job`` is the single fit authority here.

Ranking (applied AFTER eligibility; freshness is a filter, not a sort tier):

1. ``score`` descending (CV-informed score from :func:`score_job`).
2. ``date_scraped`` descending (newer first), with the effective ranking
   timestamp capped at ``now`` so a bad future ``date_scraped`` (clock skew /
   corrupt source data) cannot dominate legitimate jobs indefinitely. A future
   date is still ELIGIBLE (it is recent) but ranks as if scraped exactly at
   ``now`` -- the most recent legitimate instant. See
   :func:`_effective_rank_timestamp`.
3. ``id`` ascending (deterministic final tie-breaker so the same candidate set
   always produces the same digest across runs).

The result is capped at ``limit`` (default 10). This is distinct from
:func:`scrapers.pipeline._rank_alert_jobs`, which treats freshness as a SORT
BUCKET (stale jobs are deprioritized but still enriched) and ranks the whole
pending queue; the digest instead EXCLUDES stale jobs and ranks only eligible
ones, so its sort key has no freshness prefix.

Pure: no network, no DB, no email, no NLP. ``now`` is a required explicit
parameter so tests are deterministic; production passes
``datetime.now(timezone.utc)``.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from notifications.profiles import AlertProfile, get_alert_profile
from notifications.scoring import (
    DIGEST_KEY_LOCATION_TIER,
    DIGEST_KEY_MATCH_REASONS,
    DIGEST_KEY_MATCHED_ROLE_GROUP,
    DIGEST_KEY_SCORE,
    score_job,
)
from shared.config import (
    ALERT_DIGEST_LIMIT,
    ALERT_DIGEST_PROFILE,
    ALERT_ENRICHMENT_NICHE,
    ALERT_FRESHNESS_DAYS,
)
from shared.utils import aware_utc

logger = logging.getLogger(__name__)

# Single source of truth lives in shared.config; these named constants just give
# the digest module stable defaults and a readable call surface. Tests pass
# explicit values rather than relying on these env-derived defaults.
DIGEST_NICHE: str = ALERT_ENRICHMENT_NICHE
DIGEST_DEFAULT_FRESHNESS_DAYS: int = ALERT_FRESHNESS_DAYS
DIGEST_DEFAULT_LIMIT: int = ALERT_DIGEST_LIMIT
DIGEST_PROFILE_NAME: str = ALERT_DIGEST_PROFILE

# Status that means "enriched, awaiting digest". Matches the enrichment bucket's
# post-enrichment transition (PENDING_ENRICHMENT -> NEW).
DIGEST_JOB_STATUS_NEW: str = "NEW"


@dataclass(frozen=True)
class DigestJob:
    """A single serializable digest row, ready for a future renderer/sender.

    Numeric salary values are coerced to ``float`` (Decimal -> float) so the
    payload is JSON-serializable; display precision loss is acceptable for a
    digest. ``date_scraped`` is rendered as an ISO 8601 string for the same
    reason. All fields are plain primitives or tuples, so
    :func:`dataclasses.asdict` yields a directly JSON-dumpable dict.

    Attributes:
        id: Stable job identifier (deterministic tie-breaker).
        title: Job title.
        company: Hiring company.
        location: Raw location string (the matcher's ``raw_location``).
        site: Source board (``"computrabajo"`` / ``"occ"``).
        job_url: Canonical posting URL.
        score: CV-informed additive score from :func:`score_job`.
        match_reasons: Human-readable explanation lines from the scorer.
        date_scraped: ISO 8601 UTC timestamp the job was scraped.
        salary_min: Minimum salary as float, or ``None`` when unknown.
        salary_max: Maximum salary as float, or ``None`` when unknown.
        currency: Salary currency code (e.g. ``"MXN"``), or ``""``.
        description: Full enriched job description.
        matched_city: Accent-folded city token the matcher anchored on.
        matched_role_group: Winning role-group label from the scorer.
        location_tier: Winning location-tier label from the scorer.
    """

    id: int
    title: str
    company: str
    location: str
    site: str
    job_url: str
    score: int
    match_reasons: tuple[str, ...]
    date_scraped: str
    salary_min: float | None
    salary_max: float | None
    currency: str
    description: str
    matched_city: str
    matched_role_group: str
    location_tier: str


@dataclass(frozen=True)
class DigestPayload:
    """Serializable digest container produced by :func:`select_digest`.

    Attributes:
        profile_name: Alert profile used for selection.
        niche: Industry niche the digest was scoped to.
        generated_at: ISO 8601 UTC timestamp of the ``now`` reference.
        freshness_days: Freshness window length in days.
        limit: Maximum number of jobs the digest was capped to.
        count: Number of jobs actually selected (``<= limit``).
        jobs: Selected digest rows, ranked best-first.
    """

    profile_name: str
    niche: str
    generated_at: str
    freshness_days: int
    limit: int
    count: int
    jobs: tuple[DigestJob, ...] = field(default_factory=tuple)


def _has_niche(job: Any, niche: str) -> bool:
    """Return True if ``job.industry_niche`` equals ``niche``."""
    return getattr(job, "industry_niche", None) == niche


def _is_new(job: Any) -> bool:
    """Return True if ``job.status`` is the post-enrichment ``NEW`` status."""
    return getattr(job, "status", None) == DIGEST_JOB_STATUS_NEW


def _has_description(job: Any) -> bool:
    """Return True if ``job.description`` is a non-blank string.

    Whitespace-only descriptions are rejected: an enriched row whose description
    is just line breaks carries no digest value, and a renderer would surface an
    empty card.
    """
    description = getattr(job, "description", None)
    if description is None:
        return False
    return bool(str(description).strip())


def _is_fresh(date_scraped: Any, aware_now: datetime, cutoff: timedelta) -> bool:
    """Return True if ``date_scraped`` is within ``cutoff`` of ``aware_now``.

    Both sides are normalized to aware UTC via :func:`aware_utc` so a naive DB
    value never raises ``TypeError`` against an aware ``now``. A future
    ``date_scraped`` (clock skew / bad data) counts as fresh: a job scraped
    "tomorrow" is recent, so it is eligible. Future dates are instead neutralized
    in RANKING via :func:`_effective_rank_timestamp` so they cannot dominate real
    jobs. A missing ``date_scraped`` maps to the epoch and is therefore stale.
    """
    return (aware_now - aware_utc(date_scraped)) <= cutoff


def _effective_rank_timestamp(date_scraped: Any, aware_now: datetime) -> float:
    """Return the UTC timestamp used for ranking, capped at ``aware_now``.

    A future ``date_scraped`` (clock skew / bad source data) is clamped to
    ``aware_now`` so it ranks as the most recent legitimate instant rather than
    dominating real jobs indefinitely -- a far-future timestamp would otherwise
    sort first forever under the ``date_scraped`` descending ranking criterion.
    A past or exactly-``now`` date is returned unchanged. A missing
    ``date_scraped`` maps to the epoch (oldest) via :func:`aware_utc`, preserving
    the "unknown-age sorts last" semantics.

    Args:
        date_scraped: A ``datetime`` (aware or naive) or ``None``.
        aware_now: Timezone-aware UTC reference instant (the digest's ``now``).

    Returns:
        A POSIX timestamp (float) for use as a descending sort key.
    """
    scraped = aware_utc(date_scraped)
    if scraped > aware_now:
        return aware_now.timestamp()
    return scraped.timestamp()


def _meets_column_rules(
    job: Any, niche: str, aware_now: datetime, cutoff: timedelta
) -> bool:
    """Return True if ``job`` passes the cheap, scorer-independent eligibility rules.

    These are the rules expressible without the profile: niche, status,
    description presence, and freshness. The CV-fit gate (:func:`score_job`) is
    applied separately by :func:`select_digest` because it also yields the score
    and reasons needed for ranking and payload composition.
    """
    return (
        _has_niche(job, niche)
        and _is_new(job)
        and _has_description(job)
        and _is_fresh(getattr(job, "date_scraped", None), aware_now, cutoff)
    )


def _to_score_record(job: Any) -> dict:
    """Build the dict shape :func:`score_job` expects from a Job-like object."""
    return {
        "title": getattr(job, "title", None),
        "raw_location": getattr(job, "raw_location", None),
        "description": getattr(job, "description", None),
    }


def _opt_str(job: Any, name: str) -> str:
    """Return a stringified optional attribute, or ``""`` when missing/None."""
    value = getattr(job, name, None)
    if value is None:
        return ""
    return str(value)


def _opt_float(job: Any, name: str) -> float | None:
    """Return an optional numeric attribute as float, or ``None``.

    Coerces SQLAlchemy ``Decimal`` salary values to ``float`` for JSON
    serializability. ``None`` and ``NaN`` both map to ``None`` so a digest never
    surfaces a NaN salary to a renderer.
    """
    value = getattr(job, name, None)
    if value is None:
        return None
    # float("nan") is the only value not equal to itself; covers numpy.nan too.
    if isinstance(value, float) and value != value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Non-numeric value for %s: %r; treating as None", name, value)
        return None


def _to_digest_job(job: Any, scored: dict) -> DigestJob:
    """Compose a serializable :class:`DigestJob` from a Job row and its scored dict.

    Args:
        job: Job-like object with the digest-relevant attributes.
        scored: The dict returned by :func:`score_job` for this job.

    Returns:
        A frozen :class:`DigestJob` with primitives/tuples only.
    """
    return DigestJob(
        id=int(getattr(job, "id", 0)),
        title=_opt_str(job, "title"),
        company=_opt_str(job, "company"),
        location=_opt_str(job, "raw_location"),
        site=_opt_str(job, "site"),
        job_url=_opt_str(job, "job_url"),
        score=int(scored[DIGEST_KEY_SCORE]),
        match_reasons=tuple(scored.get(DIGEST_KEY_MATCH_REASONS, [])),
        date_scraped=aware_utc(getattr(job, "date_scraped", None)).isoformat(),
        salary_min=_opt_float(job, "salary_min"),
        salary_max=_opt_float(job, "salary_max"),
        currency=_opt_str(job, "currency"),
        description=_opt_str(job, "description"),
        # "matched_city" has no DIGEST_KEY_* constant in the codebase (the
        # matcher/scorer set it as a literal), so it is referenced by name here.
        matched_city=scored.get("matched_city", ""),
        matched_role_group=scored.get(DIGEST_KEY_MATCHED_ROLE_GROUP, ""),
        location_tier=scored.get(DIGEST_KEY_LOCATION_TIER, ""),
    )


def select_digest(
    jobs: list[Any],
    now: datetime,
    *,
    profile: AlertProfile | None = None,
    niche: str = DIGEST_NICHE,
    freshness_days: int = DIGEST_DEFAULT_FRESHNESS_DAYS,
    limit: int = DIGEST_DEFAULT_LIMIT,
) -> DigestPayload:
    """Select and rank the top digest jobs for the Industrial Bajío profile.

    Filters ``jobs`` by the eligibility contract (niche / status NEW /
    description present / freshness / CV-fit via :func:`score_job`), ranks the
    survivors by score descending then ``date_scraped`` descending then ``id``
    ascending, caps at ``limit``, and returns a serializable
    :class:`DigestPayload`.

    Args:
        jobs: Iterable of Job-like objects exposing ``id``, ``title``,
            ``raw_location``, ``description``, ``date_scraped``,
            ``industry_niche``, ``status`` and the optional salary/company/site
            fields. ORM ``Job`` rows and ``SimpleNamespace`` test doubles both
            work.
        now: Reference datetime (aware or naive) for the freshness window.
            Required and explicit so tests are deterministic; production passes
            ``datetime.now(timezone.utc)``.
        profile: Alert profile to score against. ``None`` resolves the profile
            registered under :data:`DIGEST_PROFILE_NAME`.
        niche: Industry niche to scope the digest to.
        freshness_days: Hard freshness cutoff in days.
        limit: Maximum jobs to return. Negative values are clamped to 0 so the
            slice never wraps to tail elements.

    Returns:
        A :class:`DigestPayload` with the ranked selected jobs.

    Raises:
        ValueError: If ``profile`` is ``None`` and no profile is registered under
            :data:`DIGEST_PROFILE_NAME`. The digest's purpose is CV-informed
            selection; without a profile there is no fit signal, so failing
            loudly is more honest than silently surfacing unranked jobs.
    """
    resolved_profile = profile
    if resolved_profile is None:
        resolved_profile = get_alert_profile(DIGEST_PROFILE_NAME)
        if resolved_profile is None:
            logger.error("Alert profile '%s' not found; cannot build digest.", DIGEST_PROFILE_NAME)
            raise ValueError(
                f"Alert profile '{DIGEST_PROFILE_NAME}' not found. "
                f"Register it in notifications.profiles or pass profile= explicitly."
            )

    aware_now = aware_utc(now)
    cutoff = timedelta(days=freshness_days)
    # Negative limit would make scored_pairs[:limit] wrap to tail elements; clamp
    # to 0 so a misconfigured limit yields an empty digest instead of the last N.
    safe_limit = max(0, limit)

    scored_pairs: list[tuple[Any, dict]] = []
    for job in jobs:
        if not _meets_column_rules(job, niche, aware_now, cutoff):
            continue
        scored = score_job(_to_score_record(job), resolved_profile)
        if scored is None:
            # Scorer rejected: wrong geography, reject keyword, or no role signal.
            # This is the explicit rejection of unsuitable jobs.
            continue
        scored_pairs.append((job, scored))

    scored_pairs.sort(
        key=lambda pair: (
            -pair[1][DIGEST_KEY_SCORE],
            # Cap the ranking timestamp at now so a bad future date_scraped
            # cannot outrank legitimate jobs indefinitely; see
            # _effective_rank_timestamp for the rationale.
            -_effective_rank_timestamp(pair[0].date_scraped, aware_now),
            pair[0].id,
        )
    )
    capped = scored_pairs[:safe_limit]
    digest_jobs = tuple(_to_digest_job(job, scored) for job, scored in capped)

    logger.info(
        "Selected %d digest jobs for profile '%s' (niche='%s', freshness=%dd, limit=%d)",
        len(digest_jobs),
        resolved_profile.name,
        niche,
        freshness_days,
        safe_limit,
    )
    return DigestPayload(
        profile_name=resolved_profile.name,
        niche=niche,
        generated_at=aware_now.isoformat(),
        freshness_days=freshness_days,
        limit=safe_limit,
        count=len(digest_jobs),
        jobs=digest_jobs,
    )


def payload_to_dict(payload: DigestPayload) -> dict:
    """Return a plain-dict, JSON-serializable view of ``payload``.

    Convenience wrapper around :func:`dataclasses.asdict` so a future
    renderer/sender does not need to know about dataclasses.
    """
    return asdict(payload)
