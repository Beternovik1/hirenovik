"""Alert profile abstraction for deterministic job matching.

An :class:`AlertProfile` captures a single subscriber's matching preferences:
which cities are relevant, which role keywords to include/exclude, and a cap on
how many jobs a digest should surface. This module holds no email, database, or
network logic; it only describes the matching contract.

The first hardcoded subscriber profile targets industrial roles in the Bajío
industrial corridor around Irapuato, Guanajuato, for the project owner's
brother. Geography is intentionally strict: offers outside the allowed cities
are useless to this subscriber.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Industrial Bajío subscriber (Irapuato region, Guanajuato)
# ---------------------------------------------------------------------------
# City tokens are accent-folded and lowercased so the matcher can compare them
# against accent-folded location text. The matcher anchors each token at the
# start of the city part (before the first comma) with a word boundary, so
# "guanajuato" matches the capital city but a bare state mention does not, and
# "leon" matches "León, Guanajuato" but NOT "Nuevo León" (a different state).
INDUSTRIAL_IRAPUATO_BAJIO_CITIES: tuple[str, ...] = (
    "irapuato",
    "salamanca",
    "celaya",
    "leon",
    "silao",
    "guanajuato",
    "apaseo",
    "villagran",
    "cortazar",
)

# Industrial role keywords. Matching is substring-based on accent-folded text,
# so phrases like "ingeniero industrial" match "Ingeniero Industrial de Planta".
INDUSTRIAL_IRAPUATO_BAJIO_INCLUDE_KEYWORDS: tuple[str, ...] = (
    "operador",
    "tecnico",
    "mantenimiento",
    "soldador",
    "soldadura",
    "ingeniero industrial",
    "mecanico",
    "electricista",
    "almacen",
    "inventarios",
    "logistica",
    "produccion",
    "calidad",
    "montacargas",
    "paileria",
    "herreria",
    "operario",
)

# Unambiguous internship role terms. A job whose text contains one of these is
# rejected even when its title matches an include keyword.
INDUSTRIAL_IRAPUATO_BAJIO_EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "pasante",
    "becario",
    "practicante",
)

# Default digest cap for the industrial Bajío subscriber.
INDUSTRIAL_IRAPUATO_BAJIO_MAX_JOBS = 50


@dataclass(frozen=True)
class AlertProfile:
    """A subscriber's deterministic job-matching preferences.

    Attributes:
        name: Stable identifier for the profile (matches a SEARCH_PROFILE name
            when the discovery and subscriber scopes align).
        email: Subscriber contact. Empty placeholder until email sending is
            wired; never used for matching.
        allowed_cities: Accent-folded lowercase city tokens. A job matches only
            if its city part contains one of these.
        include_keywords: Accent-folded lowercase keywords. At least one must
            appear in the job's searchable text for a match.
        exclude_keywords: Accent-folded lowercase keywords. If any appears, the
            job is rejected regardless of include matches.
        max_jobs: Upper bound on the number of matched jobs returned per digest.
    """

    name: str
    email: str
    allowed_cities: tuple[str, ...]
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    max_jobs: int = 50


INDUSTRIAL_IRAPUATO_BAJIO_PROFILE = AlertProfile(
    name="industrial_irapuato_bajio",
    # Email is a placeholder; populated when email sending is wired in a later
    # slice. Matching never reads this field.
    email="",
    allowed_cities=INDUSTRIAL_IRAPUATO_BAJIO_CITIES,
    include_keywords=INDUSTRIAL_IRAPUATO_BAJIO_INCLUDE_KEYWORDS,
    exclude_keywords=INDUSTRIAL_IRAPUATO_BAJIO_EXCLUDE_KEYWORDS,
    max_jobs=INDUSTRIAL_IRAPUATO_BAJIO_MAX_JOBS,
)

ALERT_PROFILES: dict[str, AlertProfile] = {
    "industrial_irapuato_bajio": INDUSTRIAL_IRAPUATO_BAJIO_PROFILE,
}


def get_alert_profile(name: str) -> AlertProfile | None:
    """Return the alert profile registered under ``name``, or ``None`` if absent.

    Args:
        name: Profile identifier (e.g. ``"industrial_irapuato_bajio"``).

    Returns:
        The matching :class:`AlertProfile`, or ``None`` when the name is unknown.
    """
    return ALERT_PROFILES.get(name)
