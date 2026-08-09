"""Data quality tools for the Hirenovik project."""

from sqlalchemy import and_
from sqlalchemy.sql import exists


def confirmed_duplicate_filter(job_model):
    """Return a NOT EXISTS clause excluding confirmed duplicate observations.

    Usage in a SQLAlchemy query::

        query = session.query(Job).filter(
            confirmed_duplicate_filter(Job),
            ...
        )

    A job is excluded if it appears as ``duplicate_job_id`` in
    ``job_duplicate_links`` with ``status = 'confirmed'``, regardless
    of scope (same_source or cross_source).

    Jobs appearing only as ``canonical_job_id`` remain eligible.
    Candidate and rejected relationships do NOT cause exclusion.
    """
    from src.database.models import JobDuplicateLink

    sub = exists().where(
        and_(
            JobDuplicateLink.duplicate_job_id == job_model.id,
            JobDuplicateLink.status == "confirmed",
        )
    )
    return ~sub
