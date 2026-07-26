"""Focused tests for legacy CSV export database connection resilience."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import DBAPIError

from reporting_legacy import csv_export


def _dbapi_error(*, connection_invalidated: bool) -> DBAPIError:
    """Build a SQLAlchemy database error with explicit invalidation state."""
    return DBAPIError(
        statement="SELECT jobs",
        params=None,
        orig=RuntimeError("database connection lost"),
        connection_invalidated=connection_invalidated,
    )


def _connection_context(connection: MagicMock) -> MagicMock:
    """Build an engine connection context that yields the given connection."""
    context = MagicMock()
    context.__enter__.return_value = connection
    return context


def _mock_export_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Isolate database, filesystem, and CSV output dependencies."""
    engine = MagicMock()
    db_connect = MagicMock(return_value=engine)
    dataframe = MagicMock()
    dataframe.empty = True

    monkeypatch.setattr(csv_export, "db_connect", db_connect)
    monkeypatch.setattr(csv_export.os.path, "exists", MagicMock(return_value=True))
    monkeypatch.setattr(csv_export.os, "makedirs", MagicMock())

    return engine, db_connect, dataframe


def test_export_jobs_successful_first_read_does_not_retry_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, db_connect, dataframe = _mock_export_dependencies(monkeypatch)
    connection = MagicMock()
    engine.connect.return_value = _connection_context(connection)
    read_sql = MagicMock(return_value=dataframe)
    monkeypatch.setattr(csv_export.pd, "read_sql", read_sql)

    csv_export.export_jobs()

    db_connect.assert_called_once_with()
    engine.connect.assert_called_once_with()
    read_sql.assert_called_once()
    assert read_sql.call_args.args[1] is connection
    engine.dispose.assert_called_once_with()
    dataframe.to_csv.assert_not_called()


def test_export_jobs_invalidated_first_connection_disposes_pool_before_single_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, db_connect, dataframe = _mock_export_dependencies(monkeypatch)
    first_connection = MagicMock()
    second_connection = MagicMock()
    contexts = iter(
        [
            _connection_context(first_connection),
            _connection_context(second_connection),
        ]
    )
    events: list[str] = []

    def connect() -> MagicMock:
        events.append("connect")
        return next(contexts)

    def dispose() -> None:
        events.append("dispose")

    def read_sql(_query: object, connection: MagicMock) -> MagicMock:
        events.append("read")
        if connection is first_connection:
            raise _dbapi_error(connection_invalidated=True)
        return dataframe

    engine.connect.side_effect = connect
    engine.dispose.side_effect = dispose
    mocked_read_sql = MagicMock(side_effect=read_sql)
    monkeypatch.setattr(csv_export.pd, "read_sql", mocked_read_sql)

    csv_export.export_jobs()

    db_connect.assert_called_once_with()
    assert engine.connect.call_count == 2
    assert mocked_read_sql.call_count == 2
    assert mocked_read_sql.call_args_list[0].args[1] is first_connection
    assert mocked_read_sql.call_args_list[1].args[1] is second_connection
    assert events == ["connect", "read", "dispose", "connect", "read", "dispose"]
    assert engine.dispose.call_count == 2
    dataframe.to_csv.assert_not_called()


def test_export_jobs_non_invalidated_dbapi_error_reraises_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, db_connect, _dataframe = _mock_export_dependencies(monkeypatch)
    engine.connect.return_value = _connection_context(MagicMock())
    error = _dbapi_error(connection_invalidated=False)
    read_sql = MagicMock(side_effect=error)
    monkeypatch.setattr(csv_export.pd, "read_sql", read_sql)

    with pytest.raises(DBAPIError) as exc_info:
        csv_export.export_jobs()

    assert exc_info.value is error
    db_connect.assert_called_once_with()
    engine.connect.assert_called_once_with()
    read_sql.assert_called_once()
    engine.dispose.assert_called_once_with()


def test_export_jobs_failed_second_attempt_propagates_without_third_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, db_connect, _dataframe = _mock_export_dependencies(monkeypatch)
    engine.connect.side_effect = [
        _connection_context(MagicMock()),
        _connection_context(MagicMock()),
    ]
    first_error = _dbapi_error(connection_invalidated=True)
    second_error = _dbapi_error(connection_invalidated=True)
    read_sql = MagicMock(side_effect=[first_error, second_error])
    monkeypatch.setattr(csv_export.pd, "read_sql", read_sql)

    with pytest.raises(DBAPIError) as exc_info:
        csv_export.export_jobs()

    assert exc_info.value is second_error
    db_connect.assert_called_once_with()
    assert engine.connect.call_count == 2
    assert read_sql.call_count == 2
    assert engine.dispose.call_count == 2
