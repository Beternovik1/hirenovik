"""Tests for the sequential multi-profile daily scout orchestration.

Covers ``run_multi_profile_cloud_extraction``: profiles run in order, never in
parallel; each profile receives its own conservative results_limit; a cooldown
sleep is applied between profiles but never after the last one.
"""

from unittest.mock import MagicMock, patch

import pytest

from scrapers import pipeline as pipeline_mod
from scrapers.pipeline import run_multi_profile_cloud_extraction
import shared.config as config


@pytest.fixture
def stub_profile_config(monkeypatch):
    """Pin deterministic profile configs and limits so tests do not read env."""
    monkeypatch.setattr(
        config,
        "SEARCH_PROFILES",
        {
            "tech_mx": [("Data Engineer", "Mexico", " Ingeniería de Datos")],
            "industrial_irapuato_bajio": [("Soldador", "Irapuato", "Industrial")],
        },
    )
    monkeypatch.setattr(
        config,
        "PROFILE_RESULTS_LIMITS",
        {"tech_mx": 25, "industrial_irapuato_bajio": 5},
    )
    yield


class TestRunMultiProfileCloudExtraction:
    def test_runs_each_profile_once_in_order(self, stub_profile_config):
        calls = []

        def fake_run(search_config, results_limit, metadata_results_limit=None):
            calls.append((list(search_config), results_limit, metadata_results_limit))
            return None

        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline", side_effect=fake_run), \
             patch.object(pipeline_mod, "time"):
            run_multi_profile_cloud_extraction(
                profiles=["tech_mx", "industrial_irapuato_bajio"],
                cooldown_seconds=60,
            )

        assert [c[0] for c in calls] == [
            [("Data Engineer", "Mexico", " Ingeniería de Datos")],
            [("Soldador", "Irapuato", "Industrial")],
        ]
        # Profile order is preserved: tech_mx first, industrial second.
        assert calls[0][1] == 25
        assert calls[1][1] == 5

    def test_applies_cooldown_between_profiles_not_after_last(self, stub_profile_config):
        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline"), \
             patch.object(pipeline_mod, "time") as mock_time:
            run_multi_profile_cloud_extraction(
                profiles=["tech_mx", "industrial_irapuato_bajio"],
                cooldown_seconds=30,
            )

        # Two profiles => exactly one cooldown sleep between them.
        assert mock_time.sleep.call_count == 1
        mock_time.sleep.assert_called_once_with(30)

    def test_zero_cooldown_disables_sleep(self, stub_profile_config):
        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline"), \
             patch.object(pipeline_mod, "time") as mock_time:
            run_multi_profile_cloud_extraction(
                profiles=["tech_mx", "industrial_irapuato_bajio"],
                cooldown_seconds=0,
            )

        assert mock_time.sleep.call_count == 0

    def test_single_profile_never_sleeps(self, stub_profile_config):
        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline"), \
             patch.object(pipeline_mod, "time") as mock_time:
            run_multi_profile_cloud_extraction(
                profiles=["industrial_irapuato_bajio"],
                cooldown_seconds=60,
            )

        assert mock_time.sleep.call_count == 0

    def test_unknown_profile_raises_before_any_scraping(self, stub_profile_config):
        """Regression (BLOCKER): unknown profile must FAIL CLOSED, never scrape.

        A typo in DAILY_SCOUT_PROFILES must raise before any scraping so we don't
        silently scrape the tech grid twice. get_search_config_for_profile raises
        ValueError, and the orchestrator resolves all profiles up front, so no
        run_cloud_extraction_pipeline call should happen.
        """
        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline") as mock_run, \
             patch.object(pipeline_mod, "time") as mock_time:
            with pytest.raises(ValueError, match="Unknown search profile 'bogus_profile'"):
                run_multi_profile_cloud_extraction(
                    profiles=["tech_mx", "bogus_profile"],
                    cooldown_seconds=60,
                )

        # Up-front validation means nothing scraped and no cooldown slept.
        assert mock_run.call_count == 0
        assert mock_time.sleep.call_count == 0

    def test_unknown_profile_raises_without_persisting_partial_work(self, stub_profile_config):
        """When the FIRST profile is unknown, the known second one must not run."""
        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline") as mock_run, \
             patch.object(pipeline_mod, "time"):
            with pytest.raises(ValueError):
                run_multi_profile_cloud_extraction(
                    profiles=["bogus_profile", "industrial_irapuato_bajio"],
                    cooldown_seconds=0,
                )

        mock_run.assert_not_called()

    def test_empty_profiles_logs_and_does_nothing(self, stub_profile_config):
        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline") as mock_run, \
             patch.object(pipeline_mod, "time"):
            run_multi_profile_cloud_extraction(profiles=[], cooldown_seconds=60)

        assert mock_run.call_count == 0

    def test_failure_in_one_profile_propagates_and_stops(self, stub_profile_config):
        with patch.object(
            pipeline_mod,
            "run_cloud_extraction_pipeline",
            side_effect=RuntimeError("boom"),
        ), \
             patch.object(pipeline_mod, "time") as mock_time:
            with pytest.raises(RuntimeError):
                run_multi_profile_cloud_extraction(
                    profiles=["tech_mx", "industrial_irapuato_bajio"],
                    cooldown_seconds=60,
                )

        # First profile raised before any cooldown had a chance to run.
        assert mock_time.sleep.call_count == 0


class TestMetadataCapPassThrough:
    """Regression (BLOCKER): the per-profile results_limit must apply to ALL
    scraper paths (JobSpy, Computrabajo, OCC), not just JobSpy.

    Previously run_cloud_extraction_pipeline passed NEW_SCRAPERS_CONFIG defaults
    (100) to the metadata scrapers, so the low-volume industrial cap was not
    real across Computrabajo/OCC. The multi-profile orchestrator now passes the
    profile limit as BOTH results_limit and metadata_results_limit.
    """

    def test_multi_profile_passes_metadata_cap_for_each_profile(self, stub_profile_config):
        calls = []

        def fake_run(search_config, results_limit, metadata_results_limit=None):
            calls.append((results_limit, metadata_results_limit))
            return None

        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline", side_effect=fake_run):
            run_multi_profile_cloud_extraction(
                profiles=["tech_mx", "industrial_irapuato_bajio"],
                cooldown_seconds=0,
            )

        # Metadata cap must equal the JobSpy cap for every profile.
        assert calls[0] == (25, 25)
        assert calls[1] == (5, 5)

    def test_metadata_cap_not_none_in_multi_profile_path(self, stub_profile_config):
        """None would fall back to NEW_SCRAPERS_CONFIG defaults and lose the cap."""
        calls = []

        def fake_run(search_config, results_limit, metadata_results_limit=None):
            calls.append(metadata_results_limit)
            return None

        with patch.object(pipeline_mod, "run_cloud_extraction_pipeline", side_effect=fake_run):
            run_multi_profile_cloud_extraction(
                profiles=["industrial_irapuato_bajio"],
                cooldown_seconds=0,
            )

        assert calls == [5]
        assert all(c is not None for c in calls)


class TestLegacyCloudExtractionMetadataDefault:
    """Legacy direct ``cloud_extraction`` mode (tech-only, manual runs) must keep
    using ``NEW_SCRAPERS_CONFIG`` defaults when ``metadata_results_limit`` is
    not passed. The new param defaults to None so the metadata scrapers fall
    back to their per-board configured max_results (100 by default).
    """

    @pytest.fixture
    def stub_cloud_extraction(self, monkeypatch):
        """Stub DB/scraper dependencies so run_cloud_extraction_pipeline can be
        driven in isolation. Records the max_results each metadata scraper gets."""
        ct_calls: list[dict] = []
        occ_calls: list[dict] = []

        fake_session = MagicMock()
        fake_session.close = MagicMock()
        fake_session_factory = MagicMock(return_value=fake_session)

        monkeypatch.setattr(pipeline_mod, "db_connect", lambda: MagicMock())
        monkeypatch.setattr(pipeline_mod, "create_tables", lambda engine: None)
        monkeypatch.setattr(pipeline_mod, "sessionmaker", lambda bind: fake_session_factory)

        fake_empty_df = MagicMock()
        fake_empty_df.empty = True
        monkeypatch.setattr(pipeline_mod, "extract_data", lambda **kwargs: fake_empty_df)
        monkeypatch.setattr(pipeline_mod, "include_linkedin_today", lambda: False)

        fake_ct = MagicMock()
        fake_ct.scrape_metadata = lambda **kwargs: (ct_calls.append(kwargs), fake_empty_df)[1]
        fake_occ = MagicMock()
        fake_occ.scrape_metadata = lambda **kwargs: (occ_calls.append(kwargs), fake_empty_df)[1]

        monkeypatch.setattr(pipeline_mod, "ComputrabajoScraper", lambda: fake_ct)
        monkeypatch.setattr(pipeline_mod, "OCCScraper", lambda: fake_occ)
        monkeypatch.setattr(pipeline_mod, "load_data", lambda session, records: (0, 0))
        monkeypatch.setattr(pipeline_mod, "transform_data", lambda *a: [])

        scraper_config = {
            "computrabajo": {"enabled": True, "countries": ["MX"], "is_remote": False, "max_results": 100},
            "occ": {"enabled": True, "is_remote": False, "max_results": 100},
        }
        monkeypatch.setattr(pipeline_mod, "NEW_SCRAPERS_CONFIG", scraper_config)
        return {"ct_calls": ct_calls, "occ_calls": occ_calls}

    def test_metadata_results_limit_defaults_to_none(self, stub_profile_config, stub_cloud_extraction):
        """When run directly with two args, metadata cap must fall back to
        NEW_SCRAPERS_CONFIG defaults (100), not the JobSpy results_limit (25)."""
        search_config = [("Data Engineer", "Mexico", "Ingenieria de Datos")]
        pipeline_mod.run_cloud_extraction_pipeline(search_config, results_limit=25)

        ct_calls = stub_cloud_extraction["ct_calls"]
        occ_calls = stub_cloud_extraction["occ_calls"]
        assert ct_calls[0]["max_results"] == 100
        assert occ_calls[0]["max_results"] == 100

    def test_metadata_results_limit_override_applies_to_metadata_scrapers(
        self, stub_profile_config, stub_cloud_extraction
    ):
        """When metadata_results_limit is passed explicitly, it overrides the
        NEW_SCRAPERS_CONFIG defaults for BOTH Computrabajo and OCC."""
        search_config = [("SAP WM", "Silao, Guanajuato", "Industrial")]
        pipeline_mod.run_cloud_extraction_pipeline(
            search_config, results_limit=5, metadata_results_limit=5
        )

        ct_calls = stub_cloud_extraction["ct_calls"]
        occ_calls = stub_cloud_extraction["occ_calls"]
        assert ct_calls[0]["max_results"] == 5
        assert occ_calls[0]["max_results"] == 5