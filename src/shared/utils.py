"""Shared utility helpers used across pipeline stages.

Kept dependency-free (no project imports) so any module can use these without
pulling in scrapers, database, or notifications. This is the canonical home for
cross-cutting helpers; ``scrapers.pipeline._aware_utc`` predates it and remains
a private copy until a dedicated refactor migrates that call site.
"""

from __future__ import annotations

from datetime import datetime, timezone


def aware_utc(dt: datetime | None) -> datetime:
    """Normalize a datetime to timezone-aware UTC.

    ``date_scraped`` comes from a ``DateTime(timezone=True)`` column but may
    arrive naive depending on the driver/DB. Comparing a naive ``now`` against
    an aware DB value raises ``TypeError``, so both sides are normalized to
    aware UTC before any freshness math. ``None`` (missing) maps to the epoch
    so a job with no scrape date sorts as the oldest possible (stale), which is
    the safe default for an alert digest that should not surface unknown-age
    leads first.

    Args:
        dt: A ``datetime`` (aware or naive) or ``None``.

    Returns:
        A timezone-aware UTC ``datetime``.
    """
    if dt is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
