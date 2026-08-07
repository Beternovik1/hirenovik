"""Historical Computrabajo duplicate classification (Slice 3.7).

Identifies existing Computrabajo rows whose ``job_url`` differs only
by fragment (``#lc=ListOffers-ScoreN``), groups them by canonical URL,
selects a canonical row per group, and records confirmed duplicate
relationships in ``job_duplicate_links``.

Usage::

    python -m src.data_quality.job_deduplicator --dry-run --source computrabajo
    python -m src.data_quality.job_deduplicator --source computrabajo --limit 5000

This module performs same-source deduplication ONLY.  Cross-source
matching is a separate future slice.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.database.models import JobDuplicateLink, db_connect
from src.scrapers.computrabajo_scraper import canonicalize_computrabajo_url
from src.nlp.backfill_manifest import BackfillManifest, DEFAULT_ARTIFACTS_DIR

logger = logging.getLogger(__name__)

#: Deduplication logic version — increments when the grouping or
#: canonical-selection algorithm changes.
DEDUP_VERSION = "1.0.0"

#: Known dedup scopes.
SCOPE_SAME_SOURCE = "same_source"
SCOPE_CROSS_SOURCE = "cross_source"

#: Known methods.
METHOD_COMPUTRABAJO_URL = "computrabajo_canonical_url"

#: Known statuses.
STATUS_CONFIRMED = "confirmed"


# ---------------------------------------------------------------------------
# Canonical selection
# ---------------------------------------------------------------------------


def select_canonical(rows: list[dict]) -> dict:
    """Select the best canonical row from a duplicate group.

    Strategy (in priority order):
    1. Has ``salary_min`` or ``salary_max`` → more complete data.
    2. Has ``description`` → richer metadata.
    3. Earliest ``date_scraped`` → oldest observation.
    4. Lowest ``id`` → deterministic tie-break.

    Args:
        rows: List of row dicts with keys ``id``, ``salary_min``,
            ``salary_max``, ``description``, ``date_scraped``.

    Returns:
        The selected canonical row dict.
    """
    if len(rows) == 1:
        return rows[0]

    def score(r: dict) -> tuple:
        has_salary = 1 if (r.get("salary_min") is not None or r.get("salary_max") is not None) else 0
        has_desc = 1 if (r.get("description") and str(r["description"]).strip()) else 0
        # Earliest date → sort ascending (lower is better); None → far future
        date_val = r.get("date_scraped")
        if date_val is None:
            date_val = datetime(9999, 1, 1, tzinfo=timezone.utc)
        # We want HIGHER score for salary/desc → negate for ascending sort
        # and LOWER date → ascending sort
        return (-has_salary, -has_desc, date_val, r["id"])

    return min(rows, key=score)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class DedupMetrics:
    total_inspected: int = 0
    unique_canonical_urls: int = 0
    duplicate_groups: int = 0
    canonical_rows: int = 0
    duplicate_rows: int = 0
    groups_with_meta_diff: int = 0
    groups_with_salary_diff: int = 0
    groups_with_desc_diff: int = 0
    largest_group: int = 0
    group_sizes: list[int] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def elapsed_sec(self) -> float:
        return self.end_time - self.start_time

    @property
    def duplicate_rate(self) -> float:
        if self.total_inspected == 0:
            return 0.0
        return round(self.duplicate_rows / self.total_inspected * 100, 1)

    @property
    def median_group_size(self) -> float:
        if not self.group_sizes:
            return 0.0
        s = sorted(self.group_sizes)
        n = len(s)
        if n % 2:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    @property
    def mean_group_size(self) -> float:
        if not self.group_sizes:
            return 0.0
        return sum(self.group_sizes) / len(self.group_sizes)

    def summary(self) -> str:
        lines = [
            f"Total inspected: {self.total_inspected}",
            f"Unique canonical URLs: {self.unique_canonical_urls}",
            f"Duplicate groups: {self.duplicate_groups}",
            f"Canonical rows: {self.canonical_rows}",
            f"Duplicate rows: {self.duplicate_rows}",
            f"Duplicate rate: {self.duplicate_rate}%",
            f"Largest group: {self.largest_group}",
            f"Mean / median group size: {self.mean_group_size:.1f} / {self.median_group_size:.0f}",
            f"Groups with metadata diff: {self.groups_with_meta_diff}",
            f"Groups with salary diff: {self.groups_with_salary_diff}",
            f"Groups with desc hash diff: {self.groups_with_desc_diff}",
            f"Elapsed: {self.elapsed_sec:.1f}s",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------


class JobDeduplicator:
    """Classify historical same-source duplicate job rows.

    Args:
        batch_size: Rows fetched per pagination batch.
    """

    def __init__(self, batch_size: int = 500) -> None:
        self.batch_size = batch_size

    def run(
        self,
        *,
        source: str = "computrabajo",
        limit: Optional[int] = None,
        dry_run: bool = False,
        manifest: Optional[BackfillManifest] = None,
    ) -> DedupMetrics:
        """Run deduplication classification.

        Args:
            source: Source to deduplicate (only ``"computrabajo"``).
            limit: Max rows to inspect.
            dry_run: If True, performs zero writes.
            manifest: Optional manifest for ID tracking.
        """
        if source != "computrabajo":
            raise ValueError(f"Only 'computrabajo' source supported, got '{source}'")

        metrics = DedupMetrics(start_time=time.perf_counter())
        engine = db_connect()
        try:
            with Session(engine) as session:
                # Fetch all Computrabajo rows with their metadata
                rows = self._fetch_rows(session, source, limit)
                metrics.total_inspected = len(rows)

                if not rows:
                    metrics.end_time = time.perf_counter()
                    return metrics

                # Group by canonical URL
                groups = self._build_groups(rows)

                # Count metrics
                canonical_urls = set(g["canonical_url"] for g in groups)
                metrics.unique_canonical_urls = len(canonical_urls)
                metrics.duplicate_groups = sum(1 for g in groups if len(g["rows"]) > 1)

                for g in groups:
                    if len(g["rows"]) <= 1:
                        continue
                    metrics.canonical_rows += 1
                    dup_count = len(g["rows"]) - 1
                    metrics.duplicate_rows += dup_count
                    metrics.group_sizes.append(len(g["rows"]))
                    metrics.largest_group = max(metrics.largest_group, len(g["rows"]))

                    # Metadata differences within group
                    titles = set(r["title"] for r in g["rows"])
                    salaries = set((r.get("salary_min"), r.get("salary_max")) for r in g["rows"])
                    descs = set(r.get("description") for r in g["rows"] if r.get("description"))
                    if len(titles) > 1 or len(salaries) > 1 or len(descs) > 1:
                        metrics.groups_with_meta_diff += 1
                    if len(salaries) > 1:
                        metrics.groups_with_salary_diff += 1
                    if len(descs) > 1:
                        metrics.groups_with_desc_diff += 1

                    # Select canonical
                    canonical = select_canonical(g["rows"])
                    duplicates = [r for r in g["rows"] if r["id"] != canonical["id"]]

                    if not dry_run:
                        self._persist_links(
                            session, canonical["id"], duplicates, manifest
                        )

                if not dry_run:
                    session.commit()

        finally:
            pass  # engine.dispose() skipped — shared in tests via StaticPool

        metrics.end_time = time.perf_counter()
        if dry_run:
            logger.info("DRY RUN — no rows were modified.")
        logger.info("Dedup complete.\n%s", metrics.summary())
        return metrics

    def _fetch_rows(
        self, session: Session, source: str, limit: Optional[int]
    ) -> list[dict]:
        """Fetch rows with metadata needed for grouping and selection."""
        query = text("""
            SELECT id, job_url, title, company, raw_location,
                   salary_min, salary_max, description,
                   date_scraped
            FROM jobs
            WHERE site = :source
            ORDER BY id
        """)
        if limit is not None:
            query = text("""
                SELECT id, job_url, title, company, raw_location,
                       salary_min, salary_max, description,
                       date_scraped
                FROM jobs
                WHERE site = :source
                ORDER BY id
                LIMIT :limit
            """)
        result = session.execute(query, {"source": source, "limit": limit})
        return [dict(r._mapping) for r in result.fetchall()]

    def _build_groups(self, rows: list[dict]) -> list[dict]:
        """Group rows by canonicalized URL."""
        groups: dict[str, list[dict]] = {}
        for row in rows:
            canonical = canonicalize_computrabajo_url(row["job_url"] or "")
            if canonical not in groups:
                groups[canonical] = []
            groups[canonical].append(row)

        return [
            {"canonical_url": url, "rows": group_rows}
            for url, group_rows in sorted(groups.items())
        ]

    def _persist_links(
        self,
        session: Session,
        canonical_id: int,
        duplicates: list[dict],
        manifest: Optional[BackfillManifest],
    ) -> None:
        """Insert duplicate links for a group.

        Uses raw SQL to avoid ORM autoincrement issues across dialects.
        """
        now = datetime.now(timezone.utc)
        for dup in duplicates:
            session.execute(
                text(
                    """INSERT INTO job_duplicate_links
                       (duplicate_job_id, canonical_job_id, scope, method,
                        confidence, status, dedup_version, created_at)
                       VALUES (:dup, :canon, :scope, :method,
                               :conf, :status, :version, :ts)
                       ON CONFLICT (duplicate_job_id, canonical_job_id, scope)
                       DO UPDATE SET status = EXCLUDED.status,
                                     dedup_version = EXCLUDED.dedup_version,
                                     confidence = EXCLUDED.confidence,
                                     method = EXCLUDED.method,
                                     created_at = EXCLUDED.created_at"""
                ),
                {
                    "dup": dup["id"],
                    "canon": canonical_id,
                    "scope": SCOPE_SAME_SOURCE,
                    "method": METHOD_COMPUTRABAJO_URL,
                    "conf": 1.0,
                    "status": STATUS_CONFIRMED,
                    "version": DEDUP_VERSION,
                    "ts": now,
                },
            )
            if manifest:
                manifest.add_dedup_link(
                    dup["id"], canonical_id,
                    SCOPE_SAME_SOURCE, METHOD_COMPUTRABAJO_URL, STATUS_CONFIRMED,
                )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Classify historical Computrabajo duplicate job rows."
    )
    p.add_argument("--source", type=str, default="computrabajo")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    dedup = JobDeduplicator()
    metrics = dedup.run(
        source=args.source,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print("\n--- DRY RUN COMPLETE — zero rows modified ---")
    else:
        print(f"\n--- {metrics.duplicate_rows} duplicate links created ---")


if __name__ == "__main__":
    main()
