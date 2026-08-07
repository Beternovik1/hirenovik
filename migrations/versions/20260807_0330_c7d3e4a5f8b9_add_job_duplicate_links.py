"""add_job_duplicate_links

Create the ``job_duplicate_links`` table for storing duplicate
relationships between job listings — both confirmed same-source
matches and future candidate cross-source matches.

Revision ID: c7d3e4a5f8b9
Revises: b6e2f3a4d7c9
Create Date: 2026-08-07 03:30:00.000000 UTC

Constraints
-----------

``uq_duplicate_pair`` — UNIQUE(duplicate_job_id, canonical_job_id, scope)
    Prevents inserting the exact same relationship row twice, regardless
    of status.  Renamed from uq_duplicate_link (which incorrectly placed
    ``status`` in the key, blocking multiple candidate relationships).

``ck_no_self_reference`` — CHECK(duplicate_job_id != canonical_job_id)
    A row must never point to itself.

``idx_one_confirmed`` — partial unique index
    UNIQUE(duplicate_job_id, scope) WHERE status = 'confirmed'.
    At most one confirmed canonical relationship per duplicate per scope.
    Multiple candidate relationships are explicitly allowed.

These constraints together:

- Allow:  100→200 candidate, 100→300 candidate, 100→400 candidate
  (multiple candidates for cross-source matching)
- Reject: 100→200 confirmed, 100→300 confirmed
  (only one confirmed per scope)
- Reject: 100→200 confirmed inserted twice
  (pair-level uniqueness)
- Reject: 100→100
  (self-reference)
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
        # Pair-level uniqueness: no duplicate exact relationship rows.
        sa.UniqueConstraint(
            "duplicate_job_id", "canonical_job_id", "scope",
            name="uq_duplicate_pair",
        ),
        # No self-references.
        sa.CheckConstraint(
            "duplicate_job_id != canonical_job_id",
            name="ck_no_self_reference",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_job_id"], ["jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_job_id"], ["jobs.id"],
            ondelete="RESTRICT",
        ),
    )

    # Partial unique index: at most one confirmed canonical per (dup, scope).
    # PostgreSQL only — SQLite tests use a simplified constraint.
    op.create_index(
        "idx_one_confirmed",
        "job_duplicate_links",
        ["duplicate_job_id", "scope"],
        unique=True,
        postgresql_where=sa.text("status = 'confirmed'"),
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
    op.drop_index("idx_one_confirmed", table_name="job_duplicate_links")
    op.drop_table("job_duplicate_links")
