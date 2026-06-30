"""Tests for shared.config search profile routing.

Covers SEARCH_PROFILE precedence over WORKER_NAME, the tech_mx and
industrial_irapuato_bajio profiles, unknown-profile fallback, and backward
compatibility with legacy WORKER_NAME routing.
"""

import logging

import pytest

import shared.config as config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_routing(monkeypatch):
    """Reset both routing env vars so each test starts from a known state."""
    monkeypatch.setattr(config, "SEARCH_PROFILE", "")
    monkeypatch.setattr(config, "WORKER_NAME", "Local_Test")
    yield monkeypatch


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
        # 5 roles x 4 cities.
        assert len(industrial) == 20
        niches = {niche for _, _, niche in industrial}
        assert niches == {"Industrial Bajío"}
        locations = {location for _, location, _ in industrial}
        assert ("Irapuato, Guanajuato") in locations
        assert ("León, Guanajuato") in locations


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
