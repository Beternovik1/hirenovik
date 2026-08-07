"""add_job_duplicate_links

Create the ``job_duplicate_links`` table for storing confirmed duplicate
relationships between job listings.

Revision ID: c7d3e4a5f8b9
Revises: b6e2f3a4d7c9
Create Date: 2026-08-07 03:30:00.000000 UTC

Table contract
---------------

``job_duplicate_links`` stores operational deduplication metadata
separately from the raw scraped vacancy data in ``jobs``.

Each row represents one confirmed duplicate relationship:

- ``duplicate_job_id`` — the row that should NOT be counted
  independently in analytics or processed by NLP backfills.

- ``canonical_job_id`` — the row representing the canonical vacancy.

- ``scope`` — ``'same_source'`` for Computrabajo fragment duplicates
  (this slice) or ``'cross_source'`` for future cross-platform matching.

- ``method`` — the classification method (e.g.
  ``'computrabajo_canonical_url'``).

- ``confidence`` — ``1.0`` for deterministic Computrabajo URL matching;
  lower values reserved for future fuzzy cross-source methods.

- ``status`` — ``'confirmed'`` for this slice; ``'candidate'`` and
  ``'rejected'`` for future cross-source workflows.

- ``dedup_version`` — version of the deduplication logic.

- ``created_at`` — UTC timestamp when the relationship was recorded.

Invariants enforced at the application level:

- ``duplicate_job_id != canonical_job_id`` (no self-references).
- One confirmed canonical per duplicate row per scope.
- No cycles in the same-source graph (canonical must not itself be
  a duplicate in another confirmed link).

Foreign keys use ON DELETE RESTRICT: deleting a job row that is
referenced by a duplicate link is blocked. This protects the
deduplication audit trail. Links must be explicitly deleted before
their referenced jobs can be removed.

Unique constraint ``uq_duplicate_link`` on
``(duplicate_job_id, scope, status)`` prevents double-classifying
the same row under the same scope and status.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d3e4a5f8b9"
down_revision: str | None = "b6e2f3a4d7c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_duplicate_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("duplicate_job_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_job_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("dedup_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["duplicate_job_id"], ["jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_job_id"], ["jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "duplicate_job_id", "scope", "status",
            name="uq_duplicate_link",
        ),
    )
    op.create_index(
        "idx_duplicate_links_canonical",
        "job_duplicate_links",
        ["canonical_job_id", "scope"],
        unique=False,
    )
    op.create_index(
        "idx_duplicate_links_scope_status",
        "job_duplicate_links",
        ["scope", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_duplicate_links_scope_status", table_name="job_duplicate_links")
    op.drop_index("idx_duplicate_links_canonical", table_name="job_duplicate_links")
    op.drop_table("job_duplicate_links")
