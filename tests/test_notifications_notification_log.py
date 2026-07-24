"""Tests for notifications.notification_log: read-side sent-history lookup.

Covers the ``fix/digest-sent-history`` read side (Slice 4):

* :func:`get_sent_job_ids` queries only ``NotificationLog.job_id``, scoped by
  ``profile_name``, and returns the matching ids as a set.
* Profile scoping: a different profile's rows are NOT returned.
* Empty history for a profile yields an empty set (the fresh-install path),
  not ``None``, so callers branch with plain truthiness.

No real database is touched. A recording fake session captures the queried
column and the ``profile_name == ...`` filter expression and serves preset
rows, mirroring the fake-session pattern in
``tests/test_notifications_digest_repository.py``.
"""

from __future__ import annotations

import operator as op

from database.models import NotificationLog
from notifications.notification_log import get_sent_job_ids


class _LogQuery:
    """Chains ``.filter()`` calls, records expressions, serves preset rows."""

    def __init__(self, rows):
        self._rows = rows
        self.raw_exprs = []

    def filter(self, *exprs):
        self.raw_exprs.extend(exprs)
        return self

    def all(self):
        return list(self._rows)

    def predicates_by_column(self) -> dict:
        """Map each captured expression to ``{column_name: [(operator, value)]}``."""
        mapped: dict[str, list[tuple]] = {}
        for expr in self.raw_exprs:
            col_name = expr.left.key
            value = getattr(expr.right, "value", None)
            mapped.setdefault(col_name, []).append((expr.operator, value))
        return mapped


class _LogSession:
    """Minimal ORM session: serves preset rows and records the queried column."""

    def __init__(self, rows):
        self._rows = rows
        self.queried_columns = []
        self.last_query = None

    def query(self, column):
        self.queried_columns.append(column)
        self.last_query = _LogQuery(self._rows)
        return self.last_query


class TestGetSentJobIds:
    def test_returns_profile_scoped_job_ids(self):
        """Only the ids recorded for the queried profile are returned."""
        # session.query(NotificationLog.job_id).all() yields one-tuples.
        session = _LogSession([(101,), (102,), (103,)])

        result = get_sent_job_ids(session, "industrial_irapuato_bajio")

        assert result == {101, 102, 103}

    def test_queries_only_job_id_column(self):
        session = _LogSession([])

        get_sent_job_ids(session, "industrial_irapuato_bajio")

        # Only the job_id column is fetched, never the whole row, keeping the
        # sent-history read narrow.
        assert session.queried_columns == [NotificationLog.job_id]

    def test_filters_by_profile_name_equality(self):
        """The exclusion is profile-scoped: a profile_name == ... predicate is
        added so a different profile's rows are never returned."""
        session = _LogSession([])

        get_sent_job_ids(session, "industrial_irapuato_bajio")

        preds = session.last_query.predicates_by_column()
        assert _find_predicate(preds, "profile_name", op.eq) == "industrial_irapuato_bajio"
        assert "job_id" not in preds  # no filter on job_id, only the selection

    def test_empty_history_returns_empty_set_not_none(self):
        """Fresh-install path: no rows -> empty set (truthy-friendly, never None)."""
        session = _LogSession([])

        result = get_sent_job_ids(session, "industrial_irapuato_bajio")

        assert result == set()
        assert result is not None

    def test_single_row_returns_singleton_set(self):
        session = _LogSession([(7,)])

        result = get_sent_job_ids(session, "industrial_irapuato_bajio")

        assert result == {7}

    def test_other_profiles_rows_excluded_by_filter_scoping(self):
        """The fake session does not apply the filter (it serves preset rows),
        but this records that the query is scoped by profile_name. The
        profile-scoping guarantee is therefore enforced at the SQL layer, not in
        Python, which keeps a multi-profile install correct."""
        session = _LogSession([(101,)])

        get_sent_job_ids(session, "other_profile")

        preds = session.last_query.predicates_by_column()
        assert _find_predicate(preds, "profile_name", op.eq) == "other_profile"


def _find_predicate(pred_map, column, operator):
    """Return the bind value for the first ``column`` predicate matching ``operator``."""
    for found_op, value in pred_map.get(column, []):
        if found_op is operator:
            return value
    return None
