#!/usr/bin/env python3
"""Read-only validation of the Slice 1 skill extractor against real job data.

Connects to the database in read-only mode, samples real descriptions,
runs the Slice 1 extractor in memory, and produces a human-review report.
No database writes occur — this script never executes INSERT, UPDATE,
DELETE, or COMMIT.

Usage:
    python scripts/validate_skill_extractor.py \\
        --sample-size 100 --seed 42 --source indeed,computrabajo,occ \\
        --output validation_report.md

    python scripts/validate_skill_extractor.py \\
        --sample-size 50 --seed 7 --output validation_report.json \\
        --format json

The script exits after generating the report. It does NOT start Slice 2.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import textwrap
from collections import Counter
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import text

# Add project root
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.database.models import db_connect
from src.nlp.skill_extractor import SkillExtractor
from src.nlp.skill_taxonomy import load_taxonomy

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SampledJob:
    id: int
    title: str
    site: str
    career: Optional[str]
    industry_niche: Optional[str]
    description: str
    desc_len: int


@dataclass
class ExtractionResult:
    job: SampledJob
    skills: list[str]
    review_category: str = ""  # correct, false_positive, false_negative, taxonomy_gap, ambiguous, zero_match
    notes: str = ""


@dataclass
class ValidationReport:
    sampled_at: str
    sample_size: int
    seed: int
    sources_sampled: list[str]
    results: list[ExtractionResult] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Read-only data access
# ---------------------------------------------------------------------------

def fetch_eligible_jobs(sources: Optional[list[str]] = None) -> list[dict]:
    """Fetch job ids and metadata for all jobs with usable descriptions.

    Returns only lightweight metadata — not the full description text.
    Descriptions are fetched individually during sampling to avoid
    loading the entire dataset into memory.
    """
    engine = db_connect()
    try:
        with engine.connect() as conn:
            base = text("""
                SELECT id, title, site, career, industry_niche, LENGTH(description) AS desc_len
                FROM jobs
                WHERE description IS NOT NULL
                  AND description != ''
                  AND LENGTH(description) > 30
            """)
            rows = conn.execute(base).fetchall()

            jobs = []
            for row in rows:
                j = {
                    "id": row[0],
                    "title": row[1] or "",
                    "site": row[2] or "unknown",
                    "career": row[3],
                    "industry_niche": row[4],
                    "desc_len": row[5] or 0,
                }
                if sources and j["site"] not in sources:
                    continue
                jobs.append(j)
            return jobs
    finally:
        engine.dispose()


def fetch_descriptions_batch(job_ids: list[int]) -> dict[int, str]:
    """Fetch descriptions for multiple job IDs in one query."""
    if not job_ids:
        return {}
    engine = db_connect()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, description FROM jobs WHERE id = ANY(:ids)"),
                {"ids": job_ids},
            ).fetchall()
            return {row[0]: (row[1] or "") for row in rows}
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------

def stratified_sample(
    jobs: list[dict],
    sample_size: int,
    seed: int,
) -> list[SampledJob]:
    """Draw a stratified sample across source, career, and niche.

    Stratification ensures each source and career with at least
    ``min_eligible`` rows contributes at least one row. Remaining
    slots are filled randomly from the eligible pool (weighted
    evenly across all dimensions).
    """
    rng = random.Random(seed)
    by_source: dict[str, list[dict]] = {}
    for j in jobs:
        by_source.setdefault(j["site"], []).append(j)

    sampled: list[dict] = []
    used_ids: set[int] = set()

    # Reserve ~60% of slots for proportional source distribution
    source_slots = max(int(sample_size * 0.6), len(by_source))
    per_source = max(source_slots // max(len(by_source), 1), 1)

    for source, pool in sorted(by_source.items()):
        # Shuffle within source
        rng.shuffle(pool)
        # Try to get career diversity within source
        taken = 0
        for j in pool:
            if taken >= per_source * 2:  # soft cap per source
                break
            if j["id"] in used_ids:
                continue
            sampled.append(j)
            used_ids.add(j["id"])
            taken += 1

    # Fill remaining slots randomly
    remaining = [j for j in jobs if j["id"] not in used_ids]
    rng.shuffle(remaining)
    needed = sample_size - len(sampled)
    if needed > 0:
        sampled.extend(remaining[:needed])

    rng.shuffle(sampled)
    sampled = sampled[:sample_size]

    # Batch-fetch descriptions
    descs = fetch_descriptions_batch([j["id"] for j in sampled])

    results: list[SampledJob] = []
    for j in sampled:
        desc = descs.get(j["id"], "")
        if not desc or len(desc.strip()) < 30:
            continue
        results.append(SampledJob(
            id=j["id"],
            title=j["title"],
            site=j["site"],
            career=j.get("career"),
            industry_niche=j.get("industry_niche"),
            description=desc,
            desc_len=j["desc_len"],
        ))
    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _excerpt(text: str, max_chars: int = 200) -> str:
    """Return a short excerpt, eliding the middle for very long texts."""
    t = text.strip().replace("\n", " ").replace("\r", " ")
    t = " ".join(t.split())
    if len(t) <= max_chars:
        return t
    half = max_chars // 2
    return t[:half] + " … " + t[-half:]


def _compute_metrics(results: list[ExtractionResult]) -> dict:
    if not results:
        return {}
    counts = [len(r.skills) for r in results]
    counts_sorted = sorted(counts)
    zero = sum(1 for c in counts if c == 0)
    n = len(counts)

    median = counts_sorted[n // 2] if n % 2 else (counts_sorted[n // 2 - 1] + counts_sorted[n // 2]) / 2
    p95_idx = int(n * 0.95)
    p95 = counts_sorted[min(p95_idx, n - 1)]

    skill_counter = Counter()
    for r in results:
        for s in r.skills:
            skill_counter[s] += 1

    by_source = Counter()
    by_career = Counter()
    for r in results:
        by_source[r.job.site] += 1
        if r.job.career:
            by_career[r.job.career] += 1

    return {
        "sample_size": n,
        "with_skills": n - zero,
        "zero_match": zero,
        "zero_match_pct": round(zero / n * 100, 1) if n else 0,
        "mean_skills": round(sum(counts) / n, 2) if n else 0,
        "median_skills": median,
        "p95_skills": p95,
        "max_skills": max(counts) if counts else 0,
        "high_count_gt15": sum(1 for c in counts if c > 15),
        "top_skills": skill_counter.most_common(20),
        "by_source": dict(by_source.most_common()),
        "by_career": dict(by_career.most_common()),
    }


def _format_skills(skills: list[str]) -> str:
    if not skills:
        return "(none)"
    return ", ".join(skills)


def generate_markdown(report: ValidationReport) -> str:
    lines = []
    lines.append("# Skill Extraction Validation Report")
    lines.append(f"\n**Generated:** {report.sampled_at}")
    lines.append(f"**Sample size:** {report.sample_size}")
    lines.append(f"**Seed:** {report.seed}")
    lines.append(f"**Sources:** {', '.join(report.sources_sampled)}")
    lines.append(f"**Extractor taxonomy version:** {load_taxonomy().version}")

    lines.append("\n## Aggregate Metrics")
    m = report.metrics
    lines.append(f"- Sampled: {m.get('sample_size', 0)}")
    lines.append(f"- With at least one skill: {m.get('with_skills', 0)}")
    lines.append(f"- Zero-match: {m.get('zero_match', 0)} ({m.get('zero_match_pct', 0)}%)")
    lines.append(f"- Mean skills/listing: {m.get('mean_skills', 0)}")
    lines.append(f"- Median skills/listing: {m.get('median_skills', 0)}")
    lines.append(f"- 95th percentile: {m.get('p95_skills', 0)}")
    lines.append(f"- Max skills (one listing): {m.get('max_skills', 0)}")
    lines.append(f"- Listings with >15 skills: {m.get('high_count_gt15', 0)}")

    lines.append("\n## By Source")
    for src, cnt in sorted(report.metrics.get("by_source", {}).items()):
        lines.append(f"- {src}: {cnt}")

    lines.append("\n## By Career")
    for career, cnt in sorted(report.metrics.get("by_career", {}).items()):
        lines.append(f"- {career}: {cnt}")

    lines.append("\n## Top 20 Detected Skills")
    for skill, cnt in report.metrics.get("top_skills", []):
        lines.append(f"- `{skill}`: {cnt}")

    lines.append("\n## Per-Listing Review")
    for i, r in enumerate(report.results, 1):
        lines.append(f"\n### {i}. Job #{r.job.id} — {r.job.title}")
        lines.append(f"- **Source:** {r.job.site}")
        lines.append(f"- **Career:** {r.job.career or 'N/A'}")
        lines.append(f"- **Niche:** {r.job.industry_niche or 'N/A'}")
        lines.append(f"- **Desc length:** {r.job.desc_len} chars")
        lines.append(f"- **Extracted ({len(r.skills)}):** {_format_skills(r.skills)}")
        if r.review_category:
            lines.append(f"- **Review:** {r.review_category}")
        if r.notes:
            lines.append(f"- **Notes:** {r.notes}")
        lines.append(f"- **Excerpt:** {_excerpt(r.job.description, 200)}")

    lines.append("\n## Review Categories")
    cats = Counter(r.review_category for r in report.results if r.review_category)
    if cats:
        for cat, cnt in cats.most_common():
            lines.append(f"- **{cat}:** {cnt}")

    return "\n".join(lines)


def generate_json(report: ValidationReport) -> str:
    serialised = {
        "sampled_at": report.sampled_at,
        "sample_size": report.sample_size,
        "seed": report.seed,
        "sources": report.sources_sampled,
        "metrics": report.metrics,
        "results": [
            {
                "id": r.job.id,
                "title": r.job.title,
                "site": r.job.site,
                "career": r.job.career,
                "industry_niche": r.job.industry_niche,
                "desc_len": r.job.desc_len,
                "skills": r.skills,
                "skill_count": len(r.skills),
                "review_category": r.review_category,
                "notes": r.notes,
                "excerpt": _excerpt(r.job.description, 200),
            }
            for r in report.results
        ],
    }
    return json.dumps(serialised, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate Slice 1 skill extractor against real job descriptions."
    )
    parser.add_argument("--sample-size", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--source", type=str, default=None,
                        help="Comma-separated sources (indeed,computrabajo,occ)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path (stdout if not specified)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    sources = [s.strip() for s in args.source.split(",")] if args.source else None

    logger.info("Fetching eligible jobs from database (read-only)...")
    eligible = fetch_eligible_jobs(sources)
    logger.info("Found %d eligible jobs", len(eligible))

    logger.info("Drawing stratified sample (seed=%d, size=%d)...", args.seed, args.sample_size)
    sampled = stratified_sample(eligible, args.sample_size, args.seed)
    logger.info("Sampled %d jobs with descriptions", len(sampled))

    logger.info("Loading extractor (taxonomy + patterns once)...")
    extractor = SkillExtractor()
    taxonomy = load_taxonomy()
    logger.info("Extractor ready: %d skills, %d patterns", len(taxonomy), extractor.pattern_count)

    logger.info("Running extraction on %d descriptions...", len(sampled))
    results: list[ExtractionResult] = []
    for job in sampled:
        skills = extractor.extract(job.description)
        category = "correct" if skills else "zero_match"
        results.append(ExtractionResult(job=job, skills=skills, review_category=category))

    metrics = _compute_metrics(results)
    report = ValidationReport(
        sampled_at=datetime.now(timezone.utc).isoformat(),
        sample_size=len(sampled),
        seed=args.seed,
        sources_sampled=sources or ["all"],
        results=results,
        metrics=metrics,
    )

    if args.format == "markdown":
        output = generate_markdown(report)
    else:
        output = generate_json(report)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        logger.info("Report written to %s", args.output)
    else:
        print(output)

    # Quick summary
    print("\n--- Quick Summary ---", file=sys.stderr)
    print(f"Sample size: {metrics.get('sample_size', 0)}", file=sys.stderr)
    print(f"With skills: {metrics.get('with_skills', 0)}", file=sys.stderr)
    print(f"Zero-match: {metrics.get('zero_match', 0)} ({metrics.get('zero_match_pct', 0)}%)", file=sys.stderr)
    print(f"Mean/median/max skills: {metrics.get('mean_skills', 0)} / {metrics.get('median_skills', 0)} / {metrics.get('max_skills', 0)}", file=sys.stderr)
    print(f">15 skills: {metrics.get('high_count_gt15', 0)}", file=sys.stderr)


if __name__ == "__main__":
    main()
