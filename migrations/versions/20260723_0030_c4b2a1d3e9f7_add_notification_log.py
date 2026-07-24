"""add_notification_log

Create the ``notification_log`` table tracking jobs successfully sent in digest
emails, plus its idempotence unique key and query indexes.

Revision ID: c4b2a1d3e9f7
Revises: 8e1f2a3b4c5d
Create Date: 2026-07-23 00:30:00.000000 UTC

Table contract and unique-key rationale
---------------------------------------
One row per (job, alert profile, digest send). The selector implemented in a
later slice excludes jobs that already have a row for a given profile, which
replaces the blanket ``NEW -> NOTIFIED`` status flip in
``database.operations.mark_jobs_as_notified`` with a profile-scoped, auditable
history.

The natural idempotence key is ``(job_id, profile_name, sent_at)``:

* A single digest send produces ONE ``sent_at`` timestamp shared by every job
  in that email (the caller owns it, see below), so re-recording the same send
  collides on this key. The recording call uses ``ON CONFLICT DO NOTHING`` on
  this key, giving idempotence without crashing or duplicating rows.
* The "send at most once per profile" policy is enforced by the EXCLUSION
  SELECTOR (next slice), NOT by this unique key. The schema deliberately stays
  able to represent a job sent across distinct ``sent_at`` windows so the table
  remains an honest audit ledger even if a future policy change allows a job to
  re-surface; the exclusion query still catches every prior ``job_id`` for the
  profile regardless of how many windows it spans.
* We chose ``(job_id, profile_name, sent_at)`` over a tighter
  ``(job_id, profile_name)`` unique key on purpose: a ``(job_id, profile_name)``
  unique constraint would bake the "once ever" selection rule into the schema;
  keeping the window in the key decouples the audit ledger from selection
  policy, which belongs in the selector.

``sent_at`` is caller-supplied and ``NOT NULL`` with NO ``server_default``: a
row inserted without it fails fast rather than silently taking a per-row
``now()`` value that would give each job in one email a different timestamp and
defeat the idempotence key.

Recording happens ONLY after a successful real SES send
(``EmailResult.dry_run is False``). Dry-runs never write rows, so
``ses_message_id`` is always the real SES message id and is non-empty. The
column is ``NOT NULL``; an empty string would satisfy ``NOT NULL`` but the
recording gate guarantees a real id, keeping the audit trail honest.

FK on ``job_id`` uses the default ON DELETE NO ACTION (RESTRICT). There is no
job-deletion path in the project today, so RESTRICT protects auditability at no
cost; switch to CASCADE only if a future job-prune that should also prune the
log is explicitly desired.

No secrets: this migration stores no credentials, no email addresses, and no
PII -- only the job id, profile name, send timestamp, and SES message id.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4b2a1d3e9f7"
down_revision: str | None = "8e1f2a3b4c5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``notification_log`` table and its indexes.

    Transcribed from the ``NotificationLog`` model in ``src/database/models.py``
    so ``alembic revision --autogenerate`` produces an empty diff against a
    database created from this chain.
    """
    op.create_table(
        "notification_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_name", sa.String(length=100), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ses_message_id", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # RESTRICT (default NO ACTION): protect auditability -- a job row is
        # never deleted in the app today, so blocking accidental deletion from
        # wiping the log is strictly safer than CASCADE.
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.UniqueConstraint("job_id", "profile_name", "sent_at", name="uq_notification_log_send"),
    )

    op.create_index(
        "idx_notification_log_profile_job",
        "notification_log",
        ["profile_name", "job_id"],
        unique=False,
    )
    op.create_index(
        "idx_notification_log_ses_message",
        "notification_log",
        ["ses_message_id"],
        unique=False,
    )
    op.create_index(
        "idx_notification_log_profile_sent",
        "notification_log",
        ["profile_name", "sent_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ``notification_log`` table and its indexes.

    Reverses :func:`upgrade` in the inverse order objects were created.
    """
    op.drop_index("idx_notification_log_profile_sent", table_name="notification_log")
    op.drop_index("idx_notification_log_ses_message", table_name="notification_log")
    op.drop_index("idx_notification_log_profile_job", table_name="notification_log")
    op.drop_table("notification_log")
