"""Alias-to-canonical normalizer for raw skill strings.

Given a raw skill token or alias found in text, resolve it to its
canonical form using the shared taxonomy.

Normalization steps (in order):

1.  **Unicode normalisation** — NFC form (UAX #15).
2.  **Case folding** — ``str.casefold()`` for locale-independent comparison.
3.  **Whitespace collapse** — repeated spaces → single space, trimmed.
4.  **Hyphen/slash normalisation** — ``re.sub(r'[\\-\\/]+', '_', text)``
    so ``"scikit-learn"`` and ``"scikit learn"`` both canonicalize.
5.  **Alias resolution** — direct lookup in the taxonomy's alias map.
6.  **Canonical return** — :class:`SkillDefinition` or ``None`` for unknowns.

.. warning::

    Do not strip punctuation blindly.  Symbols meaningful to technology
    names are preserved:

    - ``.`` in ``node.js``, ``.net``
    - ``+`` in ``c++``
    - ``#`` in ``c#``
    - ``/`` in ``ci/cd``

    The alias table handles these directly; the normaliser only
    collapses hyphens and slashes in *generalised* forms (e.g.
    ``"scikit-learn"`` → ``"scikit_learn"``, ``"power-bi"`` →
    ``"power_bi"``).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.nlp.skill_taxonomy import SkillDefinition, SkillTaxonomy

#: Pattern for collapsing hyphens, underscores, and slash separators that
#: are used as word joiners (not tech-significant punctuation).
_JOINER_COLLAPSE = re.compile(r"[_\-]+")

#: Aliases that MUST be passed through literally to preserve symbols.
#: These are checked *before* the joiner collapse step.
_LITERAL_ALIASES: frozenset[str] = frozenset({
    "c++", "c#", ".net", ".net framework", "dotnet",
    "node.js", "react.js", "next.js", "vue.js", "angular.js",
    "ci/cd", "pl/sql", "t-sql",
})


def _is_literal(alias: str) -> bool:
    """Return True if *alias* must skip joiner collapse."""
    return alias.casefold() in _LITERAL_ALIASES


def normalize_alias(raw: str) -> str:
    """Apply Unicode + case + whitespace normalisation to a raw string.

    This is the "quick normalise" step used when looking up aliases.
    It does NOT resolve to canonical — use :func:`resolve` for that.

    Args:
        raw: A raw string token or alias.

    Returns:
        Normalised, case-folded string suitable for alias-map lookup.
    """
    if not raw:
        return ""
    # 1. Unicode NFC
    text = unicodedata.normalize("NFC", raw.strip())
    # 2. Collapse whitespace
    text = " ".join(text.split())
    # 3. Case fold
    text = text.casefold()
    # 4. Handle literal aliases — skip joiner collapse for known symbols
    if _is_literal(text):
        return text
    # 5. Collapse hyphens/underscores where they're word joiners
    text = _JOINER_COLLAPSE.sub("_", text)
    return text


def resolve(alias: str, taxonomy: "SkillTaxonomy") -> Optional["SkillDefinition"]:
    """Resolve a raw alias to its canonical :class:`SkillDefinition`.

    Applies full normalisation then looks the result up in the
    taxonomy's alias→canonical map.

    Args:
        alias: Raw string found in text (e.g. ``"Node JS"``).
        taxonomy: The loaded :class:`SkillTaxonomy`.

    Returns:
        The matching :class:`SkillDefinition`, or ``None`` if the
        normalised form is not a known alias.
    """
    if not alias or not alias.strip():
        return None
    norm = normalize_alias(alias)
    if not norm:
        return None
    return taxonomy.resolve(norm)


__all__ = [
    "normalize_alias",
    "resolve",
]
