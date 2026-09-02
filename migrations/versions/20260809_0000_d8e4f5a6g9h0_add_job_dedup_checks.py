"""Add job_dedup_checks — durable dedup evaluation checkpoint.

One row per (job, scope, dedup_version) records that a job was
evaluated by smart dedup logic.  Absence means never-checked or
stale.  This solves the "checked-and-independent" problem that
``job_duplicate_links`` alone cannot represent.

Revision ID: d8e4f5a6g9h0
Revises: c7d3e4a5f8b9
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8e4f5a6g9h0"
down_revision: Union[str, None] = "c7d3e4a5f8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_dedup_checks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("dedup_version", sa.String(32), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "scope", "dedup_version",
            name="uq_dedup_check_job_scope_version",
        ),
        sa.Index(
            "idx_dedup_check_job_scope",
            "job_id", "scope",
        ),
    )


def downgrade() -> None:
    op.drop_index("idx_dedup_check_job_scope", table_name="job_dedup_checks")
    op.drop_table("job_dedup_checks")
