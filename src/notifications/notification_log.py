"""Read-side and write-side helpers for the digest notification log.

Reads :class:`database.models.NotificationLog` to support profile-scoped
exclusion of jobs already sent in a previous digest (Slice 4), and records
one audit row per job after a successful real SES send (Slice 5). The audit
ledger is never fabricated: reading is readonly and writing rejects a blank
``ses_message_id`` rather than planting a row with no real SES message id.

The exclusion selector (see :mod:`notifications.digest_repository`) consumes
:func:`get_sent_job_ids` to drop already-sent jobs from the candidate query,
so a job is sent at most once per profile across digest runs. The recorder
(:func:`record_sent_jobs`) then closes the loop by inserting the rows the
next run's exclusion will read.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database.models import NotificationLog

logger = logging.getLogger(__name__)

# Idempotence constraint on notification_log. Referenced by name (not by column
# list) so ON CONFLICT targets the existing unique key declared in the model --
# a column-list form would silently drift if the model's UniqueConstraint
# columns ever changed and this constant was not updated in lockstep.
NOTIFICATION_LOG_SEND_CONSTRAINT = "uq_notification_log_send"


def get_sent_job_ids(session: Session, profile_name: str) -> set[int]:
    """Return the set of job ids already sent for a given alert profile.

    Reads only ``NotificationLog.job_id`` rows scoped by ``profile_name`` so the
    query stays narrow and efficient (the ``idx_notification_log_profile_job``
    index covers this exact access pattern). Returns an empty set when no rows
    exist for the profile -- the common case for a fresh install -- so callers
    branch on truthiness without special-casing ``None`` or empty iterables.

    This is the profile-scoped replacement for the blanket
    ``NEW -> NOTIFIED`` status flip in ``operations.mark_jobs_as_notified``:
    instead of mutating ``Job.status`` (global, unaudited), the selector keeps
    a job ``NEW`` in the DB and simply skips it for this profile because an
    auditable row already records the send.

    Args:
        session: SQLAlchemy ORM session. Read-only use; this function does not
            commit or flush.
        profile_name: Alert profile identifier to scope the lookup to (e.g.
            ``"industrial_irapuato_bajio"``).

    Returns:
        Set of ``job_id`` values recorded for ``profile_name``. Empty when no
        rows match the profile.
    """
    rows = (
        session.query(NotificationLog.job_id)
        .filter(NotificationLog.profile_name == profile_name)
        .all()
    )
    sent = {row[0] for row in rows}
    logger.debug(
        "notification_log: %d sent job id(s) found for profile %r.",
        len(sent),
        profile_name,
    )
    return sent


def record_sent_jobs(
    session: Session,
    job_ids: Iterable[int],
    *,
    profile_name: str,
    sent_at: datetime,
    ses_message_id: str,
) -> int:
    """Persist one audit row per job for a successful real SES send.

    Inserts a :class:`NotificationLog` row for every ``job_id`` sharing the
    single caller-supplied ``sent_at`` (one digest email -> one timestamp for
    all its jobs, which is what makes the ``(job_id, profile_name, sent_at)``
    unique key an honest "one send" identifier). Insertion is idempotent via
    ``ON CONFLICT DO NOTHING`` against ``uq_notification_log_send``: re-recording
    the same send (e.g. a retried CLI run after a partial success) collides and
    is skipped rather than crashing or duplicating audit rows.

    Commit strategy: this helper commits inside, mirroring the established
    write-helper pattern in :mod:`etl.loaders.load_data`
    (``session.execute(stmt); session.commit()`` + rollback on error). The
    digest recorder is a small CLI/Lambda write path with no enclosing
    transaction manager, so committing at the write boundary keeps the caller
    simple and matches the repo's existing convention. On any DB error the
    transaction is rolled back before re-raising so the session is left clean
    for its ``close()`` in the caller's ``finally``.

    ``job_ids`` is deduplicated (order-preserving) so a duplicate id in a single
    digest can never collide with itself inside one INSERT, which keeps the
    returned count unambiguous.

    Args:
        session: SQLAlchemy ORM session used for the insert and commit.
        job_ids: Job ids to record. Empty iterables are a no-op (return 0) and
            do NOT raise -- the recorder calls this with the concatenation of
            primary and fallback ids, which is legitimately empty for a digest
            that had no jobs.
        profile_name: Alert profile identifier scoping the audit rows.
        sent_at: Digest-run timestamp shared by every row (see module note).
        ses_message_id: SES MessageId returned by the real send. Must be
            non-empty; a blank value raises rather than writing a fake audit
            row. The recorder is only reached after a non-dry-run send, so this
            should always be a real id, but the gate defends against a
            misconfigured sender that returns a blank id on success.

    Returns:
        Number of rows inserted. When the driver reports a rowcount (psycopg2
        does for ``INSERT ... ON CONFLICT``), that exact count of newly
        inserted rows is returned (rows skipped by ``ON CONFLICT DO NOTHING``
        are not counted). When the driver reports ``-1`` (unsupported
        rowcount), the number of attempted input rows is returned instead.

    Raises:
        ValueError: If ``ses_message_id`` is blank.
    """
    if not ses_message_id or not ses_message_id.strip():
        raise ValueError(
            "ses_message_id must be non-empty to record a sent job; a blank id "
            "would fabricate the audit ledger."
        )

    # Dedupe order-preserving: a duplicate id in one INSERT against
    # ON CONFLICT DO NOTHING is harmless but makes the returned count and the
    # audit ledger ambiguous.
    unique_ids = list(dict.fromkeys(job_ids))
    if not unique_ids:
        logger.debug(
            "notification_log: no job ids to record for profile %r; no-op.",
            profile_name,
        )
        return 0

    rows = [
        {
            "job_id": job_id,
            "profile_name": profile_name,
            "sent_at": sent_at,
            "ses_message_id": ses_message_id,
        }
        for job_id in unique_ids
    ]
    stmt = pg_insert(NotificationLog).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint=NOTIFICATION_LOG_SEND_CONSTRAINT)
    try:
        result = session.execute(stmt)
        session.commit()
    except Exception:
        session.rollback()
        logger.error(
            "notification_log: failed to record %d sent row(s) for profile %r; "
            "transaction rolled back.",
            len(rows),
            profile_name,
        )
        raise

    inserted = result.rowcount if result.rowcount != -1 else len(rows)
    logger.info(
        "notification_log: recorded %d/%d sent row(s) for profile %r (ses_message_id=%r).",
        inserted,
        len(rows),
        profile_name,
        ses_message_id,
    )
    return inserted
