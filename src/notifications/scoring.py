"""Deterministic, CV-informed job scorer for alert profiles.

The scorer extends the binary contract in :mod:`notifications.matcher` with a
transparent additive score and human-readable reasons, so a future email digest
can both rank and explain why each job was surfaced.

Design rules:

* **Pure**: no network, email, database, or NLP. Reads only record dicts.
* **Deterministic**: same inputs -> same outputs, no randomness, no time of day.
* **Backward-compatible geography**: reuses :func:`matcher._matches_location`,
  so the strict Guanajuato city/state logic is identical to the binary matcher.
  Jobs outside the allowed geography return ``None`` (score = reject).
* **Hard rejects first**: any term in the profile's ``exclude_keywords`` OR
  ``reject_keywords`` present in the searchable text returns ``None``, even when
  a high-weight role group would otherwise match (e.g. "Becario SAP WM").
* **Additive score**: ``location_tier_weight + role_group_weight``. Both are
  optional per profile; a profile with empty tiers/groups scores jobs at 0 and
  still works as a pure filter (matching the binary matcher's verdict).
* **First-match-wins role group**: groups are declared highest weight first; the
  first group with any keyword in the searchable text wins. This gives the most
  favorable interpretation to a posting (e.g. an "Analista de Almacen" title
  wins the SAP/inventory group, not a downstream "almacenista" fallback).
* **Stable ordering**: :func:`score_jobs` sorts by score descending; ties keep
  the original input order (Python's stable sort), so output is reproducible.

The returned dict is a shallow copy of the input record (never mutating it) plus
scoring fields. It is intentionally a plain dict, not a dataclass, so it composes
with the existing matcher digest shape (``matched_city``/``matched_keyword``)
and stays trivial to serialize for a future email renderer.
"""
from __future__ import annotations

import logging
from typing import Any

from notifications.matcher import _first_non_empty, _keyword_in_text, _matches_location
from notifications.profiles import AlertProfile, RoleGroup, LocationTier

logger = logging.getLogger(__name__)

# Sentinel role group / location tier names used when a profile has none defined.
_NO_ROLE_GROUP = ""
_NO_LOCATION_TIER = ""

# Keys added to the digest dict by the scorer. Kept module-level so callers and
# tests can reference them by name rather than by string literals.
DIGEST_KEY_SCORE = "score"
DIGEST_KEY_MATCH_REASONS = "match_reasons"
DIGEST_KEY_MATCHED_ROLE_GROUP = "matched_role_group"
DIGEST_KEY_MATCHED_ROLE_WEIGHT = "matched_role_weight"
DIGEST_KEY_MATCHED_ROLE_KEYWORD = "matched_role_keyword"
DIGEST_KEY_LOCATION_TIER = "location_tier"
DIGEST_KEY_LOCATION_WEIGHT = "location_weight"


def _find_location_tier(
    matched_city: str,
    tiers: tuple[LocationTier, ...],
) -> tuple[str, int]:
    """Return ``(tier_name, weight)`` for ``matched_city``.

    Args:
        matched_city: A city token already validated by :func:`_matches_location`.
        tiers: Location tiers in declared order (highest weight first).
            Duplicates across tiers are resolved by first match.

    Returns:
        ``(tier_name, weight)`` for the first tier containing the city, or
        ``("", 0)`` when the city is allowed but in no tier (still matched).
    """
    for tier in tiers:
        if matched_city in tier.cities:
            return tier.name, tier.weight
    return _NO_LOCATION_TIER, 0


def _find_role_group(
    searchable: str,
    role_groups: tuple[RoleGroup, ...],
) -> tuple[str, int, str]:
    """Return ``(group_name, weight, matched_keyword)`` for the first matching group.

    Groups are evaluated in declared order (highest weight first). The first
    group with any keyword present as a substring in ``searchable`` wins.

    Args:
        searchable: Normalized (folded/lowercased) searchable text.
        role_groups: Role groups in declared order.

    Returns:
        ``(group_name, weight, matched_keyword)`` for the winning group, or
        ``("", 0, "")`` when no group matches.
    """
    for group in role_groups:
        for keyword in group.keywords:
            if _keyword_in_text(keyword, searchable):
                return group.name, group.weight, keyword
    return _NO_ROLE_GROUP, 0, ""


def _is_rejected(searchable: str, profile: AlertProfile) -> bool:
    """Return True if any hard-reject term is present in ``searchable``.

    The reject set is the union of ``profile.exclude_keywords`` (binary matcher
    excludes, unchanged) and ``profile.reject_keywords`` (scorer extras such as
    "sin remuneracion"). Exclude takes precedence over any positive signal.
    """
    for keyword in (*profile.exclude_keywords, *profile.reject_keywords):
        if _keyword_in_text(keyword, searchable):
            return True
    return False


def score_job(record: dict, profile: AlertProfile) -> dict | None:
    """Score a single job record against ``profile``.

    Reuses the binary matcher's strict geography (:func:`_matches_location`),
    hard-rejects on exclude/reject keywords, then requires a relevance signal:
    the job must carry an include keyword OR (when role groups are defined) a
    role-group hit. An allowed city with no role signal is rejected, matching the
    binary matcher's relevance semantics rather than broadening the candidate
    set. Surviving jobs get an additive score from the matched location tier and
    the first matching role group.

    Args:
        record: Job-like dict with at least ``title`` and a location field
            (``raw_location`` or ``location``). ``description`` is optional.
        profile: The subscriber :class:`AlertProfile` to score against.

    Returns:
        A shallow copy of ``record`` enriched with ``matched_city``,
        ``matched_keyword`` (the binary matcher's include hit, for parity),
        ``score``, ``match_reasons`` (human-readable list), the matched role
        group name/weight/keyword, and the location tier name/weight. Returns
        ``None`` when geography fails, a reject term is present, or no relevance
        signal (include keyword / role group) is found. The input record is
        never mutated.
    """
    location = _first_non_empty(record, "raw_location", "location")
    matched_city = _matches_location(location, profile.allowed_cities)
    if matched_city is None:
        return None

    title = _first_non_empty(record, "title")
    description = _first_non_empty(record, "description")
    searchable = "{} {}".format(title, description)

    if _is_rejected(searchable, profile):
        return None

    # Parity with the binary matcher: a job must carry a relevant role signal,
    # not just sit in an allowed city. An allowed-city "Recepcionista" posting
    # has no include keyword and (if defined) no role-group hit; the binary
    # matcher rejects it, and so must the scorer, otherwise we broaden the
    # candidate set instead of ranking existing alert matches.
    matched_keyword = ""
    for keyword in profile.include_keywords:
        if _keyword_in_text(keyword, searchable):
            matched_keyword = keyword
            break

    role_group_name, role_weight, matched_role_keyword = _find_role_group(
        searchable, profile.role_groups
    )
    has_role_group_signal = bool(role_group_name)

    # No include keyword AND no role-group hit means no relevant signal: reject.
    # When role_groups are defined, a role-group hit is sufficient on its own
    # (some group keywords extend beyond include_keywords, e.g. English "sap");
    # when no role_groups are defined, fall back to include_keywords exactly
    # like the binary matcher.
    if profile.role_groups:
        if not matched_keyword and not has_role_group_signal:
            return None
    elif not matched_keyword:
        return None

    tier_name, location_weight = _find_location_tier(
        matched_city, profile.location_tiers
    )

    score = location_weight + role_weight

    reasons: list[str] = []
    if tier_name:
        reasons.append(
            "Location: {} ({} +{})".format(matched_city, tier_name, location_weight)
        )
    else:
        reasons.append("Location: {} (no tier defined +0)".format(matched_city))
    if role_group_name:
        reasons.append(
            "Role: {} (+{} via '{}')".format(
                role_group_name, role_weight, matched_role_keyword
            )
        )
    else:
        reasons.append("Role: no priority group matched (+0)")

    digest = dict(record)
    digest["matched_city"] = matched_city
    digest["matched_keyword"] = matched_keyword
    digest[DIGEST_KEY_SCORE] = score
    digest[DIGEST_KEY_MATCH_REASONS] = reasons
    digest[DIGEST_KEY_MATCHED_ROLE_GROUP] = role_group_name
    digest[DIGEST_KEY_MATCHED_ROLE_WEIGHT] = role_weight
    digest[DIGEST_KEY_MATCHED_ROLE_KEYWORD] = matched_role_keyword
    digest[DIGEST_KEY_LOCATION_TIER] = tier_name
    digest[DIGEST_KEY_LOCATION_WEIGHT] = location_weight
    return digest


def score_jobs(records: list[dict], profile: AlertProfile) -> list[dict]:
    """Score and rank ``records`` against ``profile``, capped at ``profile.max_jobs``.

    Unlike :func:`matcher.match_jobs` (which preserves input order and exists for
    binary filtering), this function ranks by descending score so the strongest
    career-growth fits surface first. Ties preserve input order (stable sort) so
    output is deterministic across runs.

    Args:
        records: Iterable of job-like dicts (see :func:`score_job`).
        profile: The subscriber :class:`AlertProfile` to score against.

    Returns:
        Ranked list of digest-ready dicts (scored, explained), never longer
        than ``profile.max_jobs``.
    """
    scored: list[dict] = []
    for record in records:
        digest = score_job(record, profile)
        if digest is not None:
            scored.append(digest)
    scored.sort(key=lambda r: r[DIGEST_KEY_SCORE], reverse=True)
    capped = scored[: profile.max_jobs]
    logger.info(
        "Scored %d/%d jobs for profile '%s' (cap=%d)",
        len(capped),
        len(records),
        profile.name,
        profile.max_jobs,
    )
    return capped