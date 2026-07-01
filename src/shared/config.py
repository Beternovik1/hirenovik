# src/shared/config.py
"""Single source of truth for all Hirenovik configuration.

Environment variables are read here and exposed as module-level constants or
functions. No other module reads ``os.getenv`` directly (see CONVENTIONS.md).

Search routing is profile-driven via ``SEARCH_PROFILE`` (``tech_mx`` or
``industrial_irapuato_bajio``). ``SEARCH_PROFILE`` takes precedence over the
legacy ``WORKER_NAME`` routing when set, so existing GitHub Actions behavior is
preserved by leaving ``SEARCH_PROFILE`` unset.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

WORKER_NAME = os.getenv("WORKER_NAME", "Local_Test")

# Search profile routing. When set, takes precedence over WORKER_NAME.
# An unknown profile logs a warning and falls back to DEFAULT_SEARCH_PROFILE.
SEARCH_PROFILE = os.getenv("SEARCH_PROFILE", "").strip()
DEFAULT_SEARCH_PROFILE = "tech_mx"

SCRAPER_CONFIG = {
    "results_limit": 25,
    "hours_old": 72,
}

BUSINESS_RULES = {
    "linkedin_on_mondays": True,
}


def include_linkedin_today() -> bool:
    """Return True only on Mondays when the LinkedIn business rule is enabled."""
    is_monday = datetime.now().weekday() == 0
    return is_monday and BUSINESS_RULES["linkedin_on_mondays"]


# ---------------------------------------------------------------------------
# Search profiles
# ---------------------------------------------------------------------------
# tech_mx mirrors the historical GitHub_Actions worker config so the existing
# nationwide tech scraping behavior is preserved under the new profile model.
_TECH_MX_SEARCH_CONFIG: list[tuple[str, str, str]] = [
    ("Data Engineer", "México", "Ingeniería de Datos"),
    ("Data Analyst", "México", "Ingeniería de Datos"),
    ("Analytics Engineer", "México", "Ingeniería de Datos"),
    ("Cloud Engineer", "México", "Infraestructura Cloud"),
    ("DevOps Engineer", "México", "Infraestructura Cloud"),
    ("Python Developer", "México", "Desarrollo de Software"),
    ("React Developer", "México", "Desarrollo de Software"),
    ("Cybersecurity Engineer", "México", "Ciberseguridad"),
    ("Business Intelligence", "México", "Analítica de Datos"),
]

# Industrial Bajío CV-informed scrape seeds. These mirror the relevance
# vocabulary and role-group priority from notifications.profiles
# (INDUSTRIAL_IRAPUATO_BAJIO_PROFILE) so the discovery scope targets the
# brother's actual growth path: SAP WM, inventory/warehouse control, materials,
# quality, and industrial engineering. Low-fit trades like "Soldador" are
# intentionally dropped: alert-relevant postings for those trades still surface
# via the matcher's include_keywords (soldador/soldadura), so the discovery
# seeds stay focused on CV-fit roles that drive career-growth scoring.
# SAP / quality / industrial engineering are ordered first to document their
# higher scoring priority, though search order has no runtime effect.
_INDUSTRIAL_BAJIO_ROLES: tuple[str, ...] = (
    "SAP WM",
    "Ingeniero Industrial",
    "Analista de Inventario",
    "Coordinador de Almacén",
    "Analista de Materiales",
    "Inspector de Calidad",
)

# Cities aligned with INDUSTRIAL_IRAPUATO_BAJIO_LOCATION_TIERS. Tier 1/2
# corridors (Silao, Salamanca, Celaya) are covered for career-growth plants;
# Irapuato and León (Tier 3) are kept for corridor coverage and the subscriber's
# home base. Querétaro is intentionally excluded: the alert matcher rejects it at
# the geography gate, so seeding it would only waste scrape quota on dead leads.
_INDUSTRIAL_BAJIO_CITIES: tuple[str, ...] = (
    "Silao, Guanajuato",
    "Irapuato, Guanajuato",
    "Salamanca, Guanajuato",
    "Celaya, Guanajuato",
    "León, Guanajuato",
)

_INDUSTRIAL_BAJIO_NICHE = "Industrial Bajío"


def _build_industrial_bajio_search_config() -> list[tuple[str, str, str]]:
    """Build the role x city search grid for the industrial Bajío profile."""
    return [
        (role, city, _INDUSTRIAL_BAJIO_NICHE)
        for role in _INDUSTRIAL_BAJIO_ROLES
        for city in _INDUSTRIAL_BAJIO_CITIES
    ]


SEARCH_PROFILES: dict[str, list[tuple[str, str, str]]] = {
    "tech_mx": _TECH_MX_SEARCH_CONFIG,
    "industrial_irapuato_bajio": _build_industrial_bajio_search_config(),
}


def get_search_config_for_profile(profile_name: str) -> list[tuple[str, str, str]]:
    """Return a defensive copy of the search config for an explicit profile name.

    Used by the multi-profile daily scout to fetch each profile's search grid in
    sequence without mutating the module-level ``SEARCH_PROFILE`` env var.

    This helper FAILS CLOSED: an unknown ``profile_name`` raises ``ValueError``
    instead of silently falling back to ``tech_mx``. A silent fallback here would
    make a typo in ``DAILY_SCOUT_PROFILES`` scrape the tech grid a second time and
    duplicate DB rows. The legacy lenient fallback for manual single-profile runs
    lives in ``get_search_config`` (env ``SEARCH_PROFILE``), not here.

    Args:
        profile_name: A key in ``SEARCH_PROFILES`` (e.g. ``"tech_mx"``).

    Returns:
        A fresh list of ``(search_term, location, industry_niche)`` tuples.
        Mutating it never corrupts the shared ``SEARCH_PROFILES`` registry.

    Raises:
        ValueError: If ``profile_name`` is not a key in ``SEARCH_PROFILES``.
    """
    config = SEARCH_PROFILES.get(profile_name)
    if config is None:
        known = sorted(SEARCH_PROFILES)
        logger.error("Unknown search profile '%s'. Known profiles: %s", profile_name, known)
        raise ValueError(
            f"Unknown search profile '{profile_name}'. Known profiles: {known}"
        )
    return list(config)


def get_search_config() -> list[tuple[str, str, str]]:
    """Return ``(search_term, location, industry_niche)`` tuples for the active profile.

    Precedence: ``SEARCH_PROFILE`` wins over ``WORKER_NAME`` when set. An unknown
    ``SEARCH_PROFILE`` logs a warning and falls back to ``DEFAULT_SEARCH_PROFILE``.
    When ``SEARCH_PROFILE`` is unset, legacy ``WORKER_NAME`` routing is preserved.

    Returns:
        A fresh list of ``(search_term, location, industry_niche)`` tuples. The
        returned list is a defensive copy; mutating it never corrupts the shared
        ``SEARCH_PROFILES`` registry.
    """
    if SEARCH_PROFILE:
        config = SEARCH_PROFILES.get(SEARCH_PROFILE)
        if config is not None:
            return list(config)
        logger.warning(
            "Unknown SEARCH_PROFILE '%s', defaulting to '%s'",
            SEARCH_PROFILE,
            DEFAULT_SEARCH_PROFILE,
        )
        return list(SEARCH_PROFILES[DEFAULT_SEARCH_PROFILE])
    return _search_config_for_worker(WORKER_NAME)


# ---------------------------------------------------------------------------
# Multi-profile daily scout
# ---------------------------------------------------------------------------
# The daily scout runs multiple profiles sequentially in a single GitHub Action
# (NOT in parallel) so we never spawn competing scraper workflows against the
# same datacenter IP. Profiles run in the order listed here.
_DEFAULT_DAILY_SCOUT_PROFILES: tuple[str, ...] = (
    "tech_mx",
    "industrial_irapuato_bajio",
)


def _parse_daily_scout_profiles(env_value: str) -> list[str]:
    """Parse a comma-separated ``DAILY_SCOUT_PROFILES`` env string into a list.

    Empty/blank entries are dropped and surrounding whitespace is trimmed per
    entry. An all-blank (or empty) value falls back to the default profile
    order. Pure function so parsing can be tested without touching ``os.environ``.

    Args:
        env_value: Raw string from the ``DAILY_SCOUT_PROFILES`` env var.

    Returns:
        Ordered list of profile names, or ``list(_DEFAULT_DAILY_SCOUT_PROFILES)``
        when ``env_value`` has no non-blank entries.
    """
    parsed = [
        name.strip()
        for name in env_value.split(",")
        if name.strip()
    ]
    return parsed or list(_DEFAULT_DAILY_SCOUT_PROFILES)


DAILY_SCOUT_PROFILES: list[str] = _parse_daily_scout_profiles(
    os.getenv("DAILY_SCOUT_PROFILES", "").strip()
)

# Cooldown between profiles to avoid back-to-back bursts against job boards.
DEFAULT_PROFILE_COOLDOWN_SECONDS = 60
PROFILE_COOLDOWN_SECONDS = int(
    os.getenv("PROFILE_COOLDOWN_SECONDS", str(DEFAULT_PROFILE_COOLDOWN_SECONDS))
)

# Conservative per-profile results limits. The industrial Bajío niche is
# low-volume and runs on datacenter IPs, so it stays intentionally small to
# avoid rate-limiting. tech_mx inherits the global SCRAPER_CONFIG default.
INDUSTRIAL_RESULTS_LIMIT = 5

PROFILE_RESULTS_LIMITS: dict[str, int] = {
    "tech_mx": SCRAPER_CONFIG["results_limit"],
    "industrial_irapuato_bajio": INDUSTRIAL_RESULTS_LIMIT,
}


def get_profile_results_limit(profile_name: str) -> int:
    """Return the per-profile results_limit, falling back to the global default.

    Args:
        profile_name: A key in ``PROFILE_RESULTS_LIMITS`` or ``SEARCH_PROFILES``.

    Returns:
        The results limit for the profile, or ``SCRAPER_CONFIG["results_limit"]``
        when the profile has no explicit limit configured.
    """
    return PROFILE_RESULTS_LIMITS.get(profile_name, SCRAPER_CONFIG["results_limit"])


def _search_config_for_worker(worker_name: str) -> list[tuple[str, str, str]]:
    """Legacy WORKER_NAME-based routing, preserved for backward compatibility.

    Returns a fresh list each call so callers cannot mutate the shared
    ``_TECH_MX_SEARCH_CONFIG`` registry entry.
    """
    if worker_name == "GitHub_Actions":
        return list(_TECH_MX_SEARCH_CONFIG)

    elif worker_name == "Edgar":
        return [
            ("Data Engineer", "México", "Ingeniería de Datos"),
            ("Data Analyst", "México", "Ingeniería de Datos"),
            ("Analytics Engineer", "México", "Ingeniería de Datos"),
            ("Backend Developer", "México", "Ingeniería de Datos"),
        ]

    elif worker_name == "Fercho":
        return [
            ("Cloud Engineer", "México", "Infraestructura Cloud"),
            ("DevOps Engineer", "México", "Infraestructura Cloud"),
            ("Site Reliability Engineer", "México", "Infraestructura Cloud"),
            ("Arquitecto AWS", "México", "Infraestructura Cloud"),
        ]

    elif worker_name == "Alexa":
        return [
            ("Desarrollador Frontend", "México", "Desarrollo de Software"),
            ("React Developer", "México", "Desarrollo de Software"),
            ("iOS Developer", "México", "Desarrollo Móvil"),
            ("Android Developer", "México", "Desarrollo Móvil"),
        ]

    elif worker_name == "Mazuca":
        return [
            ("Desarrollador Backend", "México", "Desarrollo de Software"),
            ("Python Developer", "México", "Desarrollo de Software"),
            ("Java Backend", "México", "Desarrollo de Software"),
            ("C# Backend", "México", "Desarrollo de Software"),
        ]

    # NODO 6: Geraldine (Análisis de Negocio y Producto)
    elif worker_name == "Geraldine":
        return [
            ("Cybersecurity Engineer", "México", "Ciberseguridad"),
            ("QA Automation", "México", "Testing"),
            ("Business Intelligence", "México", "Analítica de Datos"),
            ("Product Manager", "México", "Gestión Tech"),
        ]

    else:
        logger.warning(
            "Unknown WORKER_NAME '%s', defaulting to GitHub_Actions config",
            worker_name,
        )
        return [
            ("Data Engineer", "México", "Ingeniería de Datos"),
            ("Cloud Engineer", "México", "Infraestructura Cloud"),
        ]


def get_keywords_from_config(search_config: list) -> list:
    """Extract unique search terms for use with Computrabajo/OCC scrapers."""
    return list(set(term for term, location, niche in search_config))


NEW_SCRAPERS_CONFIG = {
    "computrabajo": {
        "max_results": int(os.getenv("COMPUTRABAJO_MAX_RESULTS", "100")),
        "countries": os.getenv("COMPUTRABAJO_COUNTRIES", "MX").split(","),
        "is_remote": os.getenv("COMPUTRABAJO_REMOTE", "false").lower() == "true",
        "enabled": os.getenv("COMPUTRABAJO_ENABLED", "true").lower() == "true",
    },
    "occ": {
        "max_results": int(os.getenv("OCC_MAX_RESULTS", "100")),
        "is_remote": os.getenv("OCC_REMOTE", "false").lower() == "true",
        "enabled": os.getenv("OCC_ENABLED", "true").lower() == "true",
    },
}

ENRICHMENT_CONFIG = {
    "daily_limit": int(os.getenv("DAILY_ENRICHMENT_LIMIT", "100")),
    "batch_size": int(os.getenv("ENRICHMENT_BATCH_SIZE", "20")),
    "cooldown_seconds": int(os.getenv("ENRICHMENT_COOLDOWN", "60")),
    "circuit_breaker_threshold": 3,
    "circuit_breaker_sleep": 300,
}
