"""Idempotent skill-extraction backfill runner (Slice 3).

Reads job descriptions from the database, runs the deterministic
:class:`~src.nlp.skill_extractor.SkillExtractor`, and persists
canonical skill keys to ``skills_json``.

Key properties:

- **Idempotent**: Rerunning with the same extractor version skips
  already-processed rows (``skills_json IS NOT NULL`` with matching
  ``skill_extractor_version``).
- **Version-aware**: Rows extracted with an outdated version are
  eligible for reprocessing.  ``--force`` reprocesses all eligible
  rows regardless of version.
- **Resume-safe**: Uses ID-based keyset pagination.  Interrupting
  and rerunning continues from where it left off.
- **Per-batch transactions**: One commit per batch; a single
  failed row does not roll back the entire batch.
- **Dry-run**: ``--dry-run`` runs the full selection and extraction
  logic but performs zero writes.

Usage::

    python -m src.nlp.skill_enricher --dry-run --limit 20
    python -m src.nlp.skill_enricher --batch-size 500 --limit 5000
    python -m src.nlp.skill_enricher --force --source computrabajo

This module is NOT the online enrichment integration (Slice 4).  It is
a standalone backfill/CLI tool.
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

# Make the repo root importable.
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.database.models import Job, db_connect
from src.nlp.skill_extractor import SkillExtractor
from src.nlp.skill_taxonomy import load_taxonomy
from src.nlp.backfill_manifest import BackfillManifest
from src.data_quality import confirmed_duplicate_filter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentMetrics:
    scanned: int = 0
    eligible: int = 0
    processed: int = 0
    with_skills: int = 0
    zero_skills: int = 0
    skipped: int = 0
    skipped_confirmed_duplicates: int = 0
    failed: int = 0
    total_skills_assigned: int = 0
    skills_per_listing: list[int] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    extractor_version: str = ""

    @property
    def elapsed_sec(self) -> float:
        return self.end_time - self.start_time

    @property
    def throughput_per_sec(self) -> float:
        return self.processed / self.elapsed_sec if self.elapsed_sec > 0 else 0.0

    @property
    def mean_skills(self) -> float:
        if not self.skills_per_listing:
            return 0.0
        return sum(self.skills_per_listing) / len(self.skills_per_listing)

    @property
    def median_skills(self) -> float:
        if not self.skills_per_listing:
            return 0.0
        s = sorted(self.skills_per_listing)
        n = len(s)
        if n % 2:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2.0

    @property
    def max_skills(self) -> int:
        return max(self.skills_per_listing) if self.skills_per_listing else 0

    def summary(self) -> str:
        lines = [
            f"Extractor version: {self.extractor_version}",
            f"Scanned: {self.scanned}",
            f"Eligible: {self.eligible}",
            f"Processed: {self.processed}",
            f"  With skills: {self.with_skills}",
            f"  Zero skills: {self.zero_skills}",
            f"Skipped (already current): {self.skipped}",
            f"Skipped (confirmed duplicates): {self.skipped_confirmed_duplicates}",
            f"Failed: {self.failed}",
            f"Total skill assignments: {self.total_skills_assigned}",
            f"Mean / median / max skills: {self.mean_skills:.1f} / {self.median_skills:.0f} / {self.max_skills}",
            f"Elapsed: {self.elapsed_sec:.1f}s ({self.throughput_per_sec:.1f} listings/s)",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------


class SkillEnricher:
    """Backfill runner that extracts skills from job descriptions.

    Args:
        extractor: Pre-built :class:`SkillExtractor`.  If *None*, the
            module-level singleton is used.
        extractor_version: Taxonomy version string.  If *None*,
            read from :func:`load_taxonomy`.
        batch_size: Rows per database transaction.
    """

    def __init__(
        self,
        extractor: Optional[SkillExtractor] = None,
        extractor_version: Optional[str] = None,
        batch_size: int = 500,
    ) -> None:
        self._extractor = extractor or SkillExtractor()
        self._version = extractor_version or load_taxonomy().version
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        limit: Optional[int] = None,
        dry_run: bool = False,
        force: bool = False,
        source: Optional[str] = None,
        manifest: Optional[BackfillManifest] = None,
    ) -> EnrichmentMetrics:
        """Run the backfill over eligible job descriptions.

        Args:
            limit: Maximum rows to process (after eligibility filter).
                ``None`` means process all eligible rows.
            dry_run: If ``True``, performs zero writes.
            force: If ``True``, reprocess even rows already at the
                current extractor version.
            source: If set, only process rows from this site
                (e.g. ``"indeed"``).
        """
        metrics = EnrichmentMetrics(
            start_time=time.perf_counter(),
            extractor_version=self._version,
        )
        engine = db_connect()
        try:
            with Session(engine) as session:
                cursor: int = 0
                while True:
                    if limit is not None and metrics.processed >= limit:
                        break

                    rows = self._fetch_batch(session, cursor, source)
                    if not rows:
                        break

                    metrics.scanned += len(rows)
                    eligible = self._filter_eligible(rows, force)
                    metrics.eligible += len(eligible)
                    batch_processed: list[int] = []

                    for row in eligible:
                        if limit is not None and metrics.processed >= limit:
                            break
                        try:
                            skills = self._extractor.extract(row.cleaned_description)
                            if not dry_run:
                                self._persist(session, row, skills)
                            metrics.processed += 1
                            metrics.total_skills_assigned += len(skills)
                            metrics.skills_per_listing.append(len(skills))
                            if skills:
                                metrics.with_skills += 1
                            else:
                                metrics.zero_skills += 1
                            batch_processed.append(row.id)
                        except Exception:
                            logger.exception(
                                "Failed to process job %d; continuing", row.id
                            )
                            metrics.failed += 1

                    if not dry_run:
                        session.commit()
                        # Manifest recorded AFTER successful commit
                        if manifest is not None and batch_processed:
                            manifest.add_batch(batch_processed)

                    # Advance cursor to last row in batch
                    cursor = rows[-1].id
                    metrics.skipped += len(rows) - len(eligible)

        finally:
            # engine.dispose() deliberately skipped — in tests the
            # engine is shared via StaticPool and disposing it would
            # destroy the in-memory database.
            pass

        metrics.end_time = time.perf_counter()
        # Count confirmed duplicates excluded by query filter
        dup_count = session.query(Job).filter(
            ~confirmed_duplicate_filter(Job),
            Job.cleaned_description.isnot(None),
            Job.cleaned_description != "",
        ).count()
        metrics.skipped_confirmed_duplicates = dup_count
        if dry_run:
            logger.info("DRY RUN — no rows were modified.")
        logger.info("Backfill complete.\n%s", metrics.summary())
        return metrics

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_batch(
        self, session: Session, cursor: int, source: Optional[str]
    ) -> list[Job]:
        """Fetch one batch of rows with descriptions, ordered by id."""
        query = session.query(Job).filter(
            confirmed_duplicate_filter(Job),
            Job.cleaned_description.isnot(None),
            Job.cleaned_description != "",
            Job.id > cursor,
        )
        if source:
            query = query.filter(Job.site == source)
        return query.order_by(Job.id).limit(self.batch_size).all()

    def _filter_eligible(
        self, rows: list[Job], force: bool
    ) -> list[Job]:
        """Keep rows eligible for extraction.

        Eligibility:
        - ``skills_json IS NULL`` (never processed), OR
        - ``skill_extractor_version != current`` (outdated), OR
        - ``force=True`` (always reprocess)

        Already-current rows are skipped.
        """
        if force:
            return list(rows)

        eligible: list[Job] = []
        for row in rows:
            if row.skills_json is None:
                eligible.append(row)
            elif row.skill_extractor_version != self._version:
                eligible.append(row)
            # else: already current — skip
        return eligible

    def _persist(
        self, session: Session, job: Job, skills: list[str]
    ) -> None:
        """Write extraction result to the row.

        Uses a targeted UPDATE to avoid touching unrelated columns
        or loading managed-object state.
        """
        session.execute(
            text(
                """UPDATE jobs
                   SET skills_json = :skills,
                       skill_extractor_version = :version,
                       skills_extracted_at = :extracted_at
                   WHERE id = :id"""
            ),
            {
                "skills": _to_json(skills),
                "version": self._version,
                "extracted_at": datetime.now(timezone.utc),
                "id": job.id,
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_json(skills: list[str]) -> str:
    """Serialize a skill list as a PostgreSQL JSON array literal."""
    import json

    return json.dumps(skills, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill skills_json from cleaned_description."
    )
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--source", type=str, default=None,
                   help="Filter by site (indeed, computrabajo, occ)")
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
    manifest = None
    if args.manifest and not args.dry_run:
        manifest = BackfillManifest(
            run_type="skill_enricher",
            command=f"python -m src.nlp.skill_enricher --limit {args.limit}",
            version=load_taxonomy().version,
            limit=args.limit,
            source=args.source,
        )
    enricher = SkillEnricher(batch_size=args.batch_size)
    metrics = enricher.run(
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        source=args.source,
        manifest=manifest,
    )
    if args.dry_run:
        print("\n--- DRY RUN COMPLETE — zero rows modified ---")
    else:
        print(f"\n--- {metrics.processed} rows updated ---")
        if manifest and manifest.affected_ids:
            path = manifest.save()
            print(f"Manifest: {path} ({len(manifest.affected_ids)} IDs)")


if __name__ == "__main__":
    main()
