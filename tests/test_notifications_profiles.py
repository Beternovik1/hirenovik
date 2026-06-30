"""Tests for notifications.profiles: dataclass contract and registry lookup."""

import dataclasses

import pytest

from notifications.profiles import (
    ALERT_PROFILES,
    INDUSTRIAL_IRAPUATO_BAJIO_PROFILE,
    AlertProfile,
    get_alert_profile,
)


class TestIndustrialIrapuatoBajioProfile:
    def test_profile_name_matches_search_profile(self):
        assert INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.name == "industrial_irapuato_bajio"

    def test_email_is_placeholder_until_sending_is_wired(self):
        # Matching never reads email; it stays empty in this foundation slice.
        assert INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.email == ""

    def test_allowed_cities_are_strict_guanajuato_region(self):
        cities = set(INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.allowed_cities)
        expected = {
            "irapuato",
            "salamanca",
            "celaya",
            "leon",
            "silao",
            "puerto interior",
            "guanajuato",
            "apaseo",
            "villagran",
            "cortazar",
        }
        assert cities == expected

    def test_allowed_cities_are_accent_folded_lowercase(self):
        for city in INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.allowed_cities:
            assert city == city.lower()
            assert "ñ" not in city and "á" not in city

    def test_include_keywords_contain_core_industrial_roles(self):
        keywords = set(INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.include_keywords)
        # Core industrial role signals must be present.
        for required in ("operador", "mantenimiento", "soldador", "produccion"):
            assert required in keywords

    def test_exclude_keywords_target_internships(self):
        excludes = set(INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.exclude_keywords)
        assert excludes == {"pasante", "becario", "practicante"}

    def test_max_jobs_has_sensible_default(self):
        assert INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.max_jobs == 50

    def test_profile_is_frozen(self):
        # Frozen dataclass prevents accidental mutation of shared profile state.
        with pytest.raises(dataclasses.FrozenInstanceError):
            INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.email = "brother@example.com"  # type: ignore[misc]


class TestGetAlertProfile:
    def test_get_alert_profile_known_returns_profile(self):
        profile = get_alert_profile("industrial_irapuato_bajio")
        assert profile is INDUSTRIAL_IRAPUATO_BAJIO_PROFILE

    def test_get_alert_profile_unknown_returns_none(self):
        assert get_alert_profile("nope") is None

    def test_alert_profiles_registry_contains_industrial_profile(self):
        assert ALERT_PROFILES["industrial_irapuato_bajio"] is INDUSTRIAL_IRAPUATO_BAJIO_PROFILE


class TestAlertProfileDataclass:
    def test_default_max_jobs_is_50(self):
        profile = AlertProfile(
            name="x",
            email="",
            allowed_cities=("irapuato",),
            include_keywords=("operador",),
            exclude_keywords=(),
        )
        assert profile.max_jobs == 50
