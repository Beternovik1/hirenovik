"""Dedup evidence fingerprinting — scope-specific, deterministic."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from src.data_quality.cross_source_matcher import (
    normalize,
    normalize_company,
    normalize_location,
)
from src.data_quality.same_source_url import canonicalize_computrabajo_url
from src.nlp.description_preparer import is_usable


def compute_evidence_hash(
    *,
    scope: str,
    job_url: Optional[str] = None,
    title: Optional[str] = None,
    company: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    salary_min: Optional[float] = None,
    salary_max: Optional[float] = None,
    date_scraped: Optional[str] = None,
) -> str:
    """Return a deterministic SHA-256 hex digest of the dedup-relevant
    evidence for *scope*.

    The fingerprint uses actual matcher semantics so that the same
    effective input produces the same hash regardless of incidental
    formatting differences.

    **same_source** (Computrabajo URL grouping):
        Two kinds of evidence matter:
        1. **Group identity** — the canonical URL (fragment stripped).
        2. **Canonical selection** — which row is chosen as canonical
           within a group.  ``select_canonical()`` uses:
           - salary presence (boolean)
           - usable-description presence (boolean)
           - date_scraped (earliest wins)
           - id (immutable deterministic tie-break, excluded)

        Changing any of these can alter the canonical choice.
        Note: same-source evaluation is group-level — a Phase 2
        enrichment of OTHER jobs sharing the same URL can change
        the canonical selection.  Per-job checkpoints are slightly
        conservative: they track THIS job's evidence, not the
        group.  The orchestrator must be group-aware and re-evaluate
        the full group when any member becomes pending.

    **cross_source** (title/company/location/description/salary/date):
        All six fields are used by the matcher for scoring and HIGH
        confidence guard decisions.  Normalization is applied where
        the matcher itself normalizes.  The hash changes if ANY of
        these fields change — causing the checkpoint to become stale.

    Returns:
        Full SHA-256 hex digest (64 characters).
    """
    if scope == "same_source":
        # Group identity: canonical URL.
        # Canonical selection evidence: does this row have salary?
        # does it have a description? when was it scraped?
        # The id field is immutable and excluded.
        has_salary = salary_min is not None or salary_max is not None
        has_desc = bool(description and is_usable(str(description)))
        payload = {
            "url": canonicalize_computrabajo_url(job_url or ""),
            "has_salary": has_salary,
            "has_usable_description": has_desc,
            "date_scraped": (date_scraped or ""),
        }

    elif scope == "cross_source":
        # All six fields affect scoring and HIGH guard decisions.
        # Apply the same normalizations the matcher uses internally.
        payload = {
            "title": normalize(title or ""),
            "company": normalize_company(company or ""),
            "location": normalize_location(location or ""),
            "description": (description or "").strip(),
            "salary_min": _serialize_salary(salary_min),
            "salary_max": _serialize_salary(salary_max),
            "date_scraped": (date_scraped or ""),
        }
    else:
        raise ValueError(f"Unknown dedup scope: {scope}")

    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _serialize_salary(value: Optional[float]) -> Optional[str]:
    """Represent salary as a deterministic string or null."""
    if value is None:
        return None
    return f"{float(value):.2f}"
