"""Tests for the two-bucket local enrichment priority (alert + general).

Covers the ``feat/alert-enrichment-priority`` behavior:

* The ALERT bucket (Industrial Bajío, default 20/day, ranked) runs BEFORE the
  GENERAL bucket (tech + other, default 100/day).
* The general bucket excludes the alert niche so no job is processed twice and
  the total never exceeds ``alert_daily_limit + daily_limit``.
* Alert ranking is a deterministic freshness-aware CV-informed ordering
  (fresh first, score descending, date_scraped descending, id ascending).
* The legacy per-site anti-starvation quota split, batching, cooldown, and
  circuit breaker behavior are preserved by the shared execution helper.
* Empty queues exit safely without invoking any scraper.

Pure helpers (``_partition_pending_by_bucket``, ``_split_site_quotas``,
``_aware_utc``, ``_rank_alert_jobs``) are unit-tested directly; the full
``run_local_enrichment_pipeline`` orchestration is exercised through a fake
session and stubbed scrapers so no database or network is touched.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scrapers import pipeline as pipeline_mod
from scrapers.pipeline import (
    _aware_utc,
    _enrich_bucket,
    _partition_pending_by_bucket,
    _rank_alert_jobs,
    _split_site_quotas,
    run_local_enrichment_pipeline,
)
from notifications.profiles import INDUSTRIAL_IRAPUATO_BAJIO_PROFILE

ALERT_NICHE = "Industrial Bajío"
_UTC = timezone.utc


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def make_job(
    job_id,
    site,
    url,
    title,
    raw_location,
    industry_niche,
    date_scraped,
    description=None,
):
    """Build a mutable Job-like object with every attribute the pipeline touches.

    Uses ``SimpleNamespace`` so tests can freely mutate ``status``,
    ``description`` and ``last_updated`` exactly like the ORM path does, without
    needing a real SQLAlchemy model or DB session.
    """
    return SimpleNamespace(
        id=job_id,
        site=site,
        job_url=url,
        title=title,
        company="Corp",
        raw_location=raw_location,
        country="Mexico",
        country_code="MX",
        state="Guanajuato",
        career=title,
        scraped_by="test",
        industry_niche=industry_niche,
        job_type="presencial",
        salary_min=None,
        salary_max=None,
        currency="MXN",
        description=description,
        date_scraped=date_scraped,
        last_updated=None,
        status="PENDING_ENRICHMENT",
    )


def _fresh_date(days_ago=1):
    """A date_scraped guaranteed fresh relative to the real wall clock."""
    return datetime.now(_UTC) - timedelta(days=days_ago)


class _FakeScraper:
    """Stub scraper recording every enrich call into a shared log.

    ``descriptions`` maps ``url -> description_text_or_None``. A url present in
    the map with a non-None value becomes NEW; a url mapped to None becomes
    ORPHANED (all-fail batch for the circuit breaker). When ``empty_result`` is
    True the scraper returns ``{}`` to exercise the legacy empty-result branch.
    """

    def __init__(self, site, descriptions, log, empty_result=False):
        self._site = site
        self._descriptions = descriptions
        self._log = log
        self._empty_result = empty_result

    def enrich_descriptions(self, urls):
        self._log.append((self._site, list(urls)))
        if self._empty_result:
            return {}
        return {
            url: {"description": self._descriptions.get(url), "salary_raw": None}
            for url in urls
        }

    @staticmethod
    def _parse_salary(raw):
        return (None, None)


class _FakeQuery:
    """Chains ``.filter()`` calls and serves a preset row list on ``.all()``."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)

    def count(self):
        return len(self._rows)


class _FakeSession:
    """Minimal ORM session: serves the preset rows and records commits."""

    def __init__(self, rows):
        self._rows = rows
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self._rows)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


@pytest.fixture
def stub_config(monkeypatch):
    """Pin a deterministic ENRICHMENT_CONFIG so tests never read env vars."""
    cfg = {
        "daily_limit": 100,
        "alert_daily_limit": 20,
        "alert_niche": ALERT_NICHE,
        "alert_freshness_days": 5,
        "batch_size": 20,
        "cooldown_seconds": 0,
        "circuit_breaker_threshold": 3,
        "circuit_breaker_sleep": 300,
    }
    monkeypatch.setattr(pipeline_mod, "ENRICHMENT_CONFIG", cfg)
    return cfg


@pytest.fixture
def enrichment_env(monkeypatch):
    """Stub DB session, scrapers, and time for ``run_local_enrichment_pipeline``.

    Yields a controller exposing:
        .log            -- shared list of ``(site, [urls])`` enrich calls, in
                           the exact order they happened across both buckets.
        .descriptions   -- ``url -> description`` map controlling NEW vs
                           ORPHANED outcomes (set before running).
        .mock_time      -- the patched ``time`` module so sleeps are no-ops and
                           callable-argument assertions are possible.
        .install_rows() -- wire a pending row list into a fresh fake session.
    """
    log = []
    descriptions = {}
    mock_time = MagicMock()

    monkeypatch.setattr(pipeline_mod, "time", mock_time)
    monkeypatch.setattr(pipeline_mod, "db_connect", lambda: object())
    monkeypatch.setattr(
        pipeline_mod,
        "ComputrabajoScraper",
        lambda: _FakeScraper("computrabajo", descriptions, log),
    )
    monkeypatch.setattr(
        pipeline_mod,
        "OCCScraper",
        lambda: _FakeScraper("occ", descriptions, log),
    )

    holder = SimpleNamespace(log=log, descriptions=descriptions, mock_time=mock_time)

    def install_rows(rows):
        session = _FakeSession(rows)
        monkeypatch.setattr(
            pipeline_mod, "sessionmaker", lambda bind: (lambda: session)
        )
        return session

    holder.install_rows = install_rows
    return holder


def _flatten_urls(log):
    """Flatten the shared enrich log into an ordered list of enriched URLs."""
    return [url for _site, urls in log for url in urls]


# ---------------------------------------------------------------------------
# _partition_pending_by_bucket
# ---------------------------------------------------------------------------


class TestPartitionPendingByBucket:
    def test_splits_alert_and_general_by_niche(self):
        alert = make_job(
            1, "occ", "u1", "SAP WM", "Silao, Guanajuato", ALERT_NICHE, _fresh_date()
        )
        general = make_job(
            2, "occ", "u2", "Data Engineer", "Mexico", "Ingeniería de Datos", _fresh_date()
        )
        alert_jobs, general_jobs = _partition_pending_by_bucket([alert, general], ALERT_NICHE)

        assert alert_jobs == [alert]
        assert general_jobs == [general]

    def test_null_niche_goes_to_general(self):
        """A pending row with no industry_niche must NOT be silently dropped or
        misrouted into the alert bucket; it enriches as a general row."""
        null_niche = make_job(1, "occ", "u1", "Dev", "Mexico", None, _fresh_date())
        alert_jobs, general_jobs = _partition_pending_by_bucket([null_niche], ALERT_NICHE)

        assert alert_jobs == []
        assert general_jobs == [null_niche]

    def test_preserves_input_order(self):
        rows = [
            make_job(1, "occ", "u1", "A", "Mexico", "Tech", _fresh_date()),
            make_job(2, "occ", "u2", "B", "Silao, Guanajuato", ALERT_NICHE, _fresh_date()),
            make_job(3, "occ", "u3", "C", "Mexico", "Tech", _fresh_date()),
            make_job(4, "occ", "u4", "D", "Irapuato, Guanajuato", ALERT_NICHE, _fresh_date()),
        ]
        alert_jobs, general_jobs = _partition_pending_by_bucket(rows, ALERT_NICHE)

        assert [j.id for j in alert_jobs] == [2, 4]
        assert [j.id for j in general_jobs] == [1, 3]

    def test_empty_input_returns_two_empty_lists(self):
        alert_jobs, general_jobs = _partition_pending_by_bucket([], ALERT_NICHE)
        assert alert_jobs == []
        assert general_jobs == []

    def test_does_not_mutate_input(self):
        rows = [make_job(1, "occ", "u1", "A", "Mexico", "Tech", _fresh_date())]
        _partition_pending_by_bucket(rows, ALERT_NICHE)
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# _split_site_quotas (legacy anti-starvation behavior, preserved verbatim)
# ---------------------------------------------------------------------------


class TestSplitSiteQuotas:
    def test_even_split_when_both_sites_meet_half(self):
        urls = {"computrabajo": ["c"] * 60, "occ": ["o"] * 60}
        quotas = _split_site_quotas(urls, daily_limit=100)
        assert quotas == {"computrabajo": 50, "occ": 50}

    def test_occ_absorbs_computrabajo_underflow(self):
        # Computrabajo has only 20 (< half=50), so OCC gets the leftover 80.
        urls = {"computrabajo": ["c"] * 20, "occ": ["o"] * 200}
        quotas = _split_site_quotas(urls, daily_limit=100)
        assert quotas == {"computrabajo": 20, "occ": 80}

    def test_computrabajo_absorbs_occ_underflow(self):
        urls = {"computrabajo": ["c"] * 200, "occ": ["o"] * 20}
        quotas = _split_site_quotas(urls, daily_limit=100)
        assert quotas == {"computrabajo": 80, "occ": 20}

    def test_never_exceeds_daily_limit(self):
        urls = {"computrabajo": ["c"] * 200, "occ": ["o"] * 200}
        quotas = _split_site_quotas(urls, daily_limit=100)
        assert quotas["computrabajo"] + quotas["occ"] <= 100

    def test_clamps_to_available_pending(self):
        urls = {"computrabajo": ["c"] * 5, "occ": ["o"] * 3}
        quotas = _split_site_quotas(urls, daily_limit=100)
        assert quotas == {"computrabajo": 5, "occ": 3}

    def test_missing_site_treated_as_zero(self):
        urls = {"computrabajo": ["c"] * 10}
        quotas = _split_site_quotas(urls, daily_limit=100)
        # occ absent -> 0, computrabajo under half -> gets the rest.
        assert quotas == {"computrabajo": 10, "occ": 0}

    def test_empty_sites_yield_zero_quotas(self):
        quotas = _split_site_quotas({"computrabajo": [], "occ": []}, daily_limit=100)
        assert quotas == {"computrabajo": 0, "occ": 0}


# ---------------------------------------------------------------------------
# _aware_utc
# ---------------------------------------------------------------------------


class TestAwareUtc:
    def test_none_maps_to_epoch(self):
        result = _aware_utc(None)
        assert result == datetime.fromtimestamp(0, tz=_UTC)

    def test_naive_becomes_aware_utc(self):
        naive = datetime(2026, 6, 30, 12, 0, 0)
        result = _aware_utc(naive)
        assert result.tzinfo is not None
        assert result == naive.replace(tzinfo=_UTC)

    def test_aware_converted_to_utc(self):
        # A +5:00 offset datetime must normalize to UTC (subtract 5 hours).
        aware = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        result = _aware_utc(aware)
        assert result.utcoffset() == timedelta(0)
        assert result.hour == 7


# ---------------------------------------------------------------------------
# _rank_alert_jobs (deterministic freshness-aware CV-informed ordering)
# ---------------------------------------------------------------------------


class TestRankAlertJobs:
    now = datetime(2026, 7, 1, tzinfo=_UTC)

    def _job(self, job_id, title, location, days_ago):
        return make_job(
            job_id,
            "occ",
            f"u{job_id}",
            title,
            location,
            ALERT_NICHE,
            self.now - timedelta(days=days_ago),
        )

    def test_fresh_before_stale_regardless_of_score(self):
        """A stale high-score job must sort AFTER a fresh lower-score job."""
        fresh_low = self._job(3, "Operador de Produccion", "Irapuato, Guanajuato", days_ago=1)
        stale_high = self._job(4, "SAP WM Manager", "Silao, Guanajuato", days_ago=30)

        ranked = _rank_alert_jobs(
            [stale_high, fresh_low], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5
        )

        # Fresh (low score) beats stale (high score).
        assert [j.id for j in ranked] == [3, 4]

    def test_score_descending_within_freshness_bucket(self):
        high = self._job(1, "SAP WM Specialist", "Silao, Guanajuato", days_ago=1)  # 150
        low = self._job(2, "Operador de Produccion", "Irapuato, Guanajuato", days_ago=1)  # 60

        ranked = _rank_alert_jobs(
            [low, high], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5
        )

        assert [j.id for j in ranked] == [1, 2]

    def test_date_scraped_descending_breaks_score_tie(self):
        newer = self._job(1, "SAP WM Specialist", "Silao, Guanajuato", days_ago=1)  # 150, 06-30
        older = self._job(2, "SAP WM Analyst", "Silao, Guanajuato", days_ago=2)  # 150, 06-29

        ranked = _rank_alert_jobs(
            [older, newer], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5
        )

        # Same score -> newer scraped first.
        assert [j.id for j in ranked] == [1, 2]

    def test_id_ascending_is_final_tiebreaker(self):
        same_date = self.now - timedelta(days=1)
        a = make_job(
            2, "occ", "u2", "SAP WM Specialist", "Silao, Guanajuato", ALERT_NICHE, same_date
        )
        b = make_job(
            1, "occ", "u1", "SAP WM Analyst", "Silao, Guanajuato", ALERT_NICHE, same_date
        )

        ranked = _rank_alert_jobs([a, b], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5)

        # Same score, same date -> id ascending.
        assert [j.id for j in ranked] == [1, 2]

    def test_full_four_criteria_order(self):
        """End-to-end ordering: fresh/score/date/id, then stale.

        Jobs:
          A id=1 SAP WM @ Silao  fresh(1d)  score 150
          B id=2 SAP WM @ Silao  fresh(2d)  score 150  (older than A)
          C id=3 Operador @ Irap fresh(1d)  score 60
          E id=5 Recepcionista   fresh(1d)  score 0 (scorer rejects -> fallback)
          D id=4 SAP WM @ Silao  STALE(30d) score 150
        Expected: A, B, C, E, then stale D.
        """
        a = self._job(1, "SAP WM Specialist", "Silao, Guanajuato", days_ago=1)
        b = self._job(2, "SAP WM Analyst", "Silao, Guanajuato", days_ago=2)
        c = self._job(3, "Operador de Produccion", "Irapuato, Guanajuato", days_ago=1)
        d = self._job(4, "SAP WM Manager", "Silao, Guanajuato", days_ago=30)
        e = self._job(5, "Recepcionista", "Silao, Guanajuato", days_ago=1)

        ranked = _rank_alert_jobs(
            [d, e, c, b, a], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5
        )

        assert [j.id for j in ranked] == [1, 2, 3, 5, 4]

    def test_scorer_rejected_job_falls_back_to_score_zero(self):
        """A job the scorer rejects (no role signal) still ranks, at score 0,
        rather than being dropped from the alert bucket."""
        rejected = self._job(5, "Recepcionista", "Silao, Guanajuato", days_ago=1)
        matched = self._job(1, "SAP WM Specialist", "Silao, Guanajuato", days_ago=1)

        ranked = _rank_alert_jobs(
            [rejected, matched], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5
        )

        # Score 0 sorts after score 150 within the same freshness bucket.
        assert [j.id for j in ranked] == [1, 5]

    def test_profile_none_ranks_by_freshness_recency_id_only(self):
        """Graceful degradation: a missing profile -> score 0 for everyone, so
        only freshness / date_scraped / id order the bucket."""
        fresh_new = self._job(1, "Anything", "Silao, Guanajuato", days_ago=1)
        fresh_old = self._job(2, "Anything", "Irapuato, Guanajuato", days_ago=2)
        stale = self._job(4, "SAP WM Manager", "Silao, Guanajuato", days_ago=30)

        ranked = _rank_alert_jobs([stale, fresh_old, fresh_new], None, self.now, 5)

        assert [j.id for j in ranked] == [1, 2, 4]

    def test_missing_date_scraped_sorts_as_oldest(self):
        """A job with no date_scraped is treated as stale (epoch) so it never
        preferentially surfaces in a fresh-first digest."""
        no_date = make_job(9, "occ", "u9", "SAP WM", "Silao, Guanajuato", ALERT_NICHE, None)
        fresh = self._job(1, "Operador", "Irapuato, Guanajuato", days_ago=1)

        ranked = _rank_alert_jobs(
            [no_date, fresh], INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5
        )

        # The fresh job (even with a lower CV score) sorts before the no-date job.
        assert [j.id for j in ranked] == [1, 9]

    def test_deterministic_across_runs(self):
        jobs = [
            self._job(1, "SAP WM Specialist", "Silao, Guanajuato", days_ago=1),
            self._job(2, "Operador", "Irapuato, Guanajuato", days_ago=1),
            self._job(3, "SAP WM Analyst", "Salamanca, Guanajuato", days_ago=2),
        ]
        first = _rank_alert_jobs(jobs, INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5)
        second = _rank_alert_jobs(jobs, INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5)

        assert [j.id for j in first] == [j.id for j in second]

    def test_does_not_mutate_input_order(self):
        jobs = [
            self._job(2, "Operador", "Irapuato, Guanajuato", days_ago=1),
            self._job(1, "SAP WM", "Silao, Guanajuato", days_ago=1),
        ]
        _rank_alert_jobs(jobs, INDUSTRIAL_IRAPUATO_BAJIO_PROFILE, self.now, 5)
        assert [j.id for j in jobs] == [2, 1]


# ---------------------------------------------------------------------------
# run_local_enrichment_pipeline orchestration
# ---------------------------------------------------------------------------


class TestRunLocalEnrichmentPipeline:
    def _industrial(self, job_id, site, days_ago=1):
        return make_job(
            job_id,
            site,
            f"i{job_id}",
            "SAP WM Specialist",
            "Silao, Guanajuato",
            ALERT_NICHE,
            _fresh_date(days_ago),
        )

    def _general(self, job_id, site, days_ago=1):
        return make_job(
            job_id,
            site,
            f"g{job_id}",
            "Data Engineer",
            "Mexico",
            "Ingeniería de Datos",
            _fresh_date(days_ago),
        )

    def _mark_all_described(self, env, rows):
        for row in rows:
            env.descriptions[row.job_url] = f"description for {row.job_url}"

    def test_alert_jobs_enriched_before_general_jobs(self, stub_config, enrichment_env):
        alert = [self._industrial(1, "computrabajo"), self._industrial(2, "occ")]
        general = [self._general(3, "computrabajo"), self._general(4, "occ")]
        rows = alert + general
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        flat = _flatten_urls(enrichment_env.log)
        alert_urls = {j.job_url for j in alert}
        general_urls = {j.job_url for j in general}
        alert_positions = [i for i, u in enumerate(flat) if u in alert_urls]
        general_positions = [i for i, u in enumerate(flat) if u in general_urls]

        assert alert_positions, "alert jobs should have been enriched"
        assert general_positions, "general jobs should have been enriched"
        # Every alert URL enriched before every general URL.
        assert max(alert_positions) < min(general_positions)

    def test_general_bucket_excludes_industrial_jobs(self, stub_config, enrichment_env):
        """Industrial (alert-niche) jobs must never be enriched by the general
        bucket. Asserted end-to-end: industrial URLs only appear in the alert
        section of the call log, never after the first general URL."""
        alert = [self._industrial(i, "computrabajo") for i in range(1, 6)]
        general = [self._general(i, "computrabajo") for i in range(6, 11)]
        rows = alert + general
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        flat = _flatten_urls(enrichment_env.log)
        industrial_urls = {j.job_url for j in alert}
        tech_urls = {j.job_url for j in general}
        last_industrial = max(i for i, u in enumerate(flat) if u in industrial_urls)
        first_tech = min(i for i, u in enumerate(flat) if u in tech_urls)
        assert last_industrial < first_tech
        # And no industrial job leaked into a general (tech) call slot.
        general_section = flat[first_tech:]
        assert not (set(general_section) & industrial_urls)

    def test_no_job_is_enriched_twice(self, stub_config, enrichment_env):
        alert = [self._industrial(1, "computrabajo"), self._industrial(2, "occ")]
        general = [self._general(3, "computrabajo"), self._general(4, "occ")]
        rows = alert + general
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        flat = _flatten_urls(enrichment_env.log)
        assert len(flat) == len(set(flat))

    def test_alert_bucket_respects_alert_limit(self, stub_config, enrichment_env):
        """30 industrial jobs (15 per site) with alert_limit=20 -> exactly 20
        processed (anti-starvation: 10 per site), 10 stay PENDING_ENRICHMENT."""
        rows = [self._industrial(i, "computrabajo") for i in range(1, 16)] + [
            self._industrial(i, "occ") for i in range(16, 31)
        ]
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        processed = [j for j in rows if j.status in ("NEW", "ORPHANED")]
        pending = [j for j in rows if j.status == "PENDING_ENRICHMENT"]
        assert len(processed) == 20
        assert len(pending) == 10

    def test_general_limit_preserved_with_anti_starvation(self, stub_config, enrichment_env):
        """Legacy general behavior: 150 general jobs (90 ct + 60 occ) with
        daily_limit=100 -> 50 per site processed, 50 left pending. No alert
        jobs present, so the general bucket behaves exactly like the old run."""
        rows = [self._general(i, "computrabajo") for i in range(1, 91)] + [
            self._general(i, "occ") for i in range(91, 151)
        ]
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        ct_processed = sum(1 for j in rows if j.site == "computrabajo" and j.status == "NEW")
        occ_processed = sum(1 for j in rows if j.site == "occ" and j.status == "NEW")
        total_processed = ct_processed + occ_processed
        assert ct_processed == 50
        assert occ_processed == 50
        assert total_processed == 100
        assert sum(1 for j in rows if j.status == "PENDING_ENRICHMENT") == 50

    def test_general_anti_starvation_overflow_preserved(self, stub_config, enrichment_env):
        """When one site is light, the other absorbs the leftover (legacy rule).
        20 ct + 200 occ with daily_limit=100 -> ct=20, occ=80."""
        rows = [self._general(i, "computrabajo") for i in range(1, 21)] + [
            self._general(i, "occ") for i in range(21, 221)
        ]
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        ct_processed = sum(1 for j in rows if j.site == "computrabajo" and j.status == "NEW")
        occ_processed = sum(1 for j in rows if j.site == "occ" and j.status == "NEW")
        assert ct_processed == 20
        assert occ_processed == 80
        assert ct_processed + occ_processed == 100

    def test_daily_limit_math_does_not_exceed_alert_plus_general_caps(
        self, stub_config, enrichment_env
    ):
        """More than enough jobs in both buckets: alert <= 20, general <= 100,
        total <= 120. This is the core capacity contract for the feature."""
        alert = [self._industrial(i, "computrabajo") for i in range(1, 31)] + [
            self._industrial(i, "occ") for i in range(31, 61)
        ]
        general = [self._general(i, "computrabajo") for i in range(61, 161)] + [
            self._general(i, "occ") for i in range(161, 261)
        ]
        rows = alert + general
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        alert_processed = sum(1 for j in alert if j.status in ("NEW", "ORPHANED"))
        general_processed = sum(1 for j in general if j.status in ("NEW", "ORPHANED"))
        assert alert_processed <= 20
        assert general_processed <= 100
        assert alert_processed + general_processed <= 120
        # And the caps are actually exercised (not trivially under).
        assert alert_processed == 20
        assert general_processed == 100

    def test_empty_queue_exits_safely(self, stub_config, enrichment_env):
        """No pending rows -> early return, no scraper instantiated, no error."""
        enrichment_env.install_rows([])

        run_local_enrichment_pipeline()

        assert enrichment_env.log == []
        # time.sleep never called because nothing was enriched.
        enrichment_env.mock_time.sleep.assert_not_called()

    def test_empty_general_only_alert_present(self, stub_config, enrichment_env):
        """Only alert jobs pending -> general bucket is a no-op, alert still runs."""
        rows = [self._industrial(1, "computrabajo"), self._industrial(2, "occ")]
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        assert all(j.status == "NEW" for j in rows)
        # Only alert URLs enriched.
        assert set(_flatten_urls(enrichment_env.log)) == {j.job_url for j in rows}

    def test_empty_alert_only_general_present(self, stub_config, enrichment_env):
        """Only general jobs pending -> alert bucket is a no-op, general still runs."""
        rows = [self._general(1, "computrabajo"), self._general(2, "occ")]
        enrichment_env.install_rows(rows)
        self._mark_all_described(enrichment_env, rows)

        run_local_enrichment_pipeline()

        assert all(j.status == "NEW" for j in rows)
        assert set(_flatten_urls(enrichment_env.log)) == {j.job_url for j in rows}

    def test_failed_enrichment_marks_orphaned(self, stub_config, enrichment_env):
        """A url whose description comes back None -> status ORPHANED (legacy)."""
        rows = [self._industrial(1, "computrabajo")]
        enrichment_env.install_rows(rows)
        # No description mapping -> enrich returns description None for the url.
        run_local_enrichment_pipeline()

        assert rows[0].status == "ORPHANED"
        assert rows[0].description is None

    def test_empty_enrich_result_skips_batch_without_status_change(
        self, stub_config, enrichment_env, monkeypatch
    ):
        """Legacy branch: when a scraper returns {} (empty result) the batch is
        skipped (processed counted, no status mutation) and enrichment continues."""
        rows = [self._general(1, "computrabajo"), self._general(2, "computrabajo")]
        enrichment_env.install_rows(rows)
        # Force the computrabajo scraper to return an empty dict every call.
        monkeypatch.setattr(
            pipeline_mod,
            "ComputrabajoScraper",
            lambda: _FakeScraper(
                "computrabajo", enrichment_env.descriptions,
                enrichment_env.log, empty_result=True,
            ),
        )

        run_local_enrichment_pipeline()

        # No status changes (batch skipped), but the urls were attempted.
        assert all(j.status == "PENDING_ENRICHMENT" for j in rows)
        assert _flatten_urls(enrichment_env.log) == [j.job_url for j in rows]

    def test_circuit_breaker_sleeps_after_consecutive_all_fail_batches(
        self, monkeypatch
    ):
        """Preserve the legacy circuit breaker: 3 consecutive all-fail batches on
        the same site trip the breaker and sleep ``circuit_breaker_sleep``."""
        cfg = {
            "daily_limit": 100,
            "alert_daily_limit": 20,
            "alert_niche": ALERT_NICHE,
            "alert_freshness_days": 5,
            "batch_size": 1,           # one url per batch -> 3 batches
            "cooldown_seconds": 0,
            "circuit_breaker_threshold": 3,
            "circuit_breaker_sleep": 300,
        }
        monkeypatch.setattr(pipeline_mod, "ENRICHMENT_CONFIG", cfg)
        log = []
        descriptions = {}
        mock_time = MagicMock()
        monkeypatch.setattr(pipeline_mod, "time", mock_time)
        monkeypatch.setattr(pipeline_mod, "db_connect", lambda: object())
        monkeypatch.setattr(
            pipeline_mod,
            "ComputrabajoScraper",
            lambda: _FakeScraper("computrabajo", descriptions, log),
        )
        monkeypatch.setattr(
            pipeline_mod,
            "OCCScraper",
            lambda: _FakeScraper("occ", descriptions, log),
        )
        # 3 general computrabajo jobs, all failing (no description mapping).
        rows = [self._general(i, "computrabajo") for i in range(1, 4)]
        session = _FakeSession(rows)
        monkeypatch.setattr(pipeline_mod, "sessionmaker", lambda bind: (lambda: session))

        run_local_enrichment_pipeline()

        # All three failed -> ORPHANED, and the circuit breaker slept 300s.
        assert all(j.status == "ORPHANED" for j in rows)
        mock_time.sleep.assert_any_call(300)


# ---------------------------------------------------------------------------
# _enrich_bucket (unit-level coverage of the shared bucket driver)
# ---------------------------------------------------------------------------


class TestEnrichBucket:
    def test_empty_jobs_returns_zeros_without_scraper_calls(self, stub_config, monkeypatch):
        session = _FakeSession([])
        # If the bucket tried to enrich, these factories would record calls.
        log = []
        monkeypatch.setattr(
            pipeline_mod, "ComputrabajoScraper",
            lambda: _FakeScraper("computrabajo", {}, log),
        )
        monkeypatch.setattr(
            pipeline_mod, "OCCScraper",
            lambda: _FakeScraper("occ", {}, log),
        )

        counts = _enrich_bucket(
            session, [], daily_limit=100, config=stub_config, bucket_label="Alert"
        )

        assert counts == {"enriched": 0, "orphaned": 0, "processed": 0}
        assert log == []
