"""Compile matching patterns from the skill taxonomy.

Each skill in the taxonomy declares a ``match_strategy``.  This module
compiles every alias into a pre-built regex or matcher callable once
per :class:`SkillPatternBank` instance — never per description — and
exposes the bank to the extractor.

Strategies
----------

``phrase`` (default)
    Word-boundary regex: ``\\b{escaped}\\b`` (case-insensitive).
    For aliases that are safe word-character sequences.

``symbol_aware``
    For aliases containing non-word characters (``+``, ``#``, ``.``,
    ``/``).  Uses character-class-aware boundaries:

    - Trailing ``+`` or ``#`` → ``(?<!\\w){escaped}(?!\\w)``
    - Leading ``.`` → ``(?:^|\\s)\\.net\\b`` style match
    - Slash separators → ``(?:^|\\s|\\W)ci/cd(?:$|\\s|\\W)``

``context_required``
    Not used for compilation; aliases are multi-word phrases compiled
    with ``phrase`` strategy.  Reserved for future runtime filtering.
"""

from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING

import logging

if TYPE_CHECKING:
    from src.nlp.skill_taxonomy import SkillDefinition, SkillTaxonomy

logger = logging.getLogger(__name__)

#: Regex that selects aliases containing non-word characters
#: (+, #, ., /, etc.) — these need symbol-aware boundaries.
_NON_WORD_CHARS_RE = re.compile(r"[+#./]", re.IGNORECASE)

#: Explicit character class for what counts as "not part of a tech symbol"
#: when checking boundaries for symbol_aware patterns.
_SYMBOL_NOT_BOUNDARY = re.compile(r"[\w]")


def _escape_phrase(alias: str) -> str:
    """Escape *alias* for a ``phrase``-strategy regex."""
    return re.escape(alias)


def _build_phrase_pattern(alias: str) -> re.Pattern:
    """Compile a word-boundary regex for a safe alias."""
    escaped = _escape_phrase(alias)
    return re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)


def _build_symbol_aware_pattern(alias: str) -> re.Pattern:
    """Compile a regex for an alias with non-word characters.

    Uses ``(?<!\w)`` and ``(?!\w)`` boundaries so that ``+``, ``#``,
    ``.``, ``/`` inside the alias don't break the match.
    """
    escaped = _escape_phrase(alias)
    return re.compile(r"(?<!\w)" + escaped + r"(?!\w)", re.IGNORECASE)


_BUILDERS = {
    "phrase": _build_phrase_pattern,
    "symbol_aware": _build_symbol_aware_pattern,
}


class SkillPatternBank:
    """Pre-compiled patterns for every known alias in the taxonomy.

    Each pattern is a ``(regex_pattern, canonical_key, alias_raw)``
    triple. The bank is built once and reused across all description
    scans.

    Attributes:
        patterns: Ordered list of ``(compiled_regex, canonical, raw_alias)``
            tuples.  Multiple aliases for the same canonical appear as
            separate entries — the extractor deduplicates by canonical.
        all_canonicals: Set of every canonical key in the taxonomy,
            used to validate extraction output.
    """

    def __init__(self, taxonomy: "SkillTaxonomy") -> None:
        self.patterns: list[tuple[re.Pattern, str, str]] = []
        self.all_canonicals: frozenset[str] = frozenset(
            sd.canonical for sd in taxonomy.skills
        )
        self._build(taxonomy)

    def _build(self, taxonomy: "SkillTaxonomy") -> None:
        """Compile one pattern per alias per skill."""
        compiled: list[tuple[re.Pattern, str, str]] = []
        for skill in taxonomy.skills:
            builder = _BUILDERS.get(skill.match_strategy)
            if builder is None:
                logger.warning(
                    "Skill '%s' has unknown match_strategy '%s'; "
                    "falling back to phrase",
                    skill.canonical,
                    skill.match_strategy,
                )
                builder = _build_phrase_pattern
            for alias in skill.aliases:
                try:
                    pattern = builder(alias)
                    compiled.append((pattern, skill.canonical, alias))
                except re.error as exc:
                    raise SkillPatternError(
                        f"Failed to compile pattern for '{skill.canonical}' "
                        f"alias '{alias}': {exc}"
                    ) from exc
        self.patterns = compiled
        logger.debug("Compiled %d patterns from %d skills", len(compiled), len(taxonomy))

    def match(self, text: str) -> set[str]:
        """Return every canonical key whose pattern matches *text*.

        Args:
            text: The description text to scan (already preprocessed
                as needed — this module applies no text normalisation).

        Returns:
            Set of canonical skill keys found. Never contains duplicates.
        """
        found: set[str] = set()
        for pattern, canonical, _alias in self.patterns:
            if pattern.search(text):
                found.add(canonical)
        return found


class SkillPatternError(ValueError):
    """Raised when a pattern cannot be compiled."""


def build_patterns(taxonomy: "SkillTaxonomy") -> SkillPatternBank:
    """Build the pre-compiled pattern bank from *taxonomy*.

    This is the main entry point; call it once per process.
    """
    return SkillPatternBank(taxonomy)


__all__ = [
    "SkillPatternBank",
    "SkillPatternError",
    "build_patterns",
]
