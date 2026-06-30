"""Deterministic job matcher for alert profiles.

Given job-like record dicts (the shape produced by ``etl.transform.transform_data``
or scraper rows) and an :class:`AlertProfile`, this module filters jobs by strict
allowed-city geography plus include/exclude keyword rules.

The matcher is pure: no network, no email, no database, no NLP. It only reads
fields from the input dicts and returns digest-ready copies of the matches.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from notifications.profiles import AlertProfile

logger = logging.getLogger(__name__)

# City tokens that share their name with a Mexican state are ambiguous: a bare
# "Guanajuato" could mean the state (anywhere in it) rather than the capital
# city. For strict alerts, such tokens are only accepted when the location is in
# "city, state" form (i.e. has a comma), which signals the city is intended.
# Unambiguous city tokens (e.g. "irapuato") match with or without a comma.
STATE_HOMONYMOUS_CITIES: frozenset[str] = frozenset({"guanajuato"})

# Accepted state-suffix indicators for the target geography (Guanajuato/Bajio).
# When a location carries a state suffix (text after the first comma), it must
# match one of these or the job is rejected regardless of the city token.
# "guanajuato" covers "Guanajuato" / "Guanajuato, Mexico"; "gto" covers
# "Gto." / "GTO" / "Gto".
GUANAJUATO_STATE_TOKENS: frozenset[str] = frozenset({"guanajuato", "gto"})

# Include/reject keywords that must match on word boundaries rather than as bare
# substrings. These are short, high-risk CV tokens curated by auditing each
# keyword against common Spanish/English words:
#   - "sap" leaks inside "whatsapp" and "sapphire".
#   - "quality" leaks inside "equality" and "inequality".
#   - "lean" leaks inside "cleans", "cleanliness", "leaning", and the Spanish
#     "lineamiento" (policy guideline).
# Longer tokens (warehouse, inventory, materials, logistics) have no common
# host word, and forcing boundaries on them would lose legitimate plurals such
# as "warehouses"; Spanish terms like "almacen" stay substring-based so they
# still match "almacenista". Only demonstrably-leaky tokens get exact matching.
_EXACT_MATCH_KEYWORDS: frozenset[str] = frozenset({"sap", "quality", "lean"})


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Return True if ``keyword`` is present in ``text`` under keyword semantics.

    Members of :data:`_EXACT_MATCH_KEYWORDS` require word boundaries so e.g.
    ``"sap"`` matches ``"SAP"`` / ``"SAP-WM"`` / ``"SAP."`` but NOT ``"whatsapp"``
    or ``"sapphire"``, and ``"quality"`` does not match ``"equality"``. All other
    keywords use plain substring matching, preserving useful behavior like
    ``"almacen"`` matching ``"almacenista"``. Used by the matcher and the scorer
    so relevance semantics stay identical across both layers.

    Args:
        keyword: Accent-folded lowercase keyword.
        text: Normalized (folded/lowercased) searchable text.

    Returns:
        True when the keyword matches under its semantics.
    """
    if keyword in _EXACT_MATCH_KEYWORDS:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def _fold_accents(text: str) -> str:
    """Return ``text`` with combining diacritical marks removed (NFD -> strip Mn).

    "León" -> "Leon", "Ingeniería" -> "Ingenieria". This lets keyword and city
    tokens match regardless of how the source spelled accents.
    """
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _normalize(value: Any) -> str:
    """Lowercase, accent-fold, and strip a value, treating None/NaN as empty.

    Args:
        value: A string, ``None``, or a float NaN. Other types are coerced via
            ``str()``.

    Returns:
        The normalized string, or ``""`` for missing/NaN values.
    """
    if value is None:
        return ""
    # float("nan") is the only value not equal to itself; covers numpy.nan too.
    if isinstance(value, float) and value != value:
        return ""
    return _fold_accents(str(value)).strip().lower()


def _first_non_empty(record: dict, *keys: str) -> str:
    """Return the first non-empty normalized value found among ``keys``.

    Lets the matcher accept both transform records (``raw_location``) and raw
    scraper-style dicts (``location``) without callers normalizing first.
    """
    for key in keys:
        text = _normalize(record.get(key))
        if text:
            return text
    return ""


def _is_guanajuato_state_suffix(suffix: str) -> bool:
    """Return True if a state suffix indicates the Guanajuato/Bajio target.

    Accepts full and abbreviated forms after accent-folding and lowercasing,
    e.g. "Guanajuato", "Gto.", "GTO", and "Guanajuato, Mexico". Punctuation is
    ignored by tokenizing on letters only.

    Args:
        suffix: Raw or normalized text after the first comma of a location.

    Returns:
        True when the suffix contains a Guanajuato state token.
    """
    normalized = _normalize(suffix)
    if not normalized:
        return False
    tokens = set(re.findall(r"[a-z]+", normalized))
    return bool(tokens & GUANAJUATO_STATE_TOKENS)


def _matches_location(location: str, allowed_cities: tuple[str, ...]) -> str | None:
    """Return the matched city token if the location is in the target geography.

    The location is split into a city part (before the first comma) and an
    optional state suffix (after it). Matching rules, in order:

    1. If a state suffix is present, it must indicate Guanajuato
       (``GUANAJUATO_STATE_TOKENS``). A non-Guanajuato suffix such as
       "Nuevo Leon" or "Jalisco" rejects the job outright, even when the city
       name matches an allowed token (e.g. "Leon, Nuevo Leon" is rejected).
    2. The city token must anchor the start of the city part followed by a word
       boundary. This prevents "leon" matching "Nuevo Leon" or "Leona", and
       keeps "guanajuato" from matching "San Francisco del Rincon, Guanajuato".
    3. A state-homonymous token (``STATE_HOMONYMOUS_CITIES``) is rejected when
       there is no state suffix: a bare "Guanajuato" is ambiguous (state vs
       capital city), so it is rejected for strict alerts. "Guanajuato,
       Guanajuato" passes because rule 1 validates the suffix.

    Args:
        location: Normalized (folded/lowercased) location string.
        allowed_cities: Accent-folded lowercase city tokens.

    Returns:
        The matching city token, or ``None`` when the location is outside the
        target geography or matches no allowed city.
    """
    if not location:
        return None
    parts = location.split(",", 1)
    city_part = parts[0].strip()
    if not city_part:
        return None
    state_suffix = parts[1] if len(parts) > 1 else ""
    has_state_suffix = bool(state_suffix)
    # A present state suffix must be Guanajuato. A different state means the job
    # is outside the Bajio target even if the city name matches an allowed token.
    if has_state_suffix and not _is_guanajuato_state_suffix(state_suffix):
        return None
    for city in allowed_cities:
        # Anchored prefix + word boundary: "leon" matches "leon" and
        # "leon de los aldama" but not "nuevo leon" or "leona".
        if not re.match(rf"^{re.escape(city)}\b", city_part):
            continue
        # "guanajuato" is both a city and a state. Without a state suffix a bare
        # "Guanajuato" is ambiguous (could be the state), so reject it; the
        # "city, state" form is unambiguous (suffix already validated above).
        if city in STATE_HOMONYMOUS_CITIES and not has_state_suffix:
            continue
        return city
    return None


def _matches_keywords(
    text: str,
    include_keywords: tuple[str, ...],
    exclude_keywords: tuple[str, ...],
) -> str | None:
    """Return the matched include keyword if ``text`` is allowed and relevant.

    Exclude keywords take precedence: if any exclude keyword is present, the job
    is rejected even when an include keyword also matches.

    Args:
        text: Normalized searchable text (typically title + description).
        include_keywords: Accent-folded lowercase keywords.
        exclude_keywords: Accent-folded lowercase keywords (already a union of
            the profile's ``exclude_keywords`` and ``reject_keywords`` at the
            call site via :func:`match_job`).

    Returns:
        The first matching include keyword, or ``None`` when excluded or when no
        include keyword is found.
    """
    for keyword in exclude_keywords:
        if _keyword_in_text(keyword, text):
            return None
    for keyword in include_keywords:
        if _keyword_in_text(keyword, text):
            return keyword
    return None


def match_job(record: dict, profile: AlertProfile) -> dict | None:
    """Evaluate a single job record against ``profile``.

    A job matches when its city part is in ``profile.allowed_cities`` AND its
    searchable text (title + description) contains an include keyword AND none of
    the hard-reject terms (``exclude_keywords`` union ``reject_keywords``) are
    present. ``reject_keywords`` is part of the global alert relevance contract:
    unpaid/volunteer terms (e.g. "sin remuneracion", "voluntario") are rejected
    by the matcher too, not only by the scorer, so every consumer of the match
    verdict shares the same relevance gate.

    Args:
        record: Job-like dict with at least ``title`` and a location field
            (``raw_location`` or ``location``). ``description`` is optional.
        profile: The subscriber :class:`AlertProfile` to match against.

    Returns:
        A shallow copy of ``record`` enriched with ``matched_city`` and
        ``matched_keyword`` when the job matches, otherwise ``None``. The input
        record is never mutated.
    """
    location = _first_non_empty(record, "raw_location", "location")
    matched_city = _matches_location(location, profile.allowed_cities)
    if matched_city is None:
        return None

    searchable = "{} {}".format(
        _first_non_empty(record, "title"),
        _first_non_empty(record, "description"),
    )
    # Union of binary exclude and scorer reject: matcher-relevant terms (e.g.
    # internships) plus contract-relevant terms (e.g. unpaid/volunteer). For
    # profiles with no reject_keywords (default empty tuple) this is exactly
    # exclude_keywords, so legacy behavior is byte-for-byte preserved.
    reject_terms = (*profile.exclude_keywords, *profile.reject_keywords)
    matched_keyword = _matches_keywords(
        searchable, profile.include_keywords, reject_terms
    )
    if matched_keyword is None:
        return None

    digest = dict(record)
    digest["matched_city"] = matched_city
    digest["matched_keyword"] = matched_keyword
    return digest


def match_jobs(records: list[dict], profile: AlertProfile) -> list[dict]:
    """Filter ``records`` by ``profile`` rules, capped at ``profile.max_jobs``.

    Args:
        records: Iterable of job-like dicts (see :func:`match_job`).
        profile: The subscriber :class:`AlertProfile` to match against.

    Returns:
        List of digest-ready matched dicts (input order preserved), never longer
        than ``profile.max_jobs``.
    """
    matched: list[dict] = []
    for record in records:
        if len(matched) >= profile.max_jobs:
            break
        digest = match_job(record, profile)
        if digest is not None:
            matched.append(digest)
    logger.info(
        "Matched %d/%d jobs for profile '%s' (cap=%d)",
        len(matched),
        len(records),
        profile.name,
        profile.max_jobs,
    )
    return matched
