"""Cross-source job duplicate matcher (Slice 4B).

Deterministic, explainable matching across job platforms: compares
canonical jobs (same-source duplicates excluded), blocks by
normalized company + title prefix, and scores each candidate pair.

Usage::

    python -m src.data_quality.cross_source_matcher --dry-run

This slice is DRY-RUN ONLY.  No relationships are persisted.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.database.models import db_connect

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_NON_ALPHA = re.compile(r"[^a-záéíóúüñ0-9\s]")
_WHITESPACE = re.compile(r"\s+")
_STAFFING_COMPANIES: frozenset[str] = frozenset({
    "ids comercial",
    "manpowergroup", "manpower group", "manpower",
    "kelly services",
    "adecco",
})


def normalize(text: Optional[str]) -> str:
    """Normalize text for comparison: NFC, lowercase, punctuation strip."""
    if not text:
        return ""
    t = unicodedata.normalize("NFC", str(text).strip().casefold())
    t = _NON_ALPHA.sub(" ", t)
    t = _WHITESPACE.sub(" ", t).strip()
    return t


def normalize_company(text: Optional[str]) -> str:
    """Normalize company name: NFC, lowercase, remove punctuation and legal suffixes."""
    t = normalize(text)
    # Remove legal suffixes more aggressively
    t = re.sub(r'\bs\.?\s*a\.?\s*(de\s*c\.?\s*v\.?)?\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\bs\s*de\s*r\s*l\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(sapi|incorporat(ed|ion)|llc|l\.?l\.?c\.?|ltd\.?|limited|corp\.?|corporation|inc\.?|gmbh|co\.?|company)\b', '', t, flags=re.IGNORECASE)
    # Remove residual single/dual letters left by suffix removal
    t = re.sub(r'\b[a-z]{1,2}\b', '', t)
    t = _WHITESPACE.sub(" ", t).strip()
    return t


def normalize_title_prefix(text: Optional[str], words: int = 3) -> str:
    """Return first N normalized title words as blocking key."""
    t = normalize(text)
    return " ".join(t.split()[:words])


def normalize_location(text: Optional[str]) -> str:
    """Normalize location for comparison."""
    return normalize(text)


def location_city(text: Optional[str]) -> str:
    """Extract first meaningful token as approximate city."""
    t = normalize_location(text)
    parts = t.split(",")[0].strip().split()
    # Remove common noise words
    noise = {"de", "la", "el", "los", "las", "del", "san", "santa"}
    meaningful = [w for w in parts if w not in noise]
    return meaningful[0] if meaningful else (parts[0] if parts else "")


def is_staffing_company(company: Optional[str]) -> bool:
    """Return True if company is a known staffing/recruiting agency."""
    norm = normalize_company(company)
    return norm in _STAFFING_COMPANIES


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_location(loc_a: str, loc_b: str) -> float:
    """Score location compatibility 0-1."""
    if not loc_a or not loc_b:
        return 0.5  # neutral when missing
    na, nb = normalize_location(loc_a), normalize_location(loc_b)
    if na == nb:
        return 1.0
    ca, cb = location_city(loc_a), location_city(loc_b)
    if ca and cb and ca == cb:
        return 0.6
    return 0.0


def token_jaccard(text_a: Optional[str], text_b: Optional[str]) -> float:
    """Token Jaccard similarity between two texts."""
    if not text_a or not text_b:
        return -1.0  # sentinel: missing data
    ta = set(normalize(text_a).split())
    tb = set(normalize(text_b).split())
    if not ta or not tb:
        return -1.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union) if union else 0.0


def _score_description(desc_a: Optional[str], desc_b: Optional[str]) -> float:
    """Score description similarity 0-1. Returns -1 if missing."""
    jac = token_jaccard(desc_a, desc_b)
    if jac < 0:
        return -1.0
    if jac >= 0.30:
        return min(1.0, jac * 2.5)  # amplify strong matches
    return jac


def _score_date(date_a, date_b) -> float:
    """Score date proximity 0-1."""
    if date_a is None or date_b is None:
        return 0.5  # neutral
    try:
        days = abs((date_a - date_b).days)
    except Exception:
        return 0.5
    if days == 0: return 1.0
    if days <= 3: return 0.9
    if days <= 7: return 0.8
    if days <= 14: return 0.6
    if days <= 30: return 0.5
    if days <= 90: return 0.2
    return 0.0


def _score_salary(sal_a: tuple, sal_b: tuple) -> float:
    """Score salary compatibility 0-1."""
    a_min, a_max = sal_a if sal_a else (None, None)
    b_min, b_max = sal_b if sal_b else (None, None)
    has_a = a_min is not None or a_max is not None
    has_b = b_min is not None or b_max is not None

    if not has_a and not has_b:
        return 0.5  # neutral — both missing
    if not has_a or not has_b:
        return 0.5  # neutral — one missing

    # Both present: check range overlap
    a_lo = a_min or a_max
    a_hi = a_max or a_min
    b_lo = b_min or b_max
    b_hi = b_max or b_min
    try:
        overlap = max(0, min(a_hi, b_hi) - max(a_lo, b_lo))
        span = max(a_hi, b_hi) - min(a_lo, b_lo)
        if span == 0:
            return 1.0 if a_lo == b_lo else 0.0
        return overlap / span
    except Exception:
        return 0.5


def compute_score(
    job_a: dict, job_b: dict, is_staffing: bool = False,
) -> dict:
    """Compute cross-source confidence score and component breakdown.

    Returns dict with keys: score, classification, components, normalized.
    """
    loc = _score_location(job_a["location"], job_b["location"])
    desc = _score_description(job_a["description"], job_b["description"])
    date = _score_date(job_a.get("date_scraped"), job_b.get("date_scraped"))
    sal = _score_salary(
        (job_a.get("salary_min"), job_a.get("salary_max")),
        (job_b.get("salary_min"), job_b.get("salary_max")),
    )

    # Weights: location 0.30, desc 0.35, date 0.20, salary 0.15
    weights = {"location": 0.30, "description": 0.35, "date": 0.20, "salary": 0.15}
    components = {"location": loc, "description": desc, "date": date, "salary": sal}

    # Handle missing descriptions: redistribute weight
    if desc < 0:
        # Description missing on one or both sides — remove from scoring,
        # redistribute weight proportionally to other components
        weights["description"] = 0.0
        remaining = 1.0 - 0.35
        for k in ("location", "date", "salary"):
            weights[k] /= remaining
        weights["location"] *= (1.0 - 0.35)
        weights["date"] = weights["date"] / (weights["location"] + weights["date"] + weights["salary"]) * (1.0 - 0.35)
        # Simpler redistribution: prorate
        total_w = weights["location"] + weights["date"] + weights["salary"]
        if total_w > 0:
            for k in ("location", "date", "salary"):
                weights[k] = weights[k] / total_w * (1.0 - 0.0)
        else:
            weights["location"] = weights["date"] = weights["salary"] = 0.33

    score = sum(weights[k] * components[k] for k in weights if components[k] >= 0)

    # Staffing-agency penalty: require higher bar
    if is_staffing:
        score = min(score, 0.84)  # can never reach HIGH

    classification = "low"
    if score >= 0.85:
        # Additional guardrails for HIGH
        if loc < 0.5:
            classification = "medium"
        elif date < 0.3:
            classification = "medium"
        else:
            classification = "high"
    elif score >= 0.50:
        classification = "medium"

    return {
        "score": round(score, 3),
        "classification": classification,
        "components": {k: round(v, 3) for k, v in components.items()},
        "normalized": {
            "company_a": normalize_company(job_a["company"]),
            "company_b": normalize_company(job_b["company"]),
            "title_a": normalize(job_a["title"]),
            "title_b": normalize(job_b["title"]),
            "location_a": normalize_location(job_a["location"]),
            "location_b": normalize_location(job_b["location"]),
        },
    }


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


@dataclass
class CrossSourceResult:
    pair: tuple[int, int]
    source_a: str
    source_b: str
    score: float
    classification: str
    components: dict
    normalized: dict


@dataclass
class CrossSourceMetrics:
    cutoff: str = ""
    canonical_by_source: dict = field(default_factory=dict)
    candidate_pairs: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    by_source_pair: dict = field(default_factory=dict)
    high_results: list[CrossSourceResult] = field(default_factory=list)
    medium_sample: list[CrossSourceResult] = field(default_factory=list)
    elapsed: float = 0.0


class CrossSourceMatcher:
    """Score cross-source candidate pairs without persisting anything."""

    def __init__(self):
        pass

    def run(self, cutoff: Optional[datetime] = None) -> CrossSourceMetrics:
        if cutoff is None:
            cutoff = datetime.now(timezone.utc)

        started = time.perf_counter()
        metrics = CrossSourceMetrics(cutoff=cutoff.isoformat())

        engine = db_connect()
        try:
            with Session(engine) as session:
                rows = session.execute(
                    text("""
                        SELECT j.id, j.site, j.title, j.company, j.raw_location,
                               j.description, j.salary_min, j.salary_max,
                               j.date_scraped
                        FROM jobs j
                        LEFT JOIN job_duplicate_links dl
                          ON j.id = dl.duplicate_job_id
                          AND dl.scope = 'same_source'
                          AND dl.status = 'confirmed'
                        WHERE j.date_scraped <= :cutoff
                          AND dl.duplicate_job_id IS NULL
                        ORDER BY j.id
                    """),
                    {"cutoff": cutoff},
                ).fetchall()

                jobs = []
                for r in rows:
                    jobs.append({
                        "id": r[0], "site": r[1], "title": r[2], "company": r[3],
                        "location": r[4], "description": r[5],
                        "salary_min": float(r[6]) if r[6] is not None else None,
                        "salary_max": float(r[7]) if r[7] is not None else None,
                        "date_scraped": r[8],
                    })

                for j in jobs:
                    metrics.canonical_by_source[j["site"]] = \
                        metrics.canonical_by_source.get(j["site"], 0) + 1

                # Block by company + title prefix
                blocks: dict[str, list[dict]] = {}
                for j in jobs:
                    nc = normalize_company(j["company"])
                    nt = normalize_title_prefix(j["title"])
                    key = f"{nc}|{nt}"
                    blocks.setdefault(key, []).append(j)

                results: list[CrossSourceResult] = []
                for key, block in blocks.items():
                    sites = set(j["site"] for j in block)
                    if len(sites) < 2:
                        continue
                    for i, a in enumerate(block):
                        for b in block[i + 1:]:
                            if a["site"] == b["site"]:
                                continue
                            metrics.candidate_pairs += 1
                            pair_key = f"{min(a['site'],b['site'])}-{max(a['site'],b['site'])}"
                            metrics.by_source_pair[pair_key] = \
                                metrics.by_source_pair.get(pair_key, 0) + 1

                            staffing = is_staffing_company(a["company"]) or \
                                       is_staffing_company(b["company"])
                            scored = compute_score(a, b, is_staffing=staffing)

                            r = CrossSourceResult(
                                pair=(a["id"], b["id"]),
                                source_a=a["site"],
                                source_b=b["site"],
                                score=scored["score"],
                                classification=scored["classification"],
                                components=scored["components"],
                                normalized=scored["normalized"],
                            )
                            results.append(r)

                results.sort(key=lambda r: -r.score)

                for r in results:
                    if r.classification == "high":
                        metrics.high_count += 1
                        if len(metrics.high_results) < 100:
                            metrics.high_results.append(r)
                    elif r.classification == "medium":
                        metrics.medium_count += 1
                        if len(metrics.medium_sample) < 30:
                            metrics.medium_sample.append(r)
                    else:
                        metrics.low_count += 1

        finally:
            engine.dispose()

        metrics.elapsed = time.perf_counter() - started
        return metrics

    def print_report(self, metrics: CrossSourceMetrics) -> None:
        print(f"\nCutoff: {metrics.cutoff}")
        print(f"Canonical jobs: {sum(metrics.canonical_by_source.values())}")
        for s, c in sorted(metrics.canonical_by_source.items()):
            print(f"  {s}: {c}")
        print(f"\nCandidate pairs: {metrics.candidate_pairs}")
        print(f"  HIGH:   {metrics.high_count}")
        print(f"  MEDIUM: {metrics.medium_count}")
        print(f"  LOW:    {metrics.low_count}")
        print(f"\nBy source pair:")
        for k, v in sorted(metrics.by_source_pair.items()):
            print(f"  {k}: {v}")
        print(f"\nElapsed: {metrics.elapsed:.1f}s")

        if metrics.high_results:
            print(f"\n=== HIGH candidates ({len(metrics.high_results)}) ===")
            for i, r in enumerate(metrics.high_results[:30]):
                print(f"\n  #{r.pair[0]} ({r.source_a}) ↔ #{r.pair[1]} ({r.source_b})")
                print(f"  Score: {r.score}  |  {r.components}")
                n = r.normalized
                print(f"  Company: {n['company_a'][:40]}  ↔  {n['company_b'][:40]}")
                print(f"  Title:   {n['title_a'][:50]}  ↔  {n['title_b'][:50]}")
                print(f"  Loc:     {n['location_a'][:30]}  ↔  {n['location_b'][:30]}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cross-source job matcher — dry run only.")
    p.add_argument("--output", type=str, default=None,
                   help="Save artifact to path")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    m = CrossSourceMatcher()
    metrics = m.run()
    m.print_report(metrics)
    print("\n--- DRY RUN COMPLETE — zero relationships created ---")

    if args.output:
        serializable = {
            "cutoff": metrics.cutoff,
            "canonical_by_source": metrics.canonical_by_source,
            "candidate_pairs": metrics.candidate_pairs,
            "high_count": metrics.high_count,
            "medium_count": metrics.medium_count,
            "low_count": metrics.low_count,
            "by_source_pair": metrics.by_source_pair,
            "high_results": [
                {
                    "pair": list(r.pair), "source_a": r.source_a,
                    "source_b": r.source_b, "score": r.score,
                    "classification": r.classification,
                    "components": r.components,
                    "normalized": r.normalized,
                }
                for r in metrics.high_results
            ],
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(serializable, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Artifact: {args.output}")


if __name__ == "__main__":
    main()
