"""Deterministic skill extraction engine.

The entry point for all skill extraction: feed it a job description
text and get back a sorted list of canonical skill keys.

.. code-block:: python

    from src.nlp.skill_extractor import SkillExtractor

    extractor = SkillExtractor()  # loads taxonomy, compiles patterns once
    skills = extractor.extract("Experience with Python, AWS, and Docker")
    # → ["aws", "docker", "python"]

Architecture
------------

1.  :class:`SkillExtractor` loads the taxonomy and compiles patterns
    exactly once (singleton semantics via :func:`load_taxonomy` cache).

2.  On each :meth:`extract` call:
    a.  Input sanitisation (None → return ``[]``).
    b.  Run compiled patterns against the raw text.
    c.  Deduplicate by canonical key.
    d.  Sort alphabetically by canonical key.
    e.  Return the list.

No database, no network, no NLP model inference.
No inference from topic membership.
No hierarchical parent-skill inference.

Future slices
-------------
Later slices will add:

- ``skills_json`` column persistence in the jobs table.
- Batch backfill over existing ``cleaned_description``.
- Pipeline integration in the ETL enrichment step.
- KeyBERT candidate discovery for zero-match listings.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.nlp.skill_taxonomy import load_taxonomy, SkillTaxonomy
from src.nlp.skill_patterns import build_patterns, SkillPatternBank

logger = logging.getLogger(__name__)


class SkillExtractor:
    """Deterministic skill extraction from job description text.

    Loads the taxonomy and compiles regex patterns once on construction
    (or on first call via the singleton-returning :func:`get_extractor`).

    The extractor is stateless beyond the compiled patterns — it can be
    reused concurrently across descriptions.

    Args:
        taxonomy: Optional pre-loaded taxonomy. If ``None``, calls
            :func:`load_taxonomy` (uses the shared JSON file).
    """

    def __init__(self, taxonomy: Optional[SkillTaxonomy] = None) -> None:
        self._taxonomy = taxonomy or load_taxonomy()
        self._patterns: SkillPatternBank = build_patterns(self._taxonomy)
        logger.info(
            "SkillExtractor ready: %d skills, %d compiled patterns",
            len(self._taxonomy),
            len(self._patterns.patterns),
        )

    def extract(self, text: Optional[str]) -> list[str]:
        """Extract canonical skill keys from *text*.

        Args:
            text: A job description string, or ``None``.

        Returns:
            Deterministically sorted list of canonical skill keys.
            Never ``None`` — returns ``[]`` for null, empty, or
            whitespace-only input.  Each canonical appears at most once.

        Raises:
            TypeError: If *text* is not a string and not ``None``.
        """
        # Sanitise input
        if text is None:
            return []
        if not isinstance(text, str):
            raise TypeError(
                f"SkillExtractor.extract expects str or None, got {type(text).__name__}"
            )
        if not text.strip():
            return []

        # Match patterns
        found: set[str] = self._patterns.match(text)

        # Sort alphabetically by canonical key (deterministic, stable)
        return sorted(found)

    @property
    def taxonomy(self) -> SkillTaxonomy:
        """The loaded :class:`SkillTaxonomy`."""
        return self._taxonomy

    @property
    def pattern_count(self) -> int:
        """Number of compiled regex patterns."""
        return len(self._patterns.patterns)


# ---------------------------------------------------------------------------
# Module-level singleton (lazy, pattern-safe)
# ---------------------------------------------------------------------------

_EXTRACTOR: Optional[SkillExtractor] = None


def get_extractor() -> SkillExtractor:
    """Return a module-level singleton :class:`SkillExtractor`.

    Taxonomy is loaded and patterns are compiled exactly once per
    process. Thread-safe to call from multiple request handlers.
    """
    global _EXTRACTOR
    if _EXTRACTOR is None:
        _EXTRACTOR = SkillExtractor()
    return _EXTRACTOR


def reset_extractor() -> None:
    """Clear the singleton (useful in tests that monkey-patch the taxonomy)."""
    global _EXTRACTOR
    _EXTRACTOR = None


__all__ = [
    "SkillExtractor",
    "get_extractor",
    "reset_extractor",
]
