"""Tests for notifications.digest_repository: DB-facing digest retrieval.

Covers the ``feat/alert-digest-selection`` DB integration:

* :func:`fetch_digest_candidates` issues a query filtered by niche, status NEW,
  description non-null / non-empty, and a coarse ``date_scraped >= now - freshness_days``
  lower bound when ``now`` is provided.
* :func:`build_digest` fetches candidates and delegates ranking / freshness /
  CV-fit to :func:`notifications.digest.select_digest`, producing a correct
  :class:`DigestPayload` end-to-end.
* Empty DB result -> empty payload, no errors.
* Profile resolution: ``None`` resolves the default industrial profile.

No real database is touched. A recording fake session captures the filter
expressions and serves preset rows, mirroring the fake-session pattern in
tests/test_enrichment_priority.py. The real SQLAlchemy ``Job`` model is imported
so the filter expressions are real column comparisons (assertable by operator
and bind value, not just string form), but no engine/session is ever opened.
"""

import operator as op
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.sql import operators as sa_operators

from database.models import Job
from notifications.digest import DigestPayload
from notifications.digest_repository import build_digest, fetch_digest_candidates
from notifications.profiles import INDUSTRIAL_IRAPUATO_BAJIO_PROFILE
from shared.utils import aware_utc

PROFILE = INDUSTRIAL_IRAPUATO_BAJIO_PROFILE
ALERT_NICHE = "Industrial Bajío"
_UTC = timezone.utc
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=_UTC)


def make_job(
    job_id,
    title="SAP WM Analyst",
    raw_location="Silao, Guanajuato",
    description="Gestion de warehouse management con SAP WM.",
    industry_niche=ALERT_NICHE,
    status="NEW",
    days_ago=1,
    salary_min=None,
    salary_max=None,
):
    """Build a Job-like SimpleNamespace mirroring the ORM Job shape."""
    return SimpleNamespace(
        id=job_id,
        site="occ",
        job_url=f"https://example.com/job/{job_id}",
        title=title,
        company="Industrias Bajio",
        raw_location=raw_location,
        country="Mexico",
        country_code="MX",
        state="Guanajuato",
        career=title,
        scraped_by="test",
        industry_niche=industry_niche,
        job_type="presencial",
        salary_min=salary_min,
        salary_max=salary_max,
        currency="MXN",
        description=description,
        date_scraped=NOW - timedelta(days=days_ago),
        last_updated=None,
        status=status,
    )


class _RecordingQuery:
    """Chains ``.filter()`` calls, records filter expressions, serves rows.

    Captures both the string form (for substring predicate assertions) and the
    raw expression objects (so tests can compile them and read bind-param
    values, e.g. the niche literal which the compiler renders as a placeholder).
    """

    def __init__(self, rows):
        self._rows = rows
        self.filter_exprs = []
        self.raw_exprs = []

    def filter(self, *exprs):
        self.filter_exprs.extend(str(expr) for expr in exprs)
        self.raw_exprs.extend(exprs)
        return self

    def all(self):
        return list(self._rows)

    def bind_values(self):
        """Compile every captured expression and return its bind-param values."""
        values = []
        for expr in self.raw_exprs:
            values.extend(expr.compile().params.values())
        return values

    def predicates_by_column(self) -> dict:
        """Map each captured expression to ``{column_name: [(operator, value), ...]}``.

        Drift-resistant: tests assert the operator (eq/ne/ge/is_not) and the
        right-hand bind value per column, so a change from ``==`` to ``!=`` or a
        removed predicate is caught here rather than only via a string match.
        ``isnot(None)`` has no right-hand value and is recorded as ``None``.
        """
        mapped: dict[str, list[tuple]] = {}
        for expr in self.raw_exprs:
            col = expr.left
            col_name = col.key
            value = getattr(expr.right, "value", None)
            mapped.setdefault(col_name, []).append((expr.operator, value))
        return mapped


class _RecordingSession:
    """Minimal ORM session: serves preset rows and records the queried model."""

    def __init__(self, rows):
        self._rows = rows
        self.queried_models = []
        self.last_query = None

    def query(self, model):
        self.queried_models.append(model)
        self.last_query = _RecordingQuery(self._rows)
        return self.last_query


def _find_predicate(pred_map, column, operator):
    """Return the bind value for the first ``column`` predicate matching ``operator``.

    Returns ``None`` both when the predicate is absent AND when the predicate
    exists but its bind value is ``None`` (e.g. ``isnot(None)``). Use
    :func:`_has_predicate` to check existence; use this helper to assert the
    exact bind value.
    """
    for found_op, value in pred_map.get(column, []):
        if found_op is operator:
            return value
    return None


def _has_predicate(pred_map, column, operator) -> bool:
    """Return True if ``column`` has a predicate using ``operator`` (any value)."""
    return any(found_op is operator for found_op, _ in pred_map.get(column, []))


# ---------------------------------------------------------------------------
# fetch_digest_candidates: SQL predicates (operator + bind value drift checks)
# ---------------------------------------------------------------------------


class TestFetchDigestCandidates:
    def test_filters_by_niche_status_description_and_freshness_bound(self):
        """Every predicate must be present with the correct operator and value.

        Asserts per-column operator + bind value (not just string substrings) so
        a drift such as ``status != 'NEW'`` or a dropped description non-empty
        check is caught here.
        """
        session = _RecordingSession([make_job(1)])
        fetch_digest_candidates(session, niche=ALERT_NICHE, now=NOW, freshness_days=5)

        assert session.queried_models == [Job]
        preds = session.last_query.predicates_by_column()

        # niche == <niche> (equality, exact value).
        assert _find_predicate(preds, "industry_niche", op.eq) == ALERT_NICHE
        # status == "NEW" (equality, exact value).
        assert _find_predicate(preds, "status", op.eq) == "NEW"
        # description IS NOT NULL (is_not operator; bind value is None, so check
        # existence rather than value).
        assert _has_predicate(preds, "description", sa_operators.is_not)
        # description != "" (not-equal, empty-string bind value).
        assert _find_predicate(preds, "description", op.ne) == ""
        # date_scraped >= now - freshness_days (greater-or-equal, aware UTC bound).
        expected_bound = aware_utc(NOW) - timedelta(days=5)
        assert _find_predicate(preds, "date_scraped", op.ge) == expected_bound

    def test_freshness_lower_bound_uses_aware_utc(self):
        """The SQL date bound must be timezone-aware UTC so a naive ``now`` is
        normalized before binding to the ``timestamptz`` column."""
        naive_now = datetime(2026, 7, 1, 12, 0, 0)
        session = _RecordingSession([make_job(1)])
        fetch_digest_candidates(session, now=naive_now, freshness_days=5)

        preds = session.last_query.predicates_by_column()
        bound = _find_predicate(preds, "date_scraped", op.ge)
        expected = aware_utc(naive_now) - timedelta(days=5)
        assert bound == expected
        assert bound.tzinfo is not None

    def test_now_omitted_skips_date_lower_bound(self):
        """When ``now`` is None (legacy callers), no date_scraped predicate is
        added so the full candidate set loads; the Python filter stays
        authoritative for freshness."""
        session = _RecordingSession([make_job(1)])
        fetch_digest_candidates(session, niche=ALERT_NICHE)

        preds = session.last_query.predicates_by_column()
        assert "date_scraped" not in preds
        # The other three column predicates are still present.
        assert _find_predicate(preds, "industry_niche", op.eq) == ALERT_NICHE
        assert _find_predicate(preds, "status", op.eq) == "NEW"
        assert _has_predicate(preds, "description", sa_operators.is_not)

    def test_returns_rows_from_session_all(self):
        rows = [make_job(1), make_job(2), make_job(3)]
        session = _RecordingSession(rows)

        result = fetch_digest_candidates(session)

        assert result == rows

    def test_empty_session_returns_empty_list(self):
        session = _RecordingSession([])

        result = fetch_digest_candidates(session)

        assert result == []

    def test_uses_default_niche_when_omitted(self):
        session = _RecordingSession([make_job(1)])
        fetch_digest_candidates(session)

        # The niche literal is a bind param (rendered as :industry_niche_1), so
        # read the compiled params to confirm the default niche value is passed.
        assert ALERT_NICHE in session.last_query.bind_values()


# ---------------------------------------------------------------------------
# build_digest: end-to-end fetch + select
# ---------------------------------------------------------------------------


class TestBuildDigest:
    def test_end_to_end_ranks_eligible_jobs(self):
        # The fake query returns every row we give it (it does not actually
        # filter), so this proves build_digest delegates ranking/fit/freshness
        # to select_digest. Two eligible jobs: high score first.
        high = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
        low = make_job(
            2, title="Operador de Produccion", raw_location="Irapuato, Guanajuato"
        )
        session = _RecordingSession([low, high])

        payload = build_digest(session, NOW, profile=PROFILE, limit=10)

        assert isinstance(payload, DigestPayload)
        assert [job.id for job in payload.jobs] == [1, 2]
        assert payload.count == 2

    def test_excludes_stale_and_unfit_rows_via_selector(self):
        """Rows that pass the SQL predicates but fail freshness or CV-fit must
        be excluded by the delegated select_digest, not surfaced raw."""
        fresh_fit = make_job(
            1, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=1
        )
        stale = make_job(
            2, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=30
        )
        wrong_city = make_job(3, title="SAP WM Analyst", raw_location="Queretaro, Queretaro")
        session = _RecordingSession([fresh_fit, stale, wrong_city])

        payload = build_digest(session, NOW, profile=PROFILE, freshness_days=5, limit=10)

        assert [job.id for job in payload.jobs] == [1]

    def test_respects_limit_cap(self):
        rows = [make_job(i) for i in range(1, 6)]
        session = _RecordingSession(rows)

        payload = build_digest(session, NOW, profile=PROFILE, limit=2)

        assert payload.count == 2
        assert payload.limit == 2

    def test_empty_db_returns_empty_payload(self):
        session = _RecordingSession([])

        payload = build_digest(session, NOW, profile=PROFILE, limit=10)

        assert payload.count == 0
        assert payload.jobs == ()

    def test_profile_none_resolves_default(self):
        session = _RecordingSession([make_job(1)])

        payload = build_digest(session, NOW, profile=None, limit=10)

        assert payload.count == 1
        assert payload.profile_name == "industrial_irapuato_bajio"

    def test_payload_salary_fields_serialized_from_db_row(self):
        row = make_job(1, salary_min=Decimal("18000.00"), salary_max=Decimal("22000.00"))
        session = _RecordingSession([row])

        payload = build_digest(session, NOW, profile=PROFILE, limit=10)

        job = payload.jobs[0]
        assert job.salary_min == 18000.0
        assert job.salary_max == 22000.0

    def test_wires_coarse_freshness_lower_bound_into_query(self):
        """build_digest must pass ``now`` through to fetch_digest_candidates so
        the coarse SQL date lower bound is applied (not just the Python filter)."""
        session = _RecordingSession([make_job(1)])

        build_digest(session, NOW, profile=PROFILE, freshness_days=5, limit=10)

        preds = session.last_query.predicates_by_column()
        expected_bound = aware_utc(NOW) - timedelta(days=5)
        assert _find_predicate(preds, "date_scraped", op.ge) == expected_bound
