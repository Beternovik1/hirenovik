"""Data quality tools for the Hirenovik project."""

from sqlalchemy import and_
from sqlalchemy.sql import exists

#: Current same-source dedup logic version (Computrabajo URL grouping).
#: Increment when the canonical-selection algorithm or grouping rules
#: change in a way that would affect existing evaluations.
SAME_SOURCE_DEDUP_VERSION = "1.0.0"

#: Current cross-source dedup logic version (title/company/description
#: similarity with guard thresholds).  Independently versioned because
#: same-source and cross-source are different algorithms.
CROSS_SOURCE_DEDUP_VERSION = "1.0.0"

#: Convenience alias for backward compatibility — prefer the
#: scope-specific constants in new code.
DEDUP_VERSION = SAME_SOURCE_DEDUP_VERSION


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
