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

# Industrial Bajío roles searched in the main Guanajuato industrial corridor.
# This is a starting set; scraping coverage is tunable. Strict geography is
# enforced downstream by the alert matcher, not by the search location alone.
_INDUSTRIAL_BAJIO_ROLES: tuple[str, ...] = (
    "Operador de Producción",
    "Técnico de Mantenimiento",
    "Soldador",
    "Ingeniero Industrial",
    "Inspector de Calidad",
)

_INDUSTRIAL_BAJIO_CITIES: tuple[str, ...] = (
    "Irapuato, Guanajuato",
    "León, Guanajuato",
    "Celaya, Guanajuato",
    "Salamanca, Guanajuato",
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
