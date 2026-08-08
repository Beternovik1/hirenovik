"""Existing-description preparation backfill runner (Slice 3.5).

Reads raw ``description`` from jobs, validates usability, cleans via
:class:`~src.nlp.preprocess.TextPreprocessor`, and persists to
``cleaned_description``.  No network requests — processes only
already-stored text.

Key properties:

- **Placeholder rejection**: Detects known non-description text like
  ``"Competencias añadidas por la empresa"`` and ``"Buscar es más fácil
  en la app"``.
- **Post-clean validation**: If the cleaned result is empty or trivial,
  the row is rejected and ``cleaned_description`` is left unchanged.
- **Existing-description preservation**: Non-empty ``cleaned_description``
  is never overwritten unless ``--force`` is passed.
- **Provenance**: Sets ``description_enrichment_source = 'raw_description'``
  to distinguish locally-prepared rows from detail-page-enriched rows.
- **Idempotent**: Rerunning skips already-prepared rows (those with
  non-null ``description_enrichment_source`` matching the same value).

Usage::

    python -m src.nlp.description_preparer --dry-run --limit 100
    python -m src.nlp.description_preparer --batch-size 500 --limit 5000
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.database.models import Job, db_connect
from src.nlp.preprocess import TextPreprocessor
from src.nlp.backfill_manifest import BackfillManifest
from src.data_quality import confirmed_duplicate_filter

logger = logging.getLogger(__name__)

#: Minimum raw-description length to attempt cleaning.
MIN_RAW_LENGTH = 30

#: Minimum cleaned-description length to persist.
MIN_CLEANED_LENGTH = 30

#: Known placeholder strings (exact match, case-insensitive, stripped).
_PLACEHOLDERS: frozenset[str] = frozenset({
    "competencias añadidas por la empresa",
    "buscar es más fácil en la app",
})

#: Provenance value written by this runner.
PROVENANCE_RAW = "raw_description"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def is_placeholder(raw: str) -> bool:
    """Return True if *raw* is a known placeholder.

    Matches case-insensitively after stripping whitespace.
    """
    return raw.strip().casefold() in _PLACEHOLDERS


def is_usable(raw: Optional[str], min_length: int = MIN_RAW_LENGTH) -> bool:
    """Return True if *raw* is a usable description candidate.

    Rejects None, empty, whitespace-only, too-short, and placeholder
    values.
    """
    if raw is None:
        return False
    stripped = raw.strip()
    if not stripped:
        return False
    if len(stripped) < min_length:
        return False
    if is_placeholder(stripped):
        return False
    return True


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class PreparationMetrics:
    scanned: int = 0
    eligible: int = 0
    already_prepared: int = 0
    skipped_confirmed_duplicates: int = 0
    rejected_before_clean: int = 0
    rejected_after_clean: int = 0
    prepared: int = 0
    failed: int = 0
    placeholder_count: int = 0
    raw_lengths: list[int] = field(default_factory=list)
    cleaned_lengths: list[int] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    provenance: str = PROVENANCE_RAW

    @property
    def elapsed_sec(self) -> float:
        return self.end_time - self.start_time

    @property
    def throughput_per_sec(self) -> float:
        return self.prepared / self.elapsed_sec if self.elapsed_sec > 0 else 0.0

    @property
    def mean_raw_len(self) -> float:
        return sum(self.raw_lengths) / len(self.raw_lengths) if self.raw_lengths else 0.0

    @property
    def median_raw_len(self) -> float:
        return _median(self.raw_lengths)

    @property
    def mean_cleaned_len(self) -> float:
        return sum(self.cleaned_lengths) / len(self.cleaned_lengths) if self.cleaned_lengths else 0.0

    @property
    def median_cleaned_len(self) -> float:
        return _median(self.cleaned_lengths)

    @property
    def mean_size_reduction_pct(self) -> float:
        if not self.raw_lengths or not self.cleaned_lengths:
            return 0.0
        total_raw = sum(self.raw_lengths)
        total_cleaned = sum(self.cleaned_lengths)
        if total_raw == 0:
            return 0.0
        return round((1 - total_cleaned / total_raw) * 100, 1)

    def summary(self) -> str:
        lines = [
            f"Provenance: {self.provenance}",
            f"Scanned: {self.scanned}",
            f"Eligible: {self.eligible}",
            f"Already prepared: {self.already_prepared}",
            f"Skipped (confirmed duplicates): {self.skipped_confirmed_duplicates}",
            f"Rejected (pre-clean): {self.rejected_before_clean}",
            f"  Placeholders: {self.placeholder_count}",
            f"Rejected (post-clean): {self.rejected_after_clean}",
            f"Prepared: {self.prepared}",
            f"Failed: {self.failed}",
            f"Raw length — mean / median: {self.mean_raw_len:.0f} / {self.median_raw_len:.0f}",
            f"Cleaned length — mean / median: {self.mean_cleaned_len:.0f} / {self.median_cleaned_len:.0f}",
            f"Mean size reduction: {self.mean_size_reduction_pct}%",
            f"Elapsed: {self.elapsed_sec:.1f}s ({self.throughput_per_sec:.1f} rows/s)",
        ]
        return "\n".join(lines)


def _median(vals: list[int]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ---------------------------------------------------------------------------
# Preparer
# ---------------------------------------------------------------------------


class DescriptionPreparer:
    """Backfill runner that cleans raw descriptions to cleaned_description.

    Args:
        min_raw_length: Minimum raw description length to attempt.
        min_cleaned_length: Minimum cleaned length to persist.
        batch_size: Rows per database transaction.
    """

    def __init__(
        self,
        min_raw_length: int = MIN_RAW_LENGTH,
        min_cleaned_length: int = MIN_CLEANED_LENGTH,
        batch_size: int = 500,
    ) -> None:
        self.min_raw_length = min_raw_length
        self.min_cleaned_length = min_cleaned_length
        self.batch_size = batch_size
        self._preprocessor = TextPreprocessor(
            min_description_length=min_cleaned_length,
        )

    def run(
        self,
        *,
        limit: Optional[int] = None,
        dry_run: bool = False,
        force: bool = False,
        source: Optional[str] = None,
        manifest: Optional[BackfillManifest] = None,
    ) -> PreparationMetrics:
        """Run the preparation backfill.

        Args:
            limit: Max rows to prepare (after eligibility filter).
            dry_run: If True, performs zero writes.
            force: If True, reprocess rows that already have a non-empty
                ``cleaned_description``.
            source: If set, only process rows from this site.
        """
        metrics = PreparationMetrics(start_time=time.perf_counter())
        engine = db_connect()
        try:
            with Session(engine) as session:
                cursor: int = 0
                while True:
                    if limit is not None and metrics.prepared >= limit:
                        break

                    rows = self._fetch_batch(session, cursor, source)
                    if not rows:
                        break

                    metrics.scanned += len(rows)
                    batch_prepared: list[int] = []

                    for job in rows:
                        if limit is not None and metrics.prepared >= limit:
                            break

                        raw = job.description
                        already = (
                            job.cleaned_description
                            and job.cleaned_description.strip()
                        )

                        if already and not force:
                            metrics.already_prepared += 1
                            continue

                        if not is_usable(raw, self.min_raw_length):
                            metrics.rejected_before_clean += 1
                            if raw and is_placeholder(raw):
                                metrics.placeholder_count += 1
                            continue

                        metrics.eligible += 1

                        try:
                            cleaned = self._preprocessor.clean_text(raw or "")
                        except Exception:
                            logger.exception("Clean failed for job %d", job.id)
                            metrics.failed += 1
                            continue

                        if not cleaned or len(cleaned.strip()) < self.min_cleaned_length:
                            metrics.rejected_after_clean += 1
                            continue

                        if not dry_run:
                            self._persist(session, job, cleaned)

                        metrics.prepared += 1
                        metrics.raw_lengths.append(len(raw or ""))
                        metrics.cleaned_lengths.append(len(cleaned))
                        batch_prepared.append(job.id)

                    if not dry_run:
                        try:
                            session.commit()
                            # Manifest recorded AFTER successful commit
                            if manifest is not None and batch_prepared:
                                manifest.add_batch(batch_prepared)
                        except Exception:
                            session.rollback()
                            logger.exception("Batch commit failed; rolling back")
                            metrics.failed += len(batch_prepared)
                            raise

                    cursor = rows[-1].id

        finally:
            pass  # engine.dispose() skipped — shared in tests via StaticPool

        metrics.end_time = time.perf_counter()
        # Count confirmed duplicates excluded by query filter
        dup_count = session.query(Job).filter(
            ~confirmed_duplicate_filter(Job),
            Job.description.isnot(None),
            Job.description != "",
        ).count()
        metrics.skipped_confirmed_duplicates = dup_count
        if dry_run:
            logger.info("DRY RUN — no rows were modified.")
        logger.info("Preparation complete.\n%s", metrics.summary())
        return metrics

    def _fetch_batch(
        self, session: Session, cursor: int, source: Optional[str]
    ) -> list[Job]:
        query = session.query(Job).filter(
            confirmed_duplicate_filter(Job),
            Job.description.isnot(None),
            Job.description != "",
            Job.id > cursor,
        )
        if source:
            query = query.filter(Job.site == source)
        return query.order_by(Job.id).limit(self.batch_size).all()

    def _persist(self, session: Session, job: Job, cleaned: str) -> None:
        session.execute(
            text(
                """UPDATE jobs
                   SET cleaned_description = :cleaned,
                       description_enrichment_source = :source
                   WHERE id = :id"""
            ),
            {
                "cleaned": cleaned,
                "source": PROVENANCE_RAW,
                "id": job.id,
            },
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill cleaned_description from raw descriptions (no network)."
    )
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--limit", type=int, default=None,
                   help="Max rows to prepare (after eligibility filter)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="Reprocess rows that already have cleaned_description")
    p.add_argument("--source", type=str, default=None)
    p.add_argument("--min-raw-length", type=int, default=MIN_RAW_LENGTH)
    p.add_argument("--min-cleaned-length", type=int, default=MIN_CLEANED_LENGTH)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--manifest", action="store_true",
                   help="Generate a local manifest of affected job IDs")
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    preparer = DescriptionPreparer(
        min_raw_length=args.min_raw_length,
        min_cleaned_length=args.min_cleaned_length,
        batch_size=args.batch_size,
    )
    manifest = None
    if args.manifest and not args.dry_run:
        manifest = BackfillManifest(
            run_type="description_preparer",
            command=f"python -m src.nlp.description_preparer --limit {args.limit}",
            version="1.0.0",
            limit=args.limit,
            source=args.source,
        )

    metrics = preparer.run(
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        source=args.source,
        manifest=manifest,
    )
    if args.dry_run:
        print("\n--- DRY RUN COMPLETE — zero rows modified ---")
    else:
        print(f"\n--- {metrics.prepared} rows prepared ---")
        if manifest and manifest.affected_ids:
            path = manifest.save()
            print(f"Manifest: {path} ({len(manifest.affected_ids)} IDs)")


if __name__ == "__main__":
    main()
