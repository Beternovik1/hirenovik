"""Tests for shared.config search profile routing.

Covers SEARCH_PROFILE precedence over WORKER_NAME, the tech_mx and
industrial_irapuato_bajio profiles, unknown-profile fallback, and backward
compatibility with legacy WORKER_NAME routing.
"""

import importlib
import logging

import pytest

import shared.config as config


# Env vars read at import time into module-level constants. Tests that assert
# those constants' default wiring must reload the module with these cleared so
# ambient env (e.g. an exported shell var with the same name) cannot pollute them.
_ENV_DERIVED_VARS = ("DAILY_SCOUT_PROFILES", "PROFILE_COOLDOWN_SECONDS")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_routing(monkeypatch):
    """Reset both routing env vars so each test starts from a known state."""
    monkeypatch.setattr(config, "SEARCH_PROFILE", "")
    monkeypatch.setattr(config, "WORKER_NAME", "Local_Test")
    yield monkeypatch


@pytest.fixture
def reloaded_config_clean_env(monkeypatch):
    """Reload shared.config with env-derived vars cleared.

    Module-level constants like ``DAILY_SCOUT_PROFILES`` and
    ``PROFILE_COOLDOWN_SECONDS`` are computed once at import time from
    ``os.getenv``. Ambient env (an exported shell var) would pollute them, so
    tests that assert the *default wiring* (env unset -> constant == default)
    must reload the module under a cleared environment.

    The original module constants are restored on teardown so subsequent tests
    are unaffected regardless of ambient env.
    """
    originals = {
        "DAILY_SCOUT_PROFILES": config.DAILY_SCOUT_PROFILES,
        "PROFILE_COOLDOWN_SECONDS": config.PROFILE_COOLDOWN_SECONDS,
    }
    for var in _ENV_DERIVED_VARS:
        monkeypatch.delenv(var, raising=False)

    importlib.reload(config)
    try:
        yield config
    finally:
        # Restore the pre-reload constants so other tests see their original
        # (possibly ambient-env-derived) values, not the reloaded defaults.
        for name, value in originals.items():
            setattr(config, name, value)


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------


class TestSearchProfileRegistry:
    def test_registry_exposes_tech_mx_and_industrial_profiles(self):
        assert "tech_mx" in config.SEARCH_PROFILES
        assert "industrial_irapuato_bajio" in config.SEARCH_PROFILES

    def test_default_search_profile_is_tech_mx(self):
        assert config.DEFAULT_SEARCH_PROFILE == "tech_mx"

    def test_tech_mx_preserves_historical_github_actions_content(self):
        tech_mx = config.SEARCH_PROFILES["tech_mx"]
        assert tech_mx[0] == ("Data Engineer", "México", "Ingeniería de Datos")
        # The original GitHub_Actions config had exactly 9 search tuples.
        assert len(tech_mx) == 9

    def test_industrial_bajio_profile_builds_role_city_grid(self):
        industrial = config.SEARCH_PROFILES["industrial_irapuato_bajio"]
        # 6 CV-informed roles x 5 location-tier cities.
        assert len(industrial) == 30
        niches = {niche for _, _, niche in industrial}
        assert niches == {"Industrial Bajío"}
        locations = {location for _, location, _ in industrial}
        # Tier 1/2/3 corridors from INDUSTRIAL_IRAPUATO_BAJIO_LOCATION_TIERS.
        assert ("Silao, Guanajuato") in locations
        assert ("Irapuato, Guanajuato") in locations
        assert ("Salamanca, Guanajuato") in locations
        assert ("Celaya, Guanajuato") in locations
        assert ("León, Guanajuato") in locations

    def test_industrial_bajio_seeds_align_with_cv_informed_roles(self):
        """Regression: scrape seeds must mirror the CV-informed profile vocabulary
        from notifications.profiles, not generic industrial trades. Soldador is
        intentionally excluded (low CV fit); alert-relevant postings still surface
        via the matcher's include_keywords."""
        roles = {role for role, _, _ in config.SEARCH_PROFILES["industrial_irapuato_bajio"]}
        # SAP WM is the highest priority CV term (Tier-1 career growth).
        assert "SAP WM" in roles
        # Industrial engineering is the CV core degree.
        assert "Ingeniero Industrial" in roles
        # Inventory / warehouse / materials drive the inventory/warehouse career path.
        assert "Analista de Inventario" in roles
        assert "Coordinador de Almacén" in roles
        assert "Analista de Materiales" in roles
        # Quality kept (one seed) for the quality/planning role group.
        assert "Inspector de Calidad" in roles
        # Low-fit generic trades must not be seeded.
        assert "Soldador" not in roles
        assert "Operador de Producción" not in roles
        assert "Técnico de Mantenimiento" not in roles

    def test_industrial_bajio_cities_exclude_queretaro(self):
        """Querétaro is rejected at the alert matcher geography gate, so it must
        not be seeded (seeding it wastes scrape quota on dead leads)."""
        locations = {location for _, location, _ in config.SEARCH_PROFILES["industrial_irapuato_bajio"]}
        assert not any("Querétaro" in loc for loc in locations)

    def test_industrial_bajio_seeds_max_scrape_stays_conservative(self):
        """Discovery volume cap across ALL scraper paths must stay conservative
        vs tech_mx. The industrial profile's INDUSTRIAL_RESULTS_LIMIT is applied
        to JobSpy (results_limit) AND to Computrabajo and OCC (metadata
        max_results) by run_multi_profile_cloud_extraction, so the real cap counts
        every board, not just JobSpy.

        Cap math per profile = searches x per-board-limit x boards. tech_mx uses
        the legacy cloud_extraction path where metadata scrapers fall back to
        NEW_SCRAPERS_CONFIG defaults (100), so its real cap is the largest of the
        three per-board caps, not their sum. We assert the industrial per-board
        cap stays conservative on each board independently."""
        industrial = config.SEARCH_PROFILES["industrial_irapuato_bajio"]
        tech_mx = config.SEARCH_PROFILES["tech_mx"]
        searches_i = len(industrial)
        searches_t = len(tech_mx)
        jobspy_limit_i = config.INDUSTRIAL_RESULTS_LIMIT
        jobspy_limit_t = config.SCRAPER_CONFIG["results_limit"]
        metadata_limit_i = config.INDUSTRIAL_RESULTS_LIMIT
        metadata_limit_t = config.NEW_SCRAPERS_CONFIG["computrabajo"]["max_results"]

        # Per-board caps (searches x per-board-limit) for the industrial profile.
        industrial_jobspy_cap = searches_i * jobspy_limit_i
        industrial_metadata_cap = searches_i * metadata_limit_i
        # tech_mx per-board caps (legacy uses NEW_SCRAPERS_CONFIG defaults for metadata).
        tech_jobspy_cap = searches_t * jobspy_limit_t
        tech_metadata_cap = searches_t * metadata_limit_t

        # The industrial low-volume rule must hold on EVERY board independently.
        assert industrial_jobspy_cap <= tech_jobspy_cap
        assert industrial_metadata_cap <= tech_metadata_cap
        # Each industrial board stays bounded by the documented max (30 x 5 = 150).
        assert industrial_jobspy_cap == 150
        assert industrial_metadata_cap == 150


# ---------------------------------------------------------------------------
# SEARCH_PROFILE precedence and fallback
# ---------------------------------------------------------------------------


class TestSearchProfilePrecedence:
    def test_get_search_config_tech_mx_returns_tech_mx_list(self, isolated_routing):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "tech_mx")
        result = config.get_search_config()
        assert result == config.SEARCH_PROFILES["tech_mx"]

    def test_get_search_config_industrial_returns_industrial_list(
        self, isolated_routing
    ):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "industrial_irapuato_bajio")
        result = config.get_search_config()
        assert result == config.SEARCH_PROFILES["industrial_irapuato_bajio"]

    def test_search_profile_takes_precedence_over_worker_name(
        self, isolated_routing
    ):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "industrial_irapuato_bajio")
        isolated_routing.setattr(config, "WORKER_NAME", "GitHub_Actions")
        result = config.get_search_config()
        # Industrial profile wins even though WORKER_NAME would select tech_mx.
        assert result == config.SEARCH_PROFILES["industrial_irapuato_bajio"]
        assert result != config.SEARCH_PROFILES["tech_mx"]

    def test_unknown_search_profile_logs_warning_and_defaults_to_tech_mx(
        self, isolated_routing, caplog
    ):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "bogus_profile")
        with caplog.at_level(logging.WARNING, logger="shared.config"):
            result = config.get_search_config()
        assert result == config.SEARCH_PROFILES["tech_mx"]
        assert "Unknown SEARCH_PROFILE" in caplog.text
        assert "tech_mx" in caplog.text

    def test_empty_search_profile_falls_back_to_worker_name(
        self, isolated_routing
    ):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "")
        isolated_routing.setattr(config, "WORKER_NAME", "Edgar")
        result = config.get_search_config()
        # Edgar legacy config includes Backend Developer; tech_mx does not.
        terms = [term for term, _, _ in result]
        assert "Backend Developer" in terms
        assert len(result) == 4


# ---------------------------------------------------------------------------
# WORKER_NAME backward compatibility
# ---------------------------------------------------------------------------


class TestWorkerNameBackwardCompat:
    def test_github_actions_worker_returns_tech_mx_content(self, isolated_routing):
        isolated_routing.setattr(config, "WORKER_NAME", "GitHub_Actions")
        result = config.get_search_config()
        assert result == config.SEARCH_PROFILES["tech_mx"]

    def test_unknown_worker_name_logs_warning_and_returns_default(
        self, isolated_routing, caplog
    ):
        isolated_routing.setattr(config, "WORKER_NAME", "Nobody")
        with caplog.at_level(logging.WARNING, logger="shared.config"):
            result = config.get_search_config()
        assert len(result) == 2
        assert result[0] == ("Data Engineer", "México", "Ingeniería de Datos")
        assert "Unknown WORKER_NAME" in caplog.text


# ---------------------------------------------------------------------------
# Defensive copies: callers cannot mutate global profile config
# ---------------------------------------------------------------------------


class TestDefensiveCopy:
    """Regression: get_search_config must return a fresh list every call so a
    caller mutating its result cannot corrupt the shared SEARCH_PROFILES
    registry or future lookups."""

    def test_search_profile_path_returns_defensive_copy(self, isolated_routing):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "tech_mx")
        first = config.get_search_config()
        first.append(("INJECTED", "HACK", "X"))
        second = config.get_search_config()
        assert ("INJECTED", "HACK", "X") not in second
        assert ("INJECTED", "HACK", "X") not in config.SEARCH_PROFILES["tech_mx"]
        assert second == config.SEARCH_PROFILES["tech_mx"]

    def test_industrial_profile_path_returns_defensive_copy(self, isolated_routing):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "industrial_irapuato_bajio")
        original_len = len(config.SEARCH_PROFILES["industrial_irapuato_bajio"])
        first = config.get_search_config()
        first.clear()
        assert len(config.SEARCH_PROFILES["industrial_irapuato_bajio"]) == original_len

    def test_unknown_profile_fallback_returns_defensive_copy(
        self, isolated_routing, caplog
    ):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "bogus_profile")
        with caplog.at_level(logging.WARNING, logger="shared.config"):
            first = config.get_search_config()
        first.append(("INJECTED", "HACK", "X"))
        assert ("INJECTED", "HACK", "X") not in config.SEARCH_PROFILES["tech_mx"]

    def test_worker_name_github_actions_path_returns_defensive_copy(
        self, isolated_routing
    ):
        # The GitHub_Actions branch shares _TECH_MX_SEARCH_CONFIG with the
        # registry, so it is the highest-risk legacy path for mutation bugs.
        isolated_routing.setattr(config, "WORKER_NAME", "GitHub_Actions")
        first = config.get_search_config()
        first.append(("INJECTED", "HACK", "X"))
        second = config.get_search_config()
        assert ("INJECTED", "HACK", "X") not in second
        assert ("INJECTED", "HACK", "X") not in config.SEARCH_PROFILES["tech_mx"]

    def test_successive_calls_return_distinct_list_objects(self, isolated_routing):
        isolated_routing.setattr(config, "SEARCH_PROFILE", "tech_mx")
        first = config.get_search_config()
        second = config.get_search_config()
        # Value-equal but not the same object: mutating one never affects the other.
        assert first == second
        assert first is not second
        first.append(("INJECTED", "HACK", "X"))
        assert ("INJECTED", "HACK", "X") not in second


# ---------------------------------------------------------------------------
# Multi-profile daily scout config
# ---------------------------------------------------------------------------


class TestProfileResultsLimits:
    def test_industrial_profile_uses_conservative_limit(self):
        assert config.PROFILE_RESULTS_LIMITS["industrial_irapuato_bajio"] == 5

    def test_tech_mx_profile_inherits_global_scraper_limit(self):
        assert config.PROFILE_RESULTS_LIMITS["tech_mx"] == config.SCRAPER_CONFIG["results_limit"]

    def test_get_profile_results_limit_returns_known_profile(self):
        assert config.get_profile_results_limit("industrial_irapuato_bajio") == 5
        assert config.get_profile_results_limit("tech_mx") == config.SCRAPER_CONFIG["results_limit"]

    def test_get_profile_results_limit_falls_back_to_global_default(self):
        # An unknown profile name must fall back to the global SCRAPER_CONFIG limit.
        assert config.get_profile_results_limit("unknown_profile") == config.SCRAPER_CONFIG["results_limit"]


class TestGetSearchConfigForProfile:
    def test_returns_tech_mx_list_for_explicit_profile(self):
        result = config.get_search_config_for_profile("tech_mx")
        assert result == config.SEARCH_PROFILES["tech_mx"]

    def test_returns_industrial_list_for_explicit_profile(self):
        result = config.get_search_config_for_profile("industrial_irapuato_bajio")
        assert result == config.SEARCH_PROFILES["industrial_irapuato_bajio"]

    def test_unknown_profile_raises_value_error_fail_closed(self, caplog):
        """Regression: multi-profile path must FAIL CLOSED on unknown profile.

        A silent fallback to tech_mx would let a DAILY_SCOUT_PROFILES typo
        scrape the tech grid twice and duplicate DB rows.
        """
        with caplog.at_level(logging.ERROR, logger="shared.config"):
            with pytest.raises(ValueError, match="Unknown search profile 'bogus_profile'"):
                config.get_search_config_for_profile("bogus_profile")
        assert "Unknown search profile" in caplog.text
        # Must NOT return a fallback list.
        assert "bogus_profile" not in config.SEARCH_PROFILES

    def test_error_message_lists_known_profiles(self):
        with pytest.raises(ValueError) as excinfo:
            config.get_search_config_for_profile("nope")
        assert "tech_mx" in str(excinfo.value)
        assert "industrial_irapuato_bajio" in str(excinfo.value)

    def test_returns_defensive_copy(self):
        first = config.get_search_config_for_profile("tech_mx")
        first.append(("INJECTED", "HACK", "X"))
        second = config.get_search_config_for_profile("tech_mx")
        assert ("INJECTED", "HACK", "X") not in second
        assert ("INJECTED", "HACK", "X") not in config.SEARCH_PROFILES["tech_mx"]


class TestParseDailyScoutProfiles:
    """Tests the pure env-parsing logic for DAILY_SCOUT_PROFILES.

    Uses the pure helper directly so tests stay isolated from os.environ and
    deterministic (no module reload leaking env-derived state).
    """

    def test_empty_string_returns_default_order(self):
        assert config._parse_daily_scout_profiles("") == ["tech_mx", "industrial_irapuato_bajio"]

    def test_all_blank_entries_returns_default_order(self):
        assert config._parse_daily_scout_profiles("   ,  , ") == [
            "tech_mx",
            "industrial_irapuato_bajio",
        ]

    def test_env_overrides_default_order(self):
        result = config._parse_daily_scout_profiles("industrial_irapuato_bajio,tech_mx")
        assert result == ["industrial_irapuato_bajio", "tech_mx"]

    def test_surrounding_whitespace_is_trimmed(self):
        result = config._parse_daily_scout_profiles(" tech_mx , industrial_irapuato_bajio ")
        assert result == ["tech_mx", "industrial_irapuato_bajio"]

    def test_single_profile_is_allowed(self):
        assert config._parse_daily_scout_profiles("industrial_irapuato_bajio") == [
            "industrial_irapuato_bajio"
        ]

    def test_returns_fresh_list_each_call(self):
        first = config._parse_daily_scout_profiles("tech_mx")
        first.append("INJECTED")
        second = config._parse_daily_scout_profiles("tech_mx")
        assert "INJECTED" not in second


class TestDailyScoutProfilesDefaults:
    """Asserts the default *wiring*: with env unset, the module-level constants
    equal the documented defaults.

    These reload shared.config under a cleared environment so ambient env (an
    exported ``DAILY_SCOUT_PROFILES`` / ``PROFILE_COOLDOWN_SECONDS`` shell var)
    cannot turn these into tautological or failing assertions.
    """

    def test_module_constant_default_order_is_tech_then_industrial(
        self, reloaded_config_clean_env
    ):
        assert reloaded_config_clean_env.DAILY_SCOUT_PROFILES == [
            "tech_mx",
            "industrial_irapuato_bajio",
        ]

    def test_default_cooldown_is_60_seconds_and_int(self, reloaded_config_clean_env):
        cfg = reloaded_config_clean_env
        assert cfg.PROFILE_COOLDOWN_SECONDS == cfg.DEFAULT_PROFILE_COOLDOWN_SECONDS
        assert isinstance(cfg.PROFILE_COOLDOWN_SECONDS, int)
        assert cfg.DEFAULT_PROFILE_COOLDOWN_SECONDS == 60
