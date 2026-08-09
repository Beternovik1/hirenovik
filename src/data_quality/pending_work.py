"""Read-only inspector for the post-enrichment pipeline backlog.

Answers questions like "how many canonical jobs are ready for description
preparation / skill extraction right now?" without performing any data
mutation.

Usage as CLI::

    python -m src.data_quality.pending_work

Programmatic::

    from src.data_quality.pending_work import PendingWorkInspector
    inspector = PendingWorkInspector()
    summary = inspector.inspect()
    print(summary.status_table())
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.data_quality import confirmed_duplicate_filter
from src.database.models import Job, JobDuplicateLink, db_connect
from src.nlp.description_preparer import unusable_description_filter

CANONICAL_SQL = text(
    """SELECT COUNT(*) FROM jobs j
       WHERE NOT EXISTS (
           SELECT 1 FROM job_duplicate_links jdl
           WHERE jdl.duplicate_job_id = j.id AND jdl.status = 'confirmed'
       )"""
)

RAW_DESC_CANONICAL_SQL = text(
    """SELECT COUNT(*) FROM jobs j
       WHERE j.description IS NOT NULL AND j.description != ''
         AND NOT EXISTS (
           SELECT 1 FROM job_duplicate_links jdl
           WHERE jdl.duplicate_job_id = j.id AND jdl.status = 'confirmed'
         )"""
)

CLEANED_CANONICAL_SQL = text(
    """SELECT COUNT(*) FROM jobs j
       WHERE j.cleaned_description IS NOT NULL AND j.cleaned_description != ''
         AND NOT EXISTS (
           SELECT 1 FROM job_duplicate_links jdl
           WHERE jdl.duplicate_job_id = j.id AND jdl.status = 'confirmed'
         )"""
)

SKILLS_CANONICAL_SQL = text(
    """SELECT COUNT(*) FROM jobs j
       WHERE j.skills_json IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM job_duplicate_links jdl
           WHERE jdl.duplicate_job_id = j.id AND jdl.status = 'confirmed'
         )"""
)


@dataclass
class PendingWorkSummary:
    """Typed snapshot of the post-enrichment pipeline backlog.

    All job counts are **canonical** (confirmed duplicates excluded) unless
    explicitly labelled as raw.
    """

    # Raw / structural
    raw_jobs: int = 0
    canonical_jobs: int = 0
    confirmed_duplicates: int = 0
    same_source_confirmed: int = 0
    cross_source_confirmed: int = 0

    # Description pipeline
    raw_description_canonical: int = 0
    cleaned_description_canonical: int = 0
    description_ready: int = 0          # usable raw desc, no cleaned_desc
    unusable_description: int = 0       # raw desc exists but is_usable rejects it

    # Skill pipeline
    skills_processed_canonical: int = 0
    skills_ready: int = 0  # has cleaned_desc, skills_json NULL

    # Derived
    nlp_complete_canonical: int = 0
    blocked_no_description: int = 0

    # Dedup (not yet measurable without a durable checkpoint)
    dedup_pending: Optional[str] = None

    # ------------------------------------------------------------------
    def status_table(self) -> str:
        """Human-readable table matching the planned CLI format."""
        dedup = (
            self.dedup_pending
            if self.dedup_pending is not None
            else "unknown"
        )
        return (
            f"Post-Enrichment Status\n"
            f"{'─' * 50}\n"
            f"Raw jobs:          {self.raw_jobs:>10,}\n"
            f"Canonical jobs:    {self.canonical_jobs:>10,}\n"
            f"Confirmed dups:    {self.confirmed_duplicates:>10,}\n"
            f"  same_source:     {self.same_source_confirmed:>10,}\n"
            f"  cross_source:    {self.cross_source_confirmed:>10,}\n"
            f"\n"
            f"Raw descriptions:  {self.raw_description_canonical:>10,}\n"
            f"Cleaned descs:     {self.cleaned_description_canonical:>10,}\n"
            f"Description-ready: {self.description_ready:>10,}\n"
            f"Unusable/placeholders:{self.unusable_description:>10,}\n"
            f"\n"
            f"Skills processed:  {self.skills_processed_canonical:>10,}\n"
            f"Skill-ready:       {self.skills_ready:>10,}\n"
            f"\n"
            f"NLP complete:      {self.nlp_complete_canonical:>10,}\n"
            f"Blocked/no desc:   {self.blocked_no_description:>10,}\n"
            f"\n"
            f"Dedup pending:     {dedup:>10}\n"
        )


class PendingWorkInspector:
    """Read-only inspector for the post-enrichment pipeline backlog.

    All queries are SELECT-only.  No data mutations are performed.
    """

    def inspect(self) -> PendingWorkSummary:
        """Query the database and return a structured summary."""
        engine = db_connect()
        try:
            with Session(engine) as session:
                return self._inspect(session)
        finally:
            engine.dispose()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _inspect(self, session: Session) -> PendingWorkSummary:
        s = PendingWorkSummary()

        # ── Structural ────────────────────────────────────────────────
        s.raw_jobs = session.query(Job).count()
        s.canonical_jobs = session.execute(CANONICAL_SQL).scalar() or 0

        dup_rows = session.query(JobDuplicateLink).filter(
            JobDuplicateLink.status == "confirmed"
        )
        s.confirmed_duplicates = dup_rows.count()
        s.same_source_confirmed = dup_rows.filter(
            JobDuplicateLink.scope == "same_source"
        ).count()
        s.cross_source_confirmed = s.confirmed_duplicates - s.same_source_confirmed

        # ── Description pipeline ──────────────────────────────────────
        s.raw_description_canonical = (
            session.execute(RAW_DESC_CANONICAL_SQL).scalar() or 0
        )
        s.cleaned_description_canonical = (
            session.execute(CLEANED_CANONICAL_SQL).scalar() or 0
        )
        s.unusable_description = (
            session.query(Job)
            .filter(
                confirmed_duplicate_filter(Job),
                Job.description.isnot(None),
                Job.description != "",
                unusable_description_filter(Job.description),
            )
            .count()
        )
        # Ready: canonical, has usable raw desc, no cleaned_desc.
        with_desc_no_cleaned = s.raw_description_canonical - s.cleaned_description_canonical
        s.description_ready = max(0, with_desc_no_cleaned - s.unusable_description)

        # ── Skill pipeline ────────────────────────────────────────────
        s.skills_processed_canonical = (
            session.execute(SKILLS_CANONICAL_SQL).scalar() or 0
        )
        # Ready: canonical, has cleaned_desc, skills_json IS NULL
        s.skills_ready = s.cleaned_description_canonical - s.skills_processed_canonical

        # ── Derived ───────────────────────────────────────────────────
        # NLP complete: has both cleaned_desc AND skills
        s.nlp_complete_canonical = min(
            s.cleaned_description_canonical, s.skills_processed_canonical
        )
        # Blocked: canonical without any raw description
        s.blocked_no_description = (
            s.canonical_jobs - s.raw_description_canonical
        )

        # ── Dedup pending ────────────────────────────────────────────
        # No durable dedup checkpoint exists on the jobs table.
        # job_duplicate_links records *results* of past dedup runs but
        # we cannot distinguish "never evaluated" from "evaluated,
        # found independent".  This will be addressed in Slice 2.
        s.dedup_pending = "checkpoint_not_available"

        return s


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    """Entry point for ``python -m src.data_quality.pending_work``."""
    inspector = PendingWorkInspector()
    summary = inspector.inspect()
    print(summary.status_table())


if __name__ == "__main__":
    main()
