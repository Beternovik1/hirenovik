"""Alert profile abstraction for deterministic job matching and scoring.

An :class:`AlertProfile` captures a single subscriber's matching preferences:
which cities are relevant, which role keywords to include/exclude, and a cap on
how many jobs a digest should surface. This module holds no email, database, or
network logic; it only describes the matching contract.

The first hardcoded subscriber profile targets industrial roles in the Bajío
industrial corridor around Irapuato, Guanajuato, for the project owner's
brother. Geography is intentionally strict: offers outside the allowed cities
are useless to this subscriber.

Scoring is CV-informed: in addition to the binary match contract, a profile may
carry weighted :class:`RoleGroup` buckets (career-growth priority for the
subscriber's background) and weighted :class:`LocationTier` buckets, plus extra
:class:`AlertProfile.reject_keywords`. The binary matcher ignores these optional
fields; the scorer (:mod:`notifications.scoring`) reads them.
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
# "puerto interior" is an unambiguous industrial park name in Silao; it is an
# allowed city token so Tier-1 Puerto Interior listings are not lost.
INDUSTRIAL_IRAPUATO_BAJIO_CITIES: tuple[str, ...] = (
    "irapuato",
    "salamanca",
    "celaya",
    "leon",
    "silao",
    "puerto interior",
    "guanajuato",
    "apaseo",
    "villagran",
    "cortazar",
)

# Industrial role keywords. Matching is substring-based on accent-folded text,
# so phrases like "ingeniero industrial" match "Ingeniero Industrial de Planta".
# The high-value CV terms (sap, warehouse management, inventory control,
# materials, logistics, control desk, stock validation, traceability,
# discrepancy, production planning, continuous improvement, quality analyst/
# technician) are part of the relevance vocabulary, NOT hidden only in scoring
# role groups. This keeps the product contract honest: scoring ranks
# alert-matched candidates, so any job score_job accepts must also be accepted
# by match_job. Adding them here lets match_job accept English-language
# high-growth postings the subscriber's CV is built for.
INDUSTRIAL_IRAPUATO_BAJIO_INCLUDE_KEYWORDS: tuple[str, ...] = (
    # Spanish industrial trades / roles.
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
    # CV-derived high-value candidate terms (SAP / inventory / warehouse /
    # materials / logistics / quality / planning / continuous improvement).
    # Spanish forms first, then English forms for bilingual postings.
    "sap",
    "warehouse management",
    "warehouse operations",
    "warehouse",
    "inventory control",
    "inventory",
    "control de inventario",
    "validacion de stock",
    "stock validation",
    "trazabilidad",
    "traceability",
    "discrepancia",
    "discrepancy",
    "materiales",
    "materials",
    "logistics",
    "cadena de suministro",
    "control desk",
    "mesa de control",
    "despacho",
    "planeacion",
    "planeacion de la produccion",
    "production planning",
    "mejora continua",
    "continuous improvement",
    "quality analyst",
    "analista de calidad",
    "quality technician",
    "tecnico de calidad",
    "quality",
    # Role-group vocabulary parity: every keyword in role_groups that can make
    # score_job accept must also be a relevance keyword here, so match_job
    # accepts whatever the scorer ranks (score_job is not None => match_job is
    # not None). The tokens below are the role-group keywords that were NOT
    # already covered above; kept in a dedicated block for auditability.
    "inventario",
    "almacenista",
    "auxiliar de almacen",
    "analista de almacen",
    "responsable de almacen",
    "operaciones de almacen",
    "control de almacen",
    "montacarguista",
    "forklift",
    "manejador de materiales",
    "material handler",
    "analista de materiales",
    "planificacion",
    "planeador",
    "programacion de la produccion",
    "inspector de calidad",
    "kaizen",
    "lean",
    "mejora de procesos",
    "ingeniero de procesos",
    "manufactura",
    "manufacturing",
    "operaciones de manufactura",
    "operador de produccion",
    "tecnico de mantenimiento",
    "sap wm",
)

# Unambiguous internship role terms. A job whose text contains one of these is
# rejected even when its title matches an include keyword.
INDUSTRIAL_IRAPUATO_BAJIO_EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "pasante",
    "becario",
    "practicante",
)

# Extra reject terms not already covered by exclude_keywords. These catch
# unpaid/unsuitable arrangements that may not use an internship noun, e.g. a
# "Voluntario de Calidad" posting. Scoring rejects on the union of
# exclude_keywords + reject_keywords; the binary matcher rejects on
# exclude_keywords only (unchanged behavior).
INDUSTRIAL_IRAPUATO_BAJIO_REJECT_KEYWORDS: tuple[str, ...] = (
    "sin remuneracion",
    "no remunerado",
    "voluntario",
    "practicas",
    "servicio social",
)

# Default digest cap for the industrial Bajío subscriber.
INDUSTRIAL_IRAPUATO_BAJIO_MAX_JOBS = 50


# ---------------------------------------------------------------------------
# Scoring-side building blocks (optional; ignored by the binary matcher)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleGroup:
    """A weighted bucket of role keywords used by the scorer.

    Groups are evaluated in declared order (highest weight first). The first
    group whose any keyword is found in the job's searchable text wins; that
    group's ``weight`` is added to the job score. Keywords are accent-folded
    lowercase substrings, so choose them specific enough to avoid leaking into
    lower-priority groups (e.g. use ``"analista de almacen"`` rather than bare
    ``"almacen"``, which would also match ``"almacenista"``).

    Attributes:
        name: Human-readable label surfaced in match reasons.
        keywords: Accent-folded lowercase substrings.
        weight: Positive integer added to the score when this group matches.
    """

    name: str
    keywords: tuple[str, ...]
    weight: int


@dataclass(frozen=True)
class LocationTier:
    """A weighted bucket of allowed city tokens used by the scorer.

    A job's matched city token is looked up across tiers in declared order; the
    first tier containing it contributes its ``weight`` to the score. A city in
    ``AlertProfile.allowed_cities`` but in no tier scores 0 for location (still
    matched, still rankable, only lower).

    Attributes:
        name: Human-readable label surfaced in match reasons.
        cities: Accent-folded lowercase city tokens (subset of allowed_cities).
        weight: Positive integer added to the score when the matched city is in
            this tier.
    """

    name: str
    cities: tuple[str, ...]
    weight: int


# Career-growth priority buckets for the brother's CV (Industrial Engineer with
# SAP WM / inventory / warehouse / logistics / quality background). High buckets
# target roles where his experience moves him upward; the lowest bucket is
# skilled industrial trades that are valid but not his growth path. Buckets are
# declared highest weight first so the scorer's first-match-wins iteration gives
# the most favorable interpretation to a posting.
INDUSTRIAL_IRAPUATO_BAJIO_ROLE_GROUPS: tuple[RoleGroup, ...] = (
    RoleGroup(
        name="SAP / inventory / logistics / materials / control desk",
        keywords=(
            "sap wm", "sap", "warehouse management",
            "inventario", "inventarios", "control de inventario", "inventory",
            "warehouse", "operaciones de almacen", "analista de almacen",
            "responsable de almacen",
            "materiales", "analista de materiales",
            "logistica", "logistics", "cadena de suministro",
            "control desk", "mesa de control", "control de almacen", "despacho",
        ),
        weight=100,
    ),
    RoleGroup(
        name="quality / planning / continuous improvement / manufacturing",
        keywords=(
            "calidad", "quality", "inspector de calidad", "tecnico de calidad",
            "planeacion", "planificacion", "planeador",
            "programacion de la produccion",
            "mejora continua", "kaizen", "lean", "mejora de procesos",
            "manufacturing", "manufactura", "operaciones de manufactura",
            "ingeniero industrial", "ingeniero de procesos",
        ),
        weight=70,
    ),
    RoleGroup(
        name="operator / warehouse support / material handler / forklift",
        keywords=(
            "operador", "operador de produccion", "operario",
            "almacenista", "auxiliar de almacen",
            "montacargas", "forklift", "montacarguista",
            "manejador de materiales", "material handler",
        ),
        weight=40,
    ),
    RoleGroup(
        name="industrial trades (maintenance / welding / fabrication)",
        keywords=(
            "tecnico", "mantenimiento", "tecnico de mantenimiento",
            "soldador", "soldadura",
            "paileria", "herreria",
            "mecanico", "electricista",
        ),
        weight=30,
    ),
)

# Location priority tiers. Silao / Puerto Interior (Tier 1) hosts major
# manufacturing plants and is the strongest career-growth corridor. Irapuato is
# a Tier-3 valid city, not automatically the highest. Querétaro is intentionally
# absent from allowed_cities, so it is rejected at the geography gate before any
# tier lookup runs.
INDUSTRIAL_IRAPUATO_BAJIO_LOCATION_TIERS: tuple[LocationTier, ...] = (
    LocationTier(
        name="Silao / Puerto Interior",
        cities=("silao", "puerto interior"),
        weight=50,
    ),
    LocationTier(
        name="Salamanca / Celaya / Apaseo",
        cities=("salamanca", "celaya", "apaseo"),
        weight=30,
    ),
    LocationTier(
        name="Irapuato / León",
        cities=("irapuato", "leon"),
        weight=20,
    ),
    LocationTier(
        name="Guanajuato capital / Villagrán / Cortazar",
        cities=("guanajuato", "villagran", "cortazar"),
        weight=10,
    ),
)


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
        role_groups: Optional weighted role buckets for the scorer
            (:class:`RoleGroup`), ordered highest weight first. The binary
            matcher ignores this field. Defaults to empty.
        location_tiers: Optional weighted city buckets for the scorer
            (:class:`LocationTier`). The binary matcher ignores this field.
            Defaults to empty.
        reject_keywords: Optional extra accent-folded lowercase terms that the
            scorer treats as hard rejects (in addition to ``exclude_keywords``).
            The binary matcher ignores this field. Defaults to empty.
    """

    name: str
    email: str
    allowed_cities: tuple[str, ...]
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    max_jobs: int = 50
    role_groups: tuple[RoleGroup, ...] = ()
    location_tiers: tuple[LocationTier, ...] = ()
    reject_keywords: tuple[str, ...] = ()


INDUSTRIAL_IRAPUATO_BAJIO_PROFILE = AlertProfile(
    name="industrial_irapuato_bajio",
    # Email is a placeholder; populated when email sending is wired in a later
    # slice. Matching never reads this field.
    email="",
    allowed_cities=INDUSTRIAL_IRAPUATO_BAJIO_CITIES,
    include_keywords=INDUSTRIAL_IRAPUATO_BAJIO_INCLUDE_KEYWORDS,
    exclude_keywords=INDUSTRIAL_IRAPUATO_BAJIO_EXCLUDE_KEYWORDS,
    max_jobs=INDUSTRIAL_IRAPUATO_BAJIO_MAX_JOBS,
    role_groups=INDUSTRIAL_IRAPUATO_BAJIO_ROLE_GROUPS,
    location_tiers=INDUSTRIAL_IRAPUATO_BAJIO_LOCATION_TIERS,
    reject_keywords=INDUSTRIAL_IRAPUATO_BAJIO_REJECT_KEYWORDS,
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
