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
* passes the digest-specific strong-signal gate
  (:func:`notifications.digest._has_strong_title_signal`). This is STRICTER than the scorer: it
  requires a growth role-group keyword OR a non-trade ``include_keywords`` entry
  to appear in the job's ``title`` ONLY -- NOT in the ``description`` and NOT in
  the ``career``. The email digest headline is the title, so a career-only
  signal is too coarse: a job like ``"ING. ELECTRICO"`` matched only because the
  description contains a generic keyword (e.g. ``"calidad"``) and the career
  happens to read ``"Ingeniero Industrial"`` must NOT surface in the daily
  email. Low-priority industrial-trades keywords (maintenance / welding /
  fabrication / electrical) are excluded from the gate: a trade-only title
  signal (e.g. title ``"Mantenimiento Electrico"``) does NOT satisfy the gate
  by itself -- the job must also carry a growth role-group keyword (or a
  non-trade include keyword) in the title. Honoring ``include_keywords`` keeps
  the gate consistent with the scorer for title-driven matches the role-group
  buckets do not cover (e.g. bare ``"almacen"`` / ``"produccion"``). The gate is
  applied ONLY here, in the digest selector, so the shared scorer/matcher stay
  broad for the enrichment bucket. Title-required behavior is intentional: the
  scorer/matcher/profiles stay unchanged and broad.

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

Secondary fallback section:

The strict title gate above is the authority for the PRIMARY digest list, but
it is intentionally strict -- a scorer-accepted job whose only role signal
lives in the description (not the title) is a real nearby option the subscriber
may still want to review, just at lower confidence. Such jobs (scorer-accepted,
base-column-rules-passing, freshness-passing, but gate-REJECTED) are collected
into a secondary ``fallback_jobs`` list, ranked by the SAME score/date/id key,
capped at ``fallback_limit`` (default 5), and excluding any job already in the
primary list. The gate is mutually exclusive (a job is either primary or
fallback, never both), so the primary-id exclusion is defensive against
duplicate-id input rows. The scorer/matcher/profiles stay broad; the fallback
path only reuses scorer-accepted candidates the strict gate set aside, so no
enrichment behavior changes. A future renderer/sender renders the secondary
section under a distinct heading only when it is non-empty.

Pure: no network, no DB, no email, no NLP. ``now`` is a required explicit
parameter so tests are deterministic; production passes
``datetime.now(timezone.utc)``.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from notifications.matcher import _fold_accents, _keyword_in_text
from notifications.profiles import AlertProfile, RoleGroup, get_alert_profile
from notifications.scoring import (
    DIGEST_KEY_LOCATION_TIER,
    DIGEST_KEY_MATCH_REASONS,
    DIGEST_KEY_MATCHED_ROLE_GROUP,
    DIGEST_KEY_MATCHED_ROLE_KEYWORD,
    DIGEST_KEY_SCORE,
    score_job,
)
from shared.config import (
    ALERT_DIGEST_FALLBACK_LIMIT,
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
# Cap for the secondary fallback section (lower-confidence scorer-accepted jobs
# the strict title gate set aside). Mirrors the primary cap's env-derived source
# so ops can tune both from one config module.
DIGEST_DEFAULT_FALLBACK_LIMIT: int = ALERT_DIGEST_FALLBACK_LIMIT
DIGEST_PROFILE_NAME: str = ALERT_DIGEST_PROFILE

# Status that means "enriched, awaiting digest". Matches the enrichment bucket's
# post-enrichment transition (PENDING_ENRICHMENT -> NEW).
DIGEST_JOB_STATUS_NEW: str = "NEW"

# The lowest-priority role group is skilled industrial trades (maintenance /
# welding / fabrication / electrical). These are valid enrichment candidates but
# not the subscriber's career-growth path: a digest entry whose ONLY title
# signal is a trades keyword is too weak to surface in a daily email. The digest
# gate identifies this group by name (with a minimum-weight fallback for
# robustness) and treats its keywords as weak, requiring instead a stronger
# signal from a growth role group OR a non-trade include keyword in the title.
# This is digest-local: the shared scorer / matcher stay broad so the enrichment
# bucket still collects trade candidates.
DIGEST_LOW_PRIORITY_ROLE_GROUP_NAME: str = (
    "industrial trades (maintenance / welding / fabrication)"
)


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
        limit: Maximum number of PRIMARY jobs the digest was capped to.
        count: Number of PRIMARY jobs actually selected (``<= limit``). This is
            the strict, title-gate-authoritative count; the secondary
            ``fallback_jobs`` list is reported separately so callers and tests
            can distinguish the two confidence tiers without ambiguity.
        jobs: Selected PRIMARY digest rows, ranked best-first.
        fallback_jobs: Lower-confidence secondary rows (scorer-accepted but
            strict-title-gate-rejected), ranked by the same score/date/id key,
            capped at ``fallback_limit``, and excluding any job already in
            ``jobs``. Empty when no such candidates exist; a renderer omits the
            secondary section entirely when this is empty.
    """

    profile_name: str
    niche: str
    generated_at: str
    freshness_days: int
    limit: int
    count: int
    jobs: tuple[DigestJob, ...] = field(default_factory=tuple)
    fallback_jobs: tuple[DigestJob, ...] = field(default_factory=tuple)


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


def _low_priority_trade_keywords(
    role_groups: tuple[RoleGroup, ...],
) -> frozenset[str]:
    """Return the weak trade keywords that must NOT alone satisfy the digest gate.

    Identifies the industrial-trades group by its declared name
    (:data:`DIGEST_LOW_PRIORITY_ROLE_GROUP_NAME`); if no group matches the name
    (the profile was renamed or replaced), falls back to the minimum-weight
    group(s) so the digest gate still excludes the lowest-priority bucket. The
    returned keywords are treated as weak: a title signal that only hits these
    tokens is rejected unless a growth role-group keyword or a non-trade include
    keyword also appears in the title.

    Args:
        role_groups: The profile's role groups (ordered highest weight first).

    Returns:
        A frozenset of accent-folded lowercase keywords that are weak digest
        signals. Empty when ``role_groups`` is empty.
    """
    if not role_groups:
        return frozenset()
    low_priority = [
        group
        for group in role_groups
        if group.name == DIGEST_LOW_PRIORITY_ROLE_GROUP_NAME
    ]
    if not low_priority:
        min_weight = min(group.weight for group in role_groups)
        low_priority = [group for group in role_groups if group.weight == min_weight]
        logger.warning(
            "Low-priority role group '%s' not found in profile; falling back to "
            "minimum-weight group(s) %s for the digest trade-keyword gate.",
            DIGEST_LOW_PRIORITY_ROLE_GROUP_NAME,
            [group.name for group in low_priority],
        )
    return frozenset(
        keyword for group in low_priority for keyword in group.keywords
    )


def _has_strong_title_signal(
    job: Any,
    scored: dict,
    role_groups: tuple[RoleGroup, ...],
    include_keywords: tuple[str, ...] = (),
) -> bool:
    """Return True if a strong non-weak role/industry keyword appears in TITLE.

    This is the digest-specific STRONG-SIGNAL gate, stricter than the scorer.
    The scorer (:func:`score_job`) accepts a job when a role-group keyword OR an
    include keyword appears anywhere in ``title + description``; that lets a
    generic body keyword (e.g. ``"calidad"``) pull in a job whose title is
    unrelated (e.g. ``"ING. ELECTRICO"``). Broad enrichment wants those
    candidates, but a daily EMAIL digest should not surface them -- the
    subscriber sees the TITLE as the digest headline, so a heading that does not
    match the role loses trust in the alert.

    The gate inspects the job's ``title`` ONLY. ``career`` is intentionally
    IGNORED: a career-only signal is too coarse because the email digest
    headline is the title, not the career. A real-world example: a job titled
    ``"ING. ELECTRICO"`` whose career reads ``"Ingeniero Industrial"`` and whose
    scorer-winning signal is a description-only ``"calidad"`` was surfacing in
    the digest only because the career contained the growth keyword
    ``"ingeniero industrial"`` -- the title itself carried no growth signal.
    The product rule: the digest must require a strong non-weak growth/include
    keyword in the TITLE itself.

    The gate checks the UNION of role-group keywords (the high-value CV
    vocabulary) AND ``include_keywords`` against the job's ``title`` only,
    EXCLUDING the low-priority industrial-trades keywords (maintenance / welding
    / fabrication / electrical). A trade keyword in the title is a weak signal:
    a job like ``ING. ELECTRICO`` whose title mentions ``"electricista"`` (or
    ``"mantenimiento"``) must not pass even though the scorer accepted it via a
    description-only ``calidad``. See :func:`_low_priority_trade_keywords` for
    how the weak set is derived.

    Including ``include_keywords`` honors scorer-accepted title signals that are
    NOT part of any role group (e.g. bare ``"almacen"`` and ``"produccion"``):
    the scorer accepts those jobs via the include-keyword gate, and a title hit
    on the same token is a genuine strong signal worth surfacing in the digest.
    Trade tokens that also appear in ``include_keywords`` (e.g.
    ``"mantenimiento"``, ``"electricista"``) are skipped via the same weak set
    so they cannot re-admit a trade-only job through the back door.

    It intentionally does NOT require the title keyword to be the scorer's
    winning signal: a posting titled ``Almacenista`` with ``SAP`` in the
    description is a real warehouse fit and should pass even though the
    scorer's highest-priority winning group is SAP/inventory via the body text.
    Conversely, ``ING. ELECTRICO`` with a generic ``calidad`` mention only in
    the description (and ``"Ingeniero Industrial"`` only in the career) still
    fails because neither a growth role-group keyword nor a non-trade include
    keyword appears in the TITLE -- the gate only ever inspects ``title``, so a
    description-only or career-only generic keyword is never enough.

    Args:
        job: Job-like object with ``title``.
        scored: The dict returned by :func:`score_job` for this job, carrying
            ``DIGEST_KEY_MATCHED_ROLE_KEYWORD``.
        role_groups: The profile's role groups; any non-weak role-group keyword
            in title satisfies the digest gate.
        include_keywords: The profile's include keywords; any non-weak include
            keyword in title also satisfies the gate, honoring scorer-accepted
            title signals that live outside the role-group buckets (e.g. bare
            ``"almacen"`` / ``"produccion"``).

    Returns:
        True when the digest's strong-signal contract is satisfied.
    """
    matched_role_keyword = scored.get(DIGEST_KEY_MATCHED_ROLE_KEYWORD, "")

    title_text = _fold_accents(str(getattr(job, "title", None) or "")).strip().lower()

    if not title_text:
        # No title at all: not enough signal for an email digest headline.
        return False

    # Low-priority trade keywords (maintenance / welding / electrical /
    # fabrication) are weak digest signals: a job whose only title hit is a
    # trade token is valid for broad enrichment but not the subscriber's growth
    # path, so it must not surface in the email digest unless a stronger growth
    # role-group keyword (or a non-trade include keyword) also appears in the
    # title. See _low_priority_trade_keywords for the weak-set derivation.
    weak_keywords = _low_priority_trade_keywords(role_groups)

    for group in role_groups:
        for keyword in group.keywords:
            # Skip weak trade keywords so a trade-only title signal is never
            # enough on its own; a growth group keyword still satisfies.
            if keyword in weak_keywords:
                continue
            if _keyword_in_text(keyword, title_text):
                return True

    # Role groups are the high-value CV vocabulary, but include_keywords carry
    # scorer-accepted strong title signals that no role group covers (e.g. bare
    # "almacen"/"produccion"). Honor them so the digest gate does not contradict
    # the scorer for title-driven matches. Trade tokens that also live in
    # include_keywords are skipped via the same weak set so they cannot re-admit
    # a trade-only job through the back door.
    for keyword in include_keywords:
        if keyword in weak_keywords:
            continue
        if _keyword_in_text(keyword, title_text):
            return True

    # No strong keyword in title: the role signal came from the description
    # and/or the career alone. Too weak for an email digest whose headline is
    # the title.
    role_group_name = scored.get(DIGEST_KEY_MATCHED_ROLE_GROUP, "")
    logger.info(
        "Digest strong-signal gate rejected job id=%s: role keyword '%s' not in "
        "title ('%s'); career-only ('%s') or description-only signal is too "
        "coarse for the email digest headline (title-required).",
        getattr(job, "id", "?"),
        matched_role_keyword or role_group_name,
        getattr(job, "title", ""),
        getattr(job, "career", ""),
    )
    return False


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
    # float("nan") is the only float not equal to itself; covers numpy.nan too.
    if isinstance(value, float) and value != value:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        logger.warning("Non-numeric value for %s: %r; treating as None", name, value)
        return None
    # Decimal('NaN') is NOT a float, so the isinstance check above misses it;
    # float(Decimal('NaN')) returns nan here. Catch it after conversion so a
    # NaN never leaks into the payload as a real float (which the renderer
    # would format as "nan"). math.isnan covers both float and Decimal paths.
    if math.isnan(result):
        logger.warning("NaN salary value for %s; treating as None", name)
        return None
    return result


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
    fallback_limit: int = DIGEST_DEFAULT_FALLBACK_LIMIT,
) -> DigestPayload:
    """Select and rank the top digest jobs for the Industrial Bajío profile.

    Filters ``jobs`` by the eligibility contract (niche / status NEW /
    description present / freshness / CV-fit via :func:`score_job`), then splits
    the scorer-accepted survivors into two tiers:

    * PRIMARY (``jobs``): the strict title-gate-passing matches, ranked by score
      descending then ``date_scraped`` descending then ``id`` ascending, capped
      at ``limit``.
    * SECONDARY (``fallback_jobs``): the scorer-accepted matches that FAILED the
      strict title gate (lower confidence), ranked by the SAME key, capped at
      ``fallback_limit``, and excluding any job already selected for primary.

    Returns a serializable :class:`DigestPayload` carrying both tiers. The
    scorer/matcher/profiles are not changed: the fallback path only reuses
    scorer-accepted candidates the strict gate set aside.

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
        limit: Maximum PRIMARY jobs to return. Negative values are clamped to 0
            so the slice never wraps to tail elements.
        fallback_limit: Maximum SECONDARY (fallback) jobs to return. Negative
            values are clamped to 0. Set to 0 to disable the secondary section.

    Returns:
        A :class:`DigestPayload` with the ranked selected primary jobs and the
        lower-confidence fallback jobs.

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
    # Negative limits would make the slices wrap to tail elements; clamp to 0 so
    # a misconfigured limit yields an empty tier instead of the last N.
    safe_limit = max(0, limit)
    safe_fallback_limit = max(0, fallback_limit)

    # Scorer-accepted survivors split by the strict title gate: gate-passing
    # jobs are primary candidates; gate-rejected (but scorer-accepted, base-rules
    # and freshness passing) jobs are lower-confidence fallback candidates. The
    # scorer stays the single fit authority; the gate is digest-local.
    primary_pairs: list[tuple[Any, dict]] = []
    fallback_pairs: list[tuple[Any, dict]] = []
    for job in jobs:
        if not _meets_column_rules(job, niche, aware_now, cutoff):
            continue
        scored = score_job(_to_score_record(job), resolved_profile)
        if scored is None:
            # Scorer rejected: wrong geography, reject keyword, or no role signal.
            # This is the explicit rejection of unsuitable jobs -- not a fallback
            # candidate either, because there is no fit signal at all.
            continue
        if _has_strong_title_signal(
            job, scored, resolved_profile.role_groups, resolved_profile.include_keywords
        ):
            primary_pairs.append((job, scored))
        else:
            # Scorer-accepted but the strict title gate rejected it: the role
            # signal lives in the description/career, not the title. Still a
            # valid lower-confidence candidate for the secondary section.
            fallback_pairs.append((job, scored))

    # Both tiers share the SAME ranking key (score desc, date_scraped desc, id
    # asc) so the fallback list is ordered exactly as the primary would be.
    def _rank_key(pair: tuple[Any, dict]) -> tuple[int, float, int]:
        job_obj, scored_dict = pair
        return (
            -int(scored_dict[DIGEST_KEY_SCORE]),
            # Cap the ranking timestamp at now so a bad future date_scraped
            # cannot outrank legitimate jobs indefinitely; see
            # _effective_rank_timestamp for the rationale.
            -_effective_rank_timestamp(job_obj.date_scraped, aware_now),
            int(job_obj.id),
        )

    primary_pairs.sort(key=_rank_key)
    fallback_pairs.sort(key=_rank_key)

    capped_primary = primary_pairs[:safe_limit]
    # Exclude any job already selected for primary. The strict gate is mutually
    # exclusive (a job is either primary or fallback, never both), so this only
    # matters for duplicate-id input rows -- but the product rule is explicit,
    # so the filter is kept as a defensive guarantee.
    primary_ids = {job.id for job, _ in capped_primary}
    capped_fallback = [
        pair for pair in fallback_pairs if pair[0].id not in primary_ids
    ][:safe_fallback_limit]

    digest_jobs = tuple(_to_digest_job(job, scored) for job, scored in capped_primary)
    fallback_jobs = tuple(_to_digest_job(job, scored) for job, scored in capped_fallback)

    logger.info(
        "Selected %d primary digest jobs and %d fallback jobs for profile '%s' "
        "(niche='%s', freshness=%dd, limit=%d, fallback_limit=%d)",
        len(digest_jobs),
        len(fallback_jobs),
        resolved_profile.name,
        niche,
        freshness_days,
        safe_limit,
        safe_fallback_limit,
    )
    return DigestPayload(
        profile_name=resolved_profile.name,
        niche=niche,
        generated_at=aware_now.isoformat(),
        freshness_days=freshness_days,
        limit=safe_limit,
        count=len(digest_jobs),
        jobs=digest_jobs,
        fallback_jobs=fallback_jobs,
    )


def payload_to_dict(payload: DigestPayload) -> dict:
    """Return a plain-dict, JSON-serializable view of ``payload``.

    Convenience wrapper around :func:`dataclasses.asdict` so a future
    renderer/sender does not need to know about dataclasses.
    """
    return asdict(payload)
