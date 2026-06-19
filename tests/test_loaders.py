"""Tests for load_data() — dedup via ON CONFLICT DO NOTHING.

load_data() uses PostgreSQL-specific pg_insert().on_conflict_do_nothing().
For tests, we mock the session to verify behavior without a real Supabase connection.
"""

from unittest.mock import MagicMock, patch

import pytest

from etl.loaders import load_data


class TestLoadData:
    def test_load_data_returns_zero_for_empty_records(self):
        session = MagicMock()
        inserted, skipped = load_data(session, [])
        assert inserted == 0
        assert skipped == 0
        session.execute.assert_not_called()

    def test_load_data_skips_duplicate_job_url(self, mocker):
        """When inserting a duplicate job_url, it should be counted as skipped."""
        session = MagicMock()
        # Mock rowcount to simulate 1 inserted out of 2 records
        session.execute.return_value.rowcount = 1

        records = [
            {"job_url": "https://example.com/job/1", "title": "Dev", "company": "C1"},
            {"job_url": "https://example.com/job/1", "title": "Dev", "company": "C1"},
        ]

        inserted, skipped = load_data(session, records)
        assert inserted == 1
        assert skipped == 1
        session.commit.assert_called_once()

    def test_load_data_all_new_records(self, mocker):
        """When all records are new, inserted should equal len(records)."""
        session = MagicMock()
        session.execute.return_value.rowcount = 3

        records = [
            {"job_url": "https://example.com/job/1", "title": "D1", "company": "C1"},
            {"job_url": "https://example.com/job/2", "title": "D2", "company": "C2"},
            {"job_url": "https://example.com/job/3", "title": "D3", "company": "C3"},
        ]

        inserted, skipped = load_data(session, records)
        assert inserted == 3
        assert skipped == 0

    def test_load_data_rolls_back_on_error(self, mocker):
        """On database error, session.rollback() is called and exception re-raised."""
        session = MagicMock()
        session.execute.side_effect = RuntimeError("Connection lost")

        records = [{"job_url": "https://example.com/job/1", "title": "Dev", "company": "C1"}]

        with pytest.raises(RuntimeError, match="Connection lost"):
            load_data(session, records)

        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    def test_load_data_handles_rowcount_minus_one(self, mocker):
        """Some drivers return rowcount=-1. Fall back to len(records) for inserted."""
        session = MagicMock()
        session.execute.return_value.rowcount = -1

        records = [
            {"job_url": "https://example.com/job/1", "title": "Dev", "company": "C1"},
        ]

        inserted, skipped = load_data(session, records)
        assert inserted == 1
        assert skipped == 0
