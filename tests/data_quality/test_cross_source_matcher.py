"""Tests for CrossSourceMatcher normalization, scoring, and blocking."""

from datetime import datetime, timezone

from src.data_quality.cross_source_matcher import (
    normalize,
    normalize_company,
    normalize_title_prefix,
    normalize_location,
    location_city,
    is_staffing_company,
    token_jaccard,
    _score_location,
    _score_date,
    _score_salary,
    _score_description,
    _title_disciplines_conflict,
    _title_compatible,
    compute_score,
)


class TestNormalization:
    def test_normalize_basic(self) -> None:
        assert normalize("Hello World") == "hello world"

    def test_normalize_accents(self) -> None:
        assert normalize("León, Guanajuato") == "león guanajuato"

    def test_normalize_punctuation(self) -> None:
        assert normalize("S.A. de C.V.") == "s a de c v"

    def test_normalize_whitespace(self) -> None:
        assert normalize("  many   spaces  ") == "many spaces"

    def test_normalize_none(self) -> None:
        assert normalize(None) == ""

    def test_normalize_company_strips_suffixes(self) -> None:
        assert normalize_company("IDS Comercial, S.A. de C.V.") == "ids comercial"

    def test_normalize_company_preserves_core(self) -> None:
        assert "crediclub" in normalize_company("CrediClub SAPI de CV")

    def test_title_prefix(self) -> None:
        assert normalize_title_prefix("Data Engineer - AWS Cloud") == "data engineer aws"

    def test_title_prefix_spanish(self) -> None:
        assert normalize_title_prefix("Ingeniero de Datos Senior") == "ingeniero de datos"

    def test_location_normalize(self) -> None:
        assert normalize_location("CDMX, México") == "cdmx méxico"

    def test_location_city_extracts(self) -> None:
        assert location_city("León, Guanajuato") == "león"


class TestStaffingDetection:
    def test_ids_comercial_is_staffing(self) -> None:
        assert is_staffing_company("IDS Comercial, S.A. de C.V.") is True

    def test_manpower_is_staffing(self) -> None:
        assert is_staffing_company("ManpowerGroup") is True

    def test_probecarios_is_staffing(self) -> None:
        assert is_staffing_company("Probecarios") is True

    def test_crediclub_is_not_staffing(self) -> None:
        assert is_staffing_company("CrediClub") is False


class TestTitleDisciplines:
    def test_industrial_vs_mecatronica_conflict(self) -> None:
        assert _title_disciplines_conflict(
            "Becario de Ing Industrial o Sistemas",
            "Becario de Ing Mecatrónica o Ing Mecánica"
        ) is True

    def test_data_vs_finance_conflict(self) -> None:
        assert _title_disciplines_conflict(
            "Analista de Datos",
            "Analista Financiero"
        ) is True

    def test_same_discipline_no_conflict(self) -> None:
        assert _title_disciplines_conflict(
            "Data Engineer",
            "Ingeniero de Datos"
        ) is False

    def test_one_no_category_no_conflict(self) -> None:
        assert _title_disciplines_conflict(
            "Analista de Datos",
            "Analista"
        ) is False


class TestScoreLocation:
    def test_exact_match(self) -> None:
        assert _score_location("León, Gto", "León, Gto") == 1.0

    def test_same_city_different_format(self) -> None:
        assert _score_location("León, Gto.", "León, Guanajuato") >= 0.5

    def test_different_city(self) -> None:
        assert _score_location("León, Gto", "Monterrey, NL") == 0.0

    def test_missing_location(self) -> None:
        assert _score_location("", "León") == 0.5


class TestTokenJaccard:
    def test_identical(self) -> None:
        assert token_jaccard("Python SQL AWS", "Python SQL AWS") > 0.9

    def test_similar(self) -> None:
        assert token_jaccard("Python SQL AWS Docker", "Python SQL Docker") > 0.5

    def test_different(self) -> None:
        assert token_jaccard("Python developer", "Truck driver") < 0.2

    def test_missing(self) -> None:
        assert token_jaccard(None, "text") == -1.0

    def test_both_missing(self) -> None:
        assert token_jaccard(None, None) == -1.0


class TestScoreDate:
    def test_same_day(self) -> None:
        d = datetime(2026, 1, 1)
        assert _score_date(d, d) == 1.0

    def test_three_days(self) -> None:
        assert _score_date(datetime(2026, 1, 1), datetime(2026, 1, 4)) == 0.9

    def test_week(self) -> None:
        assert _score_date(datetime(2026, 1, 1), datetime(2026, 1, 8)) == 0.8

    def test_thirty_days(self) -> None:
        assert _score_date(datetime(2026, 1, 1), datetime(2026, 1, 31)) == 0.5

    def test_ninety_days(self) -> None:
        assert _score_date(datetime(2026, 1, 1), datetime(2026, 4, 1)) == 0.2

    def test_over_ninety(self) -> None:
        assert _score_date(datetime(2026, 1, 1), datetime(2026, 7, 1)) == 0.0

    def test_missing(self) -> None:
        assert _score_date(None, datetime(2026, 1, 1)) == 0.5


class TestScoreSalary:
    def test_overlapping_ranges(self) -> None:
        assert _score_salary((30000, 50000), (35000, 45000)) >= 0.5

    def test_contradictory(self) -> None:
        # Non-overlapping ranges
        assert _score_salary((10000, 20000), (50000, 60000)) == 0.0

    def test_one_missing(self) -> None:
        assert _score_salary((30000, 50000), (None, None)) == 0.5

    def test_both_missing(self) -> None:
        assert _score_salary((None, None), (None, None)) == 0.5


class TestScoreDescription:
    def test_identical_description(self) -> None:
        s = _score_description("Python SQL AWS developer", "Python SQL AWS developer")
        assert s > 0.8

    def test_missing_description(self) -> None:
        assert _score_description(None, "text") == -1.0


class TestComputeScore:
    def _job(self, site, title, company, location, desc, sal_min=None, sal_max=None,
             date=None):
        return {
            "site": site, "title": title, "company": company,
            "location": location, "description": desc,
            "salary_min": sal_min, "salary_max": sal_max,
            "date_scraped": date or datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

    def test_strong_match_with_descriptions_is_high(self) -> None:
        a = self._job("indeed", "Data Engineer", "CrediClub", "Leon Gto",
                       "Python SQL AWS Docker experience required", 30000, 50000)
        b = self._job("computrabajo", "Data Engineer", "CrediClub", "Leon Guanajuato",
                       "Python SQL AWS Docker Kubernetes experience", 35000, 45000)
        result = compute_score(a, b)
        assert result["score"] > 0.75
        # With descriptions present and similar, should be HIGH or MEDIUM
        assert result["classification"] in ("high", "medium")

    def test_missing_description_caps_at_medium(self) -> None:
        """Missing description on one side prevents HIGH."""
        a = self._job("indeed", "Data Engineer", "Acme Corp", "CDMX",
                       "Python SQL AWS")  # has description
        b = self._job("computrabajo", "Data Engineer", "Acme Corp", "CDMX",
                       None)  # missing description
        result = compute_score(a, b)
        assert result["classification"] != "high"

    def test_discipline_conflict_not_high(self) -> None:
        """Industrial vs Mecatronica titles must not be HIGH."""
        a = self._job("occ", "Becario de Ing Industrial", "Probecarios",
                       "Silao Gto", "Python SQL", 4500, 4500)
        b = self._job("computrabajo", "Becario de Ing Mecatronica", "Probecarios",
                       "Silao Guanajuato", "Python SQL AWS", 4500, 4500)
        result = compute_score(a, b, is_staffing=True)
        assert result["classification"] != "high"

    def test_staffing_never_high(self) -> None:
        a = self._job("indeed", "Data Engineer", "IDS Comercial", "CDMX",
                       "Python SQL AWS Docker", 40000, 60000)
        b = self._job("computrabajo", "Data Engineer", "IDS Comercial", "CDMX",
                       "Python SQL AWS Docker Kubernetes", 45000, 55000)
        result = compute_score(a, b, is_staffing=True)
        assert result["classification"] != "high"

    def test_both_missing_description_not_high(self) -> None:
        a = self._job("indeed", "Data Engineer", "Acme", "CDMX", None)
        b = self._job("computrabajo", "Data Engineer", "Acme", "CDMX", None)
        result = compute_score(a, b)
        assert result["classification"] != "high"
