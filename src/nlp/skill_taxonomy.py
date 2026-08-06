"""Canonical skill taxonomy loader, validator, and data model.

Reads the shared language-neutral taxonomy from
``src/shared/skill_taxonomy.json``, validates its schema and consistency,
and exposes :class:`SkillTaxonomy` as the single runtime source of truth
for all skill definitions.

The taxonomy is loaded once per process; callers obtain the singleton
via :func:`load_taxonomy`. The JSON file is the authoritative source,
consumable by both the Python extraction engine and (in a later slice)
the JavaScript frontend.

.. code-block:: python

    from src.nlp.skill_taxonomy import load_taxonomy

    taxonomy = load_taxonomy()
    skill = taxonomy.get("python")
    print(skill.canonical)   # "python"
    print(skill.display)     # "Python"
    print(skill.category)    # "programming_languages"
    print(skill.aliases)     # ["python", "py"]

Available categories (``taxonomy.categories``):

    - ``programming_languages`` — Python, Java, C++, Go, Rust, R, …
    - ``databases`` — PostgreSQL, MySQL, Snowflake, BigQuery, …
    - ``data_engineering`` — Spark, Kafka, Airflow, dbt, …
    - ``cloud`` — AWS, Azure, GCP
    - ``devops`` — Docker, Kubernetes, Terraform, CI/CD, …
    - ``frameworks`` — Django, FastAPI, React, Next.js, .NET, …
    - ``frontend`` — HTML/CSS, Tailwind, Bootstrap
    - ``ml_ai`` — TensorFlow, PyTorch, scikit-learn, LLMs, …
    - ``bi_analytics`` — Power BI, Tableau, Looker, Excel
    - ``testing`` — pytest, Selenium
    - ``enterprise_systems`` — ERP, Salesforce, ServiceNow
    - ``sap_modules`` — SAP MM, SAP SD, SAP WM, SAP ABAP, …
    - ``industrial_manufacturing`` — PLC, SCADA, Lean, CAD, IoT, …
    - ``other_tools`` — Jira, Confluence, Slack, PowerPoint, Access

.. _match-strategies:

Matching strategies
-------------------

Each skill declares a ``match_strategy`` that controls how its aliases
are compiled into regex patterns by :mod:`skill_patterns`.  Available
strategies (defined in the JSON under ``match_strategies``):

``phrase``
    Standard word-boundary matching for unambiguous word-character
    aliases.  Alias ``sql`` is compiled as ``\\bsql\\b`` (case-
    insensitive).  This is the default for most skills.

``symbol_aware``
    For aliases containing non-word characters (``+``, ``#``, ``.``,
    ``/``).  Boundaries are determined per-alias rather than with
    blanket ``\\b``.

``context_required``
    Aliases are too ambiguous to match standalone; the pattern expects
    nearby technical context words.  Currently unused directly;
    ambiguous terms like "Go", "C", and "R" use multi-word phrase
    aliases (e.g. ``"golang"``, ``"c programming"``, ``"r language"``)
    with ``phrase`` strategy instead.

Why not BERTopic / LDA / KeyBERT for skill extraction?
------------------------------------------------------
Topic models (BERTopic, LDA) discover latent themes across the
full corpus. Their topic keywords ("cloud", "aws", "infrastructure")
are statistical representations of a cluster, not evidence that any
individual listing mentions all those keywords.  Mixing topic
keywords with per-listing skill extraction would create misleading
frequency data: a listing in topic 4 would appear to request "cloud"
even when it never mentions it.

This extraction engine works at the individual listing level with
deterministic pattern matching.  Topic models may be used in future
slices for *candidate discovery* on zero-match listings — not as the
primary extraction method.

Future ``skills_json`` persistence
----------------------------------
The existing ``keywords_json`` column stores BERTopic topic metadata
(``{"topic_id": …, "topic_keywords": […]}"``).  It will NOT be reused
for per-listing skill extraction.  A later slice will add:

- ``skills_json`` — extracted canonical skill keys
- ``skill_extractor_version`` — taxonomy version at extraction time
- ``skills_extracted_at`` — timestamp

with NULL semantics (unprocessed) vs. empty array (processed, no
matches).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Joiner collapse pattern used to normalize alias keys (same as the
#: normalizer module, but inlined here to avoid circular imports).
_ALIAS_JOINER = re.compile(r"[_\-]+")

#: Aliases whose symbols must be preserved literally.
_ALIAS_LITERALS: frozenset[str] = frozenset({
    "c++", "c#", ".net", ".net framework",
    "node.js", "react.js", "next.js", "vue.js", "angular.js",
    "ci/cd", "pl/sql", "t-sql",
})


def _normalize_alias_key(raw: str) -> str:
    """Normalize an alias string for use as a lookup key.

    Must match the behaviour of :func:`normalize_alias` from the
    normalizer module without importing it (avoids circular deps).
    """
    text = raw.strip().casefold()
    if text in _ALIAS_LITERALS:
        return text
    return _ALIAS_JOINER.sub("_", text)

#: Relative path to the shared taxonomy JSON, resolved from the
#: project root (wherever ``src/`` lives).
_DEFAULT_TAXONOMY_PATH: Path = Path(__file__).parent.parent / "shared" / "skill_taxonomy.json"

#: Known valid match strategies.
_VALID_MATCH_STRATEGIES: frozenset[str] = frozenset(
    {"phrase", "symbol_aware", "context_required"}
)

#: Categories required for validation.
_REQUIRED_SKILL_FIELDS: frozenset[str] = frozenset(
    {"canonical", "display", "aliases", "category", "icon_slug", "match_strategy"}
)


@dataclass(frozen=True)
class SkillDefinition:
    """A single skill in the canonical taxonomy.

    Attributes:
        canonical: Normalised key used everywhere (e.g. ``"nodejs"``).
        display: Human-readable label (e.g. ``"Node.js"``).
        aliases: Patterns matched in job descriptions.
        category: Category key (e.g. ``"frameworks"``).
        icon_slug: simple-icons slug for the frontend, or ``None``.
        match_strategy: One of ``phrase``, ``symbol_aware``,
            ``context_required``.
    """

    canonical: str
    display: str
    aliases: tuple[str, ...]
    category: str
    icon_slug: Optional[str]
    match_strategy: str


@dataclass(frozen=True)
class SkillTaxonomy:
    """Immutable validated skill taxonomy.

    Attributes:
        version: Taxonomy version string.
        categories: Mapping of category key to display name.
        skills: Tuple of all :class:`SkillDefinition` entries.
        _by_canonical: Fast lookup dict keyed on canonical name.
        _alias_to_canonical: Mapping from every alias string to its
            owning canonical key.
    """

    version: str
    categories: dict[str, str]
    skills: tuple[SkillDefinition, ...]
    _by_canonical: dict[str, SkillDefinition] = field(repr=False)
    _alias_to_canonical: dict[str, str] = field(repr=False)

    def get(self, canonical: str) -> Optional[SkillDefinition]:
        """Return the :class:`SkillDefinition` for *canonical*, or *None*."""
        return self._by_canonical.get(canonical)

    def resolve(self, alias: str) -> Optional[SkillDefinition]:
        """Resolve a raw alias to its canonical skill, or *None*."""
        norm = _normalize_alias_key(alias)
        if not norm:
            return None
        canonical = self._alias_to_canonical.get(norm)
        if canonical is None:
            return None
        return self._by_canonical.get(canonical)

    def __len__(self) -> int:
        return len(self.skills)


# ---------------------------------------------------------------------------
# Loader / validator
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    """Read and parse the taxonomy JSON file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillTaxonomyError(
            f"Taxonomy file is not valid JSON: {path}"
        ) from exc


def _validate_schema(raw: dict, path: Path) -> None:
    """Validate top-level keys exist."""
    for key in ("version", "categories", "skills", "match_strategies"):
        if key not in raw:
            raise SkillTaxonomyError(
                f"Taxonomy {path}: missing required key '{key}'"
            )
    if not isinstance(raw["skills"], list):
        raise SkillTaxonomyError("Taxonomy 'skills' must be a list")
    if not isinstance(raw["categories"], dict):
        raise SkillTaxonomyError("Taxonomy 'categories' must be an object")


def _validate_skill_entry(entry: dict, index: int, known_categories: set[str]) -> SkillDefinition:
    """Validate one skill and return a :class:`SkillDefinition`."""
    # Required fields
    missing = _REQUIRED_SKILL_FIELDS - set(entry.keys())
    if missing:
        raise SkillTaxonomyError(
            f"Skill {index}: missing required fields: {sorted(missing)}"
        )

    canonical = entry["canonical"]
    if not isinstance(canonical, str) or not canonical.strip():
        raise SkillTaxonomyError(f"Skill {index}: 'canonical' must be a non-empty string")

    display = entry["display"]
    if not isinstance(display, str) or not display.strip():
        raise SkillTaxonomyError(f"Skill {index} ('{canonical}'): 'display' is empty")

    category = entry["category"]
    if not isinstance(category, str) or not category.strip():
        raise SkillTaxonomyError(f"Skill {index} ('{canonical}'): 'category' is empty")
    if category not in known_categories:
        raise SkillTaxonomyError(
            f"Skill {index} ('{canonical}'): unknown category '{category}'"
        )

    aliases = entry.get("aliases")
    if not isinstance(aliases, list):
        raise SkillTaxonomyError(
            f"Skill {index} ('{canonical}'): 'aliases' must be a list"
        )
    if len(aliases) == 0:
        raise SkillTaxonomyError(
            f"Skill {index} ('{canonical}'): 'aliases' must have at least one entry"
        )
    for ai, alias in enumerate(aliases):
        if not isinstance(alias, str) or not alias.strip():
            raise SkillTaxonomyError(
                f"Skill {index} ('{canonical}'): alias[{ai}] is not a non-empty string"
            )

    # Check for duplicate aliases within this skill
    seen: set[str] = set()
    for alias in aliases:
        norm = _normalize_alias_key(alias)
        if norm in seen:
            raise SkillTaxonomyError(
                f"Skill {index} ('{canonical}'): duplicate alias '{alias}'"
            )
        seen.add(norm)

    strategy = entry.get("match_strategy", "phrase")
    if strategy not in _VALID_MATCH_STRATEGIES:
        raise SkillTaxonomyError(
            f"Skill {index} ('{canonical}'): unknown match_strategy '{strategy}'"
        )

    icon = entry.get("icon_slug")
    if icon is not None and not isinstance(icon, str):
        raise SkillTaxonomyError(
            f"Skill {index} ('{canonical}'): 'icon_slug' must be a string or null"
        )

    return SkillDefinition(
        canonical=canonical.strip(),
        display=display.strip(),
        aliases=tuple(a.strip() for a in aliases),
        category=category.strip(),
        icon_slug=icon.strip() if isinstance(icon, str) else None,
        match_strategy=strategy,
    )


def _check_duplicate_canonicals(skills: list[SkillDefinition]) -> None:
    """Raise if any canonical key appears more than once."""
    seen: dict[str, int] = {}
    for i, s in enumerate(skills):
        if s.canonical in seen:
            raise SkillTaxonomyError(
                f"Duplicate canonical key '{s.canonical}' at skills[{i}] "
                f"(first seen at skills[{seen[s.canonical]}])"
            )
        seen[s.canonical] = i


def _check_conflicting_aliases(
    skills: list[SkillDefinition],
) -> dict[str, str]:
    """Build alias→canonical map; raise on unresolved conflicts.

    Two skills claiming the same alias is a conflict by default.
    Returns the alias-to-canonical mapping.
    """
    mapping: dict[str, str] = {}
    for s in skills:
        for alias in s.aliases:
            norm = _normalize_alias_key(alias)
            existing = mapping.get(norm)
            if existing is not None and existing != s.canonical:
                raise SkillTaxonomyError(
                    f"Conflicting alias '{alias}' claimed by "
                    f"'{s.canonical}' and '{existing}'"
                )
            mapping[norm] = s.canonical
    return mapping


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SkillTaxonomyError(ValueError):
    """Raised when the taxonomy JSON fails validation."""


_TAXONOMY_CACHE: Optional[SkillTaxonomy] = None


def load_taxonomy(path: Optional[Path] = None) -> SkillTaxonomy:
    """Load and validate the canonical skill taxonomy.

    Args:
        path: Override the default taxonomy path (for testing).

    Returns:
        A validated, immutable :class:`SkillTaxonomy`.

    Raises:
        SkillTaxonomyError: If the JSON is missing, malformed, or
            contains duplicate/conflicting entries.
    """
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None and path is None:
        return _TAXONOMY_CACHE

    file_path = path or _DEFAULT_TAXONOMY_PATH
    if not file_path.exists():
        raise SkillTaxonomyError(f"Taxonomy file not found: {file_path}")

    raw = _read_json(file_path)
    _validate_schema(raw, file_path)

    known_categories = set(raw["categories"].keys())
    if not known_categories:
        raise SkillTaxonomyError("Taxonomy 'categories' is empty")

    skill_defs: list[SkillDefinition] = []
    for idx, entry in enumerate(raw["skills"]):
        sd = _validate_skill_entry(entry, idx, known_categories)
        skill_defs.append(sd)

    if len(skill_defs) == 0:
        raise SkillTaxonomyError("Taxonomy 'skills' list is empty")

    _check_duplicate_canonicals(skill_defs)
    alias_map = _check_conflicting_aliases(skill_defs)

    taxonomy = SkillTaxonomy(
        version=raw["version"],
        categories=dict(raw["categories"]),
        skills=tuple(skill_defs),
        _by_canonical={sd.canonical: sd for sd in skill_defs},
        _alias_to_canonical=alias_map,
    )

    if path is None:
        _TAXONOMY_CACHE = taxonomy

    logger.info(
        "Loaded skill taxonomy v%s: %d skills across %d categories, %d aliases",
        taxonomy.version,
        len(taxonomy),
        len(taxonomy.categories),
        len(alias_map),
    )
    return taxonomy


def reset_taxonomy_cache() -> None:
    """Clear the singleton cache (useful in tests)."""
    global _TAXONOMY_CACHE
    _TAXONOMY_CACHE = None


__all__ = [
    "SkillDefinition",
    "SkillTaxonomy",
    "SkillTaxonomyError",
    "load_taxonomy",
    "reset_taxonomy_cache",
]
