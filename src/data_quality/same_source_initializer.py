"""Historical same-source checkpoint initializer.

Expands missing or stale Computrabajo members to complete canonical-URL
groups, audits those groups using the current dedup logic, and reports
what checkpoints and relationship updates WOULD be written.

Usage::

    python -m src.data_quality.same_source_initializer --dry-run

Dry-run is the **only** mode currently implemented.  A future
``--write`` flag will be gated behind explicit user approval.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from src.data_quality import SAME_SOURCE_DEDUP_VERSION
from src.data_quality.dedup_checkpoint import current_evidence_hash
from src.data_quality.job_deduplicator import (
    JobDeduplicator,
    select_canonical,
    SCOPE_SAME_SOURCE,
)
from src.data_quality.same_source_planner import plan_pending_same_source_groups
from src.data_quality.same_source_url import canonicalize_computrabajo_url
from src.database.models import JobDuplicateLink, JobDedupCheck, db_connect


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class SameSourceInitMetrics:
    start_time: float = 0.0
    end_time: float = 0.0

    # Scanned
    total_computrabajo_rows: int = 0
    canonical_groups: int = 0
    singleton_groups: int = 0
    multi_row_groups: int = 0

    # Canonical evaluation
    canonical_jobs_evaluated: int = 0
    existing_confirmed_links: int = 0
    links_already_present: int = 0
    links_new: int = 0
    link_conflicts: int = 0
    groups_with_changed_canonical: int = 0

    # Checkpoint audit
    checkpoints_current: int = 0
    checkpoints_stale: int = 0
    checkpoints_missing: int = 0
    checkpoint_targets: int = 0

    # Conflict samples (job_id → canonical pairs)
    conflict_samples: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Same-Source Checkpoint Initializer — DRY RUN\n"
            f"{'─' * 55}\n"
            f"Computrabajo rows:     {self.total_computrabajo_rows:>8,}\n"
            f"Canonical URL groups:  {self.canonical_groups:>8,}\n"
            f"  Singleton:           {self.singleton_groups:>8,}\n"
            f"  Multi-row:           {self.multi_row_groups:>8,}\n"
            f"Canonical jobs eval:   {self.canonical_jobs_evaluated:>8,}\n"
            f"\n"
            f"Existing conf links:   {self.existing_confirmed_links:>8,}\n"
            f"Links already present: {self.links_already_present:>8,}\n"
            f"New links needed:      {self.links_new:>8,}\n"
            f"Link conflicts:        {self.link_conflicts:>8,}\n"
            f"Changed canonical:     {self.groups_with_changed_canonical:>8,}\n"
            f"\n"
            f"Checkpoints:\n"
            f"  Already current:     {self.checkpoints_current:>8,}\n"
            f"  Stale:               {self.checkpoints_stale:>8,}\n"
            f"  Missing:             {self.checkpoints_missing:>8,}\n"
            f"  Targets (to write):  {self.checkpoint_targets:>8,}\n"
            f"\n"
            f"Elapsed: {self.end_time - self.start_time:.1f}s\n"
        )


# ---------------------------------------------------------------------------
# Initializer
# ---------------------------------------------------------------------------


class SameSourceCheckpointInitializer:
    """Audit complete URL groups selected by the shared pending planner."""

    def run_dry(self) -> SameSourceInitMetrics:
        """Evaluate pending Computrabajo groups with SELECTs and zero mutations."""
        metrics = SameSourceInitMetrics(start_time=time.perf_counter())
        engine = db_connect()
        try:
            with Session(engine) as session:
                self._evaluate(session, metrics)
        finally:
            engine.dispose()
        metrics.end_time = time.perf_counter()
        return metrics

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evaluate(
        self, session: Session, m: SameSourceInitMetrics
    ) -> None:
        # 1. Fetch all Computrabajo rows with metadata.
        dedup = JobDeduplicator()
        rows = dedup._fetch_rows(session, source="computrabajo", limit=None)
        m.total_computrabajo_rows = len(rows)

        # 2. Expand pending members to their complete canonical-URL groups.
        pending_urls = {
            group.canonical_url
            for group in plan_pending_same_source_groups(session)
        }
        groups = [
            group
            for group in dedup._build_groups(rows)
            if group["canonical_url"] in pending_urls
        ]
        m.canonical_groups = len(groups)

        # 3. Load existing state into memory for fast lookups.
        existing_links = self._load_existing_links(session)
        existing_checkpoints = self._load_existing_checkpoints(session)

        for g in groups:
            is_singleton = len(g["rows"]) == 1
            if is_singleton:
                m.singleton_groups += 1
            else:
                m.multi_row_groups += 1

            canonical = select_canonical(g["rows"])
            m.canonical_jobs_evaluated += 1  # one canonical per group

            # ── Relationship audit ──────────────────────────────────
            # All non-canonical rows in this group are duplicates.
            for r in g["rows"]:
                if r["id"] == canonical["id"]:
                    continue
                dup_id, canon_id = r["id"], canonical["id"]
                self._audit_link(m, existing_links, dup_id, canon_id)

            # Detect changed canonical: if a previously confirmed
            # duplicate is now the canonical, that's a conflict.
            self._audit_changed_canonical(m, existing_links, g, canonical)

            # ── Checkpoint audit ────────────────────────────────────
            # Every evaluated group member gets its own checkpoint.
            # When ANY member's evidence changes (Phase 2 enrichment),
            # its checkpoint becomes stale → the full URL group is
            # scheduled for re-evaluation.
            for r in g["rows"]:
                rid = r["id"]
                m.checkpoint_targets += 1
                if rid not in existing_checkpoints:
                    m.checkpoints_missing += 1
                elif existing_checkpoints[rid] != current_evidence_hash(
                    session, rid, "same_source"
                ):
                    m.checkpoints_stale += 1
                else:
                    m.checkpoints_current += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_existing_links(
        self, session: Session
    ) -> dict[int, int]:
        """{(duplicate_job_id): canonical_job_id} for confirmed same_source."""
        rows = session.query(
            JobDuplicateLink.duplicate_job_id,
            JobDuplicateLink.canonical_job_id,
        ).filter(
            JobDuplicateLink.scope == SCOPE_SAME_SOURCE,
            JobDuplicateLink.status == "confirmed",
        ).all()
        return {dup: canon for dup, canon in rows if dup != canon}

    def _load_existing_checkpoints(
        self, session: Session
    ) -> dict[int, str]:
        """{job_id: evidence_hash} for same_source current version."""
        rows = session.query(
            JobDedupCheck.job_id,
            JobDedupCheck.evidence_hash,
        ).filter(
            JobDedupCheck.scope == "same_source",
            JobDedupCheck.dedup_version == SAME_SOURCE_DEDUP_VERSION,
        ).all()
        return {jid: h for jid, h in rows}

    def _audit_link(
        self,
        m: SameSourceInitMetrics,
        existing: dict[int, int],
        dup_id: int,
        canon_id: int,
    ) -> None:
        existing_canon = existing.get(dup_id)
        if existing_canon is None:
            m.links_new += 1
        elif existing_canon == canon_id:
            m.links_already_present += 1
        else:
            m.link_conflicts += 1
            if len(m.conflict_samples) < 5:
                m.conflict_samples.append({
                    "dup": dup_id,
                    "existing_canon": existing_canon,
                    "current_canon": canon_id,
                })
        m.existing_confirmed_links = len(existing)

    def _audit_changed_canonical(
        self,
        m: SameSourceInitMetrics,
        existing: dict[int, int],
        group: dict,
        current_canonical: dict,
    ) -> None:
        """Detect if a previously-confirmed duplicate became the new canonical."""
        canon_id = current_canonical["id"]
        if canon_id in existing:
            # This job was previously marked as a duplicate (it's in the
            # existing_links map as a dup_id).  Now it was selected as
            # canonical by the current algorithm.
            m.groups_with_changed_canonical += 1
            if len(m.conflict_samples) < 5:
                m.conflict_samples.append({
                    "group_url": canonicalize_computrabajo_url(
                        current_canonical.get("job_url", "")
                    ),
                    "new_canonical": canon_id,
                    "was_duplicate_of": existing[canon_id],
                })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    import argparse
    p = argparse.ArgumentParser(
        description="Historical same-source checkpoint initializer — dry run only."
    )
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Select-only audit (default; --write not yet implemented)")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    print("Same-Source Checkpoint Initializer\n")
    init = SameSourceCheckpointInitializer()
    metrics = init.run_dry()
    print(metrics.summary())

    if metrics.link_conflicts > 0 or metrics.groups_with_changed_canonical > 0:
        print("⚠️  LINK CONFLICTS DETECTED — see samples above.")
        print("   Do NOT write until reviewed.")
        print()
        for s in metrics.conflict_samples:
            print(f"   {s}")
    else:
        print("✅ No link conflicts — current evaluation matches existing links.")

    if metrics.checkpoint_targets > 0:
        print(f"\n{metrics.checkpoint_targets} checkpoint rows would be written by --write.")
    else:
        print("\nNo checkpoints needed — all already current.")


if __name__ == "__main__":
    main()
