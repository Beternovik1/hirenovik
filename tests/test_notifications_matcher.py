"""Tests for notifications.matcher: deterministic geography and keyword filtering.

Covers the industrial Bajío subscriber profile: strict Guanajuato-region city
filtering, include/exclude keyword rules, case/accent insensitivity, NaN safety,
non-mutation of input, and the max_jobs digest cap.
"""

from notifications.matcher import (
    GUANAJUATO_STATE_TOKENS,
    _is_guanajuato_state_suffix,
    matches_alert_geography,
    match_job,
    match_jobs,
)
from notifications.profiles import AlertProfile, INDUSTRIAL_IRAPUATO_BAJIO_PROFILE

PROFILE = INDUSTRIAL_IRAPUATO_BAJIO_PROFILE


def _job(title: str, location: str, description: str = "", **extra) -> dict:
    """Build a transform-shaped job record with optional extra fields."""
    record = {
        "title": title,
        "raw_location": location,
        "description": description,
        "job_url": "https://example.com/job/1",
        "company": "Industrias Bajío",
    }
    record.update(extra)
    return record


# ---------------------------------------------------------------------------
# Geography: allowed Guanajuato cities pass
# ---------------------------------------------------------------------------


class TestAllowedGeographyPasses:
    def test_match_job_irapuato_industrial_role_returns_match(self):
        result = match_job(_job("Operador de Producción", "Irapuato, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "irapuato"
        assert result["matched_keyword"] in {"operador", "produccion"}

    def test_match_job_leon_with_accent_matches_city_leon(self):
        result = match_job(_job("Técnico de Mantenimiento", "León, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "leon"

    def test_match_job_salamanca_soldador_matches(self):
        result = match_job(_job("Soldador", "Salamanca, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "salamanca"
        assert result["matched_keyword"] == "soldador"

    def test_match_job_capital_guanajuato_city_matches(self):
        # "Guanajuato, Guanajuato" is the capital city, which is allowed.
        result = match_job(_job("Inspector de Calidad", "Guanajuato, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "guanajuato"

    def test_match_job_apaseo_el_grande_matches_via_substring(self):
        result = match_job(_job("Almacenista", "Apaseo el Grande, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "apaseo"
        assert result["matched_keyword"] == "almacen"

    def test_match_job_villagran_with_accent_matches(self):
        result = match_job(_job("Soldador", "Villagrán, Gto."), PROFILE)
        assert result is not None
        assert result["matched_city"] == "villagran"

    def test_match_job_bare_unambiguous_city_without_comma_still_matches(self):
        # The comma requirement applies ONLY to state-homonymous tokens
        # ("guanajuato"). Unambiguous cities like Irapuato match with or without
        # a comma because no state shares their name.
        result = match_job(_job("Operador de Producción", "Irapuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "irapuato"


# ---------------------------------------------------------------------------
# Geography: Indeed-published "GUA" state abbreviation (regression)
# ---------------------------------------------------------------------------


class TestIndeedGuaAbbreviation:
    # Indeed publishes Guanajuato as "GUA" in raw_location (e.g. "Celaya, GUA,
    # MX"). Before the fix, "gua" was not in GUANAJUATO_STATE_TOKENS, so all
    # 67 fresh Indeed Industrial Bajio candidates failed state validation and
    # never reached scoring. These tests pin the abbreviation acceptance.

    def test_gua_is_registered_as_state_token(self):
        assert "gua" in GUANAJUATO_STATE_TOKENS

    def test_match_job_celaya_gua_mx_matches(self):
        result = match_job(_job("Operador de Producción", "Celaya, GUA, MX"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "celaya"

    def test_match_job_leon_gua_mx_matches(self):
        result = match_job(_job("Técnico de Mantenimiento", "León, GUA, MX"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "leon"

    def test_match_job_silao_gua_mx_matches(self):
        result = match_job(_job("Soldador", "Silao, GUA, MX"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "silao"

    def test_is_guanajuato_state_suffix_gua_returns_true(self):
        assert _is_guanajuato_state_suffix("GUA, MX") is True

    def test_is_guanajuato_state_suffix_guadalajara_returns_false(self):
        # "gua" is a registered token, but tokenization extracts whole words, so
        # "guadalajara" is a single token that does not equal "gua". This guards
        # against a false positive where a "GUA" state token could leak into the
        # Jalisco city name via substring matching.
        assert _is_guanajuato_state_suffix("Guadalajara") is False

    def test_match_job_allowed_city_with_guadalajara_suffix_rejected(self):
        # Belt-and-suspenders: even with a Bajio city prefix, a "Guadalajara"
        # state suffix (a single non-matching token) must reject the job. This
        # proves the "gua" token does not match "guadalajara" through the matcher.
        result = match_job(_job("Soldador", "Irapuato, Guadalajara"), PROFILE)
        assert result is None


# ---------------------------------------------------------------------------
# Geography: jobs outside allowed cities fail even with a good role keyword
# ---------------------------------------------------------------------------


class TestOutsideGeographyFails:
    def test_match_job_mexico_city_rejected_even_with_good_role(self):
        result = match_job(_job("Operador de Producción", "Ciudad de México, México"), PROFILE)
        assert result is None

    def test_match_job_queretaro_rejected_even_with_good_role(self):
        result = match_job(_job("Técnico de Mantenimiento", "Querétaro, Qro."), PROFILE)
        assert result is None

    def test_match_job_monterrey_rejected_even_with_good_role(self):
        result = match_job(_job("Soldador", "Monterrey, Nuevo León"), PROFILE)
        assert result is None

    def test_match_job_non_allowed_guanajuato_city_rejected(self):
        # San Francisco del Rincón is in Guanajuato state but not in the allowed
        # cities. The matcher must inspect the city part only, not the state, so
        # the bare "Guanajuato" state mention must not trigger a false positive.
        result = match_job(_job("Soldador", "San Francisco del Rincón, Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_bare_guanajuato_state_only_rejected(self):
        # Regression: "guanajuato" is both a city and a state. A bare
        # "Guanajuato" with no state suffix is ambiguous (could be the state),
        # so strict alerts must reject it even when the role keyword is good.
        result = match_job(_job("Soldador", "Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_bare_guanajuato_with_industrial_role_still_rejected(self):
        # The role keyword is good, but the bare location is ambiguous.
        # Geography must fail before keywords are even checked.
        result = match_job(_job("Operador de Producción", "Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_guanajuato_comma_guanajuato_still_matches(self):
        # Positive control for the homonym rule: "Guanajuato, Guanajuato" is in
        # "city, state" form, which clearly names the capital city, so it is
        # accepted even though the bare token is ambiguous.
        result = match_job(_job("Inspector de Calidad", "Guanajuato, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "guanajuato"

    def test_match_job_leon_in_nuevo_leon_state_rejected(self):
        # Regression: the city token "leon" matches, but the state suffix is
        # Nuevo León, not Guanajuato. A non-Guanajuato suffix must reject the
        # job even when the city name is an allowed token.
        result = match_job(_job("Soldador", "León, Nuevo León"), PROFILE)
        assert result is None

    def test_match_job_irapuato_in_jalisco_state_rejected(self):
        # Regression: "irapuato" is an allowed city, but "Irapuato, Jalisco" is
        # outside the Bajio target. The state suffix validation must reject it.
        result = match_job(_job("Operador de Producción", "Irapuato, Jalisco"), PROFILE)
        assert result is None

    def test_match_job_guanajuato_in_nuevo_leon_state_rejected(self):
        # Regression: the homonymous capital token appears with a non-Guanajuato
        # state suffix. The suffix validation rejects it before the homonym rule
        # could accept it.
        result = match_job(_job("Inspector de Calidad", "Guanajuato, Nuevo León"), PROFILE)
        assert result is None

    def test_match_job_irapuato_in_gto_abbreviation_matches(self):
        # Positive control: the "Gto." abbreviation is an accepted Guanajuato
        # state suffix, so the job matches.
        result = match_job(_job("Operador de Producción", "Irapuato, Gto."), PROFILE)
        assert result is not None
        assert result["matched_city"] == "irapuato"

    def test_match_job_nuevo_leon_state_does_not_match_city_leon(self):
        # Regression: "leon" is an allowed city token, but "Nuevo León" is a
        # different state. Substring matching falsely matched this; the anchored
        # word-boundary check must reject it.
        result = match_job(_job("Soldador", "Nuevo León"), PROFILE)
        assert result is None

    def test_match_job_nuevo_leon_with_country_does_not_match_city_leon(self):
        # Regression: same false positive when the country is appended.
        result = match_job(_job("Operador de Producción", "Nuevo León, México"), PROFILE)
        assert result is None

    def test_match_job_nuevo_leon_with_role_keyword_still_rejected(self):
        # The role keyword is good, but the geography is wrong: Nuevo León is
        # not a Bajío city. Geography must fail before keywords are even checked.
        result = match_job(_job("Soldador TIG", "Monterrey, Nuevo León"), PROFILE)
        assert result is None

    def test_match_job_suffixed_city_form_rejected(self):
        # Word boundary must also reject suffixed forms so "leona" / "leonardo"
        # do not match the "leon" city token.
        result = match_job(_job("Soldador", "Leonarda, Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_leon_guanajuato_still_matches_after_boundary_fix(self):
        # Positive control for the regression set: the real Bajío city still
        # matches with the anchored word-boundary logic.
        result = match_job(_job("Soldador", "León, Guanajuato"), PROFILE)
        assert result is not None
        assert result["matched_city"] == "leon"


# ---------------------------------------------------------------------------
# Keyword rules: irrelevant roles and excluded terms fail
# ---------------------------------------------------------------------------


class TestKeywordRules:
    def test_match_job_irrelevant_role_in_allowed_city_rejected(self):
        # Backend developer is a tech role, not industrial; no include keyword.
        result = match_job(_job("Desarrollador Backend", "Irapuato, Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_pasante_internship_rejected(self):
        result = match_job(_job("Pasante de Producción", "Celaya, Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_becario_internship_rejected(self):
        result = match_job(_job("Becario de Calidad", "Irapuato, Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_practicante_internship_rejected(self):
        result = match_job(_job("Practicante de Logística", "León, Guanajuato"), PROFILE)
        assert result is None

    def test_match_job_exclude_wins_over_include(self):
        # "operador" is present (include) but "pasante" is present (exclude).
        description = "Buscamos pasante para apoyo en línea de producción."
        result = match_job(
            _job("Operador de Producción", "Irapuato, Guanajuato", description),
            PROFILE,
        )
        assert result is None

    def test_match_job_keyword_in_description_matches(self):
        # Title has no include keyword, but the description names the role.
        result = match_job(
            _job("Personal de Planta", "Irapuato, Guanajuato",
                 description="Buscamos operador de producción para línea."),
            PROFILE,
        )
        assert result is not None
        assert result["matched_keyword"] == "operador"


# ---------------------------------------------------------------------------
# Case / accent insensitivity and field flexibility
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_match_job_uppercase_title_and_location_matches(self):
        result = match_job(
            _job("OPERADOR DE PRODUCCIÓN", "IRAPUATO, GTO."), PROFILE
        )
        assert result is not None
        assert result["matched_city"] == "irapuato"

    def test_match_job_accepts_location_key_when_raw_location_missing(self):
        record = {"title": "Soldador", "location": "Celaya, Guanajuato"}
        result = match_job(record, PROFILE)
        assert result is not None
        assert result["matched_city"] == "celaya"

    def test_match_job_accepts_location_key_when_raw_location_is_empty(self):
        record = {
            "title": "Soldador",
            "raw_location": "",
            "location": "Silao, Guanajuato",
        }
        result = match_job(record, PROFILE)
        assert result is not None
        assert result["matched_city"] == "silao"


# ---------------------------------------------------------------------------
# Edge cases: missing fields, NaN, non-mutation
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_match_job_missing_location_rejected(self):
        result = match_job({"title": "Soldador"}, PROFILE)
        assert result is None

    def test_match_job_missing_title_and_description_rejected(self):
        result = match_job({"raw_location": "Irapuato, Guanajuato"}, PROFILE)
        assert result is None

    def test_match_job_nan_location_treated_as_empty(self):
        record = {"title": "Operador de Producción", "raw_location": float("nan")}
        result = match_job(record, PROFILE)
        assert result is None

    def test_match_job_nan_description_does_not_crash(self):
        record = {
            "title": "Operador de Producción",
            "raw_location": "Irapuato, Guanajuato",
            "description": float("nan"),
        }
        result = match_job(record, PROFILE)
        # Title still provides the include keyword; NaN description is ignored.
        assert result is not None

    def test_match_job_none_location_rejected(self):
        record = {"title": "Soldador", "raw_location": None}
        result = match_job(record, PROFILE)
        assert result is None

    def test_match_job_does_not_mutate_input(self):
        record = _job("Operador de Producción", "Irapuato, Guanajuato")
        result = match_job(record, PROFILE)
        assert result is not None
        assert "matched_city" not in record
        assert "matched_keyword" not in record
        assert result is not record

    def test_match_job_preserves_original_fields_in_digest(self):
        record = _job("Soldador", "Salamanca, Guanajuato", company="Aceros Bajío")
        result = match_job(record, PROFILE)
        assert result is not None
        assert result["company"] == "Aceros Bajío"
        assert result["job_url"] == "https://example.com/job/1"
        assert result["matched_city"] == "salamanca"


# ---------------------------------------------------------------------------
# match_jobs: batch filtering and max_jobs cap
# ---------------------------------------------------------------------------


class TestMatchJobs:
    def test_match_jobs_empty_input_returns_empty(self):
        assert match_jobs([], PROFILE) == []

    def test_match_jobs_returns_only_matches_in_order(self):
        records = [
            _job("Operador de Producción", "Irapuato, Guanajuato"),  # match
            _job("Desarrollador Backend", "Irapuato, Guanajuato"),   # no keyword
            _job("Soldador", "Salamanca, Guanajuato"),               # match
            _job("Operador de Producción", "CDMX, México"),          # wrong city
        ]
        results = match_jobs(records, PROFILE)
        assert len(results) == 2
        assert results[0]["matched_city"] == "irapuato"
        assert results[1]["matched_city"] == "salamanca"

    def test_match_jobs_all_rejected_returns_empty(self):
        records = [
            _job("Desarrollador Backend", "Irapuato, Guanajuato"),
            _job("Operador de Producción", "Monterrey, Nuevo León"),
        ]
        assert match_jobs(records, PROFILE) == []

    def test_match_jobs_caps_at_max_jobs(self):
        capped_profile = AlertProfile(
            name="capped_test",
            email="",
            allowed_cities=PROFILE.allowed_cities,
            include_keywords=PROFILE.include_keywords,
            exclude_keywords=PROFILE.exclude_keywords,
            max_jobs=2,
        )
        records = [
            _job("Operador de Producción", "Irapuato, Guanajuato", job_url=f"url-{i}")
            for i in range(5)
        ]
        results = match_jobs(records, capped_profile)
        assert len(results) == 2

    def test_match_jobs_zero_max_jobs_returns_empty(self):
        zero_profile = AlertProfile(
            name="zero_test",
            email="",
            allowed_cities=PROFILE.allowed_cities,
            include_keywords=PROFILE.include_keywords,
            exclude_keywords=PROFILE.exclude_keywords,
            max_jobs=0,
        )
        records = [_job("Operador de Producción", "Irapuato, Guanajuato")]
        assert match_jobs(records, zero_profile) == []

    def test_match_jobs_single_row_input(self):
        results = match_jobs([_job("Soldador", "Celaya, Guanajuato")], PROFILE)
        assert len(results) == 1
        assert results[0]["matched_city"] == "celaya"


# ---------------------------------------------------------------------------
# matches_alert_geography: public Phase 1 geography gate
# ---------------------------------------------------------------------------


class TestMatchesAlertGeography:
    """Phase 1 OCC insert filter reuses the same geography semantics."""

    CITIES = INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.allowed_cities

    def test_matches_alert_geography_celaya_gua_mx_returns_true(self):
        # Indeed-style "city, GUA, MX" abbreviation must pass.
        assert matches_alert_geography("Celaya, GUA, MX", self.CITIES) is True

    def test_matches_alert_geography_leon_with_accent_returns_true(self):
        assert matches_alert_geography("León, Guanajuato", self.CITIES) is True

    def test_matches_alert_geography_irapuato_returns_true(self):
        assert matches_alert_geography("Irapuato, Guanajuato", self.CITIES) is True

    def test_matches_alert_geography_tizayuca_hidalgo_returns_false(self):
        assert matches_alert_geography("Tizayuca, Hidalgo", self.CITIES) is False

    def test_matches_alert_geography_chihuahua_returns_false(self):
        assert matches_alert_geography("Chihuahua, Chihuahua", self.CITIES) is False

    def test_matches_alert_geography_miguel_hidalgo_cdmx_returns_false(self):
        # "Miguel Hidalgo, Ciudad de México" — outside Bajío geography.
        assert matches_alert_geography(
            "Miguel Hidalgo, Ciudad de México", self.CITIES
        ) is False

    def test_matches_alert_geography_leon_nuevo_leon_returns_false(self):
        # Same city name "Leon" but a non-Guanajuato state suffix -> rejected.
        assert matches_alert_geography("Leon, Nuevo Leon", self.CITIES) is False

    def test_matches_alert_geography_none_returns_false(self):
        assert matches_alert_geography(None, self.CITIES) is False

    def test_matches_alert_geography_nan_returns_false(self):
        import math
        assert matches_alert_geography(math.nan, self.CITIES) is False

    def test_matches_alert_geography_empty_string_returns_false(self):
        assert matches_alert_geography("", self.CITIES) is False

    def test_matches_alert_geography_empty_cities_returns_false(self):
        # No allowed cities means nothing can match.
        assert matches_alert_geography("Irapuato, Guanajuato", ()) is False
