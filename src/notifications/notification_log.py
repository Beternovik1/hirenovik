"""Read-side helpers for the digest notification log.

Queries :class:`database.models.NotificationLog` to support profile-scoped
exclusion of jobs already sent in a previous digest, WITHOUT writing rows
yet. The write side (recording a successful real SES send) lands in a later
slice; this module intentionally stays readonly so a read can never corrupt
the audit ledger.

The exclusion selector (see :mod:`notifications.digest_repository`) consumes
:func:`get_sent_job_ids` to drop already-sent jobs from the candidate query,
so a job is sent at most once per profile across digest runs.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from database.models import NotificationLog

logger = logging.getLogger(__name__)


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
