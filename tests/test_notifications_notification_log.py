"""Tests for notifications.notification_log: read-side and write-side helpers.

Covers the ``fix/digest-sent-history`` read side (Slice 4) and write side
(Slice 5):

Read (Slice 4):

* :func:`get_sent_job_ids` queries only ``NotificationLog.job_id``, scoped by
  ``profile_name``, and returns the matching ids as a set.
* Profile scoping: a different profile's rows are NOT returned.
* Empty history for a profile yields an empty set (the fresh-install path),
  not ``None``, so callers branch with plain truthiness.

Write (Slice 5):

* :func:`record_sent_jobs` is a no-op (returns 0) on empty ``job_ids`` and
  never executes/commits.
* A blank ``ses_message_id`` raises :class:`ValueError` before any DB write,
  so the audit ledger is never fabricated.
* The insert targets ``ON CONFLICT DO NOTHING`` against the
  ``uq_notification_log_send`` unique constraint, making re-recording a send
  idempotent.
* Duplicate ``job_ids`` are deduped (order-preserving) so a single INSERT
  cannot self-collide and the returned count stays unambiguous.
* A DB error rolls back and re-raises.

No real database is touched. A recording fake session captures the queried
column and the ``profile_name == ...`` filter expression and serves preset
rows, mirroring the fake-session pattern in
``tests/test_notifications_digest_repository.py``. The write-side tests use a
:class:`unittest.mock.MagicMock` session and inspect the compiled SQL for the
``ON CONFLICT`` clause rather than executing against PostgreSQL.
"""

from __future__ import annotations

import operator as op
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from database.models import NotificationLog
from notifications.notification_log import get_sent_job_ids, record_sent_jobs

NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


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


class TestRecordSentJobs:
    """Slice 5 write side: persist one audit row per job after a real SES send."""

    def test_empty_input_noop_returns_zero(self):
        """Empty ``job_ids`` is a legitimate no-op (a digest with no jobs), so
        nothing is executed or committed and 0 is returned without raising."""
        session = MagicMock(name="session")

        count = record_sent_jobs(
            session, [], profile_name="industrial_irapuato_bajio", sent_at=NOW, ses_message_id="abc"
        )

        assert count == 0
        session.execute.assert_not_called()
        session.commit.assert_not_called()

    def test_blank_message_id_raises_value_error_before_any_write(self):
        """A blank SES message id must never become an audit row; the gate fires
        before execute so the ledger cannot be fabricated on either path."""
        session = MagicMock(name="session")

        for blank in ("", "   "):
            with pytest.raises(ValueError, match="ses_message_id"):
                record_sent_jobs(session, [1], profile_name="p", sent_at=NOW, ses_message_id=blank)

        session.execute.assert_not_called()
        session.commit.assert_not_called()

    def test_insert_uses_on_conflict_do_nothing_on_unique_constraint(self):
        """The recorder must be idempotent: the compiled statement targets
        ``ON CONFLICT DO NOTHING`` against ``uq_notification_log_send`` so a
        re-recorded send collides and is skipped rather than crashing/duplicating."""
        session = MagicMock(name="session")
        session.execute.return_value = MagicMock(rowcount=2)

        record_sent_jobs(
            session,
            [1, 2],
            profile_name="industrial_irapuato_bajio",
            sent_at=NOW,
            ses_message_id="abc",
        )

        session.execute.assert_called_once()
        stmt = session.execute.call_args.args[0]
        compiled = str(
            stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        assert "ON CONFLICT" in compiled
        assert "DO NOTHING" in compiled
        assert "uq_notification_log_send" in compiled

    def test_commits_after_execute_and_returns_driver_rowcount(self):
        """A happy insert commits once and returns the driver-reported inserted
        rowcount (rows skipped by ON CONFLICT are not counted)."""
        session = MagicMock(name="session")
        session.execute.return_value = MagicMock(rowcount=3)

        count = record_sent_jobs(
            session, [1, 2, 3], profile_name="p", sent_at=NOW, ses_message_id="abc"
        )

        session.execute.assert_called_once()
        session.commit.assert_called_once()
        session.rollback.assert_not_called()
        assert count == 3

    def test_dedupes_duplicate_job_ids(self):
        """Duplicate ids in one INSERT are deduped (order-preserving) so a self-
        collision can never occur and the returned count is unambiguous."""
        session = MagicMock(name="session")
        # rowcount -1 -> fallback to len(deduped rows), exposing dedup via count.
        session.execute.return_value = MagicMock(rowcount=-1)

        count = record_sent_jobs(
            session, [1, 1, 2], profile_name="p", sent_at=NOW, ses_message_id="abc"
        )

        # 3 attempted -> 2 unique; the fallback count reflects the deduped rows.
        assert count == 2

    def test_rolls_back_and_reraises_on_execute_error(self):
        """A DB error rolls the transaction back and re-raises so the caller's
        ``finally`` close() leaves the session clean and the failure surfaces."""
        session = MagicMock(name="session")
        session.execute.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            record_sent_jobs(session, [1], profile_name="p", sent_at=NOW, ses_message_id="abc")

        session.rollback.assert_called_once()
        session.commit.assert_not_called()
