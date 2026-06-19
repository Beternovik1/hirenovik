"""Tests for Glue job feature engineering logic (clean_and_curate.py).

Tests the business logic using pandas — same transformations, no PySpark/Java dependency.
Covers: salary calculations, outlier filtering, seniority detection, modality encoding,
keyword features, and career filters.
"""

import re

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helper functions extracted from Glue job logic for testability
# ---------------------------------------------------------------------------

MXN_USD_RATE = 17.5

OUTLIER_MIN_MXN = 5000
OUTLIER_MAX_MXN = 150000

SENIORITY_PATTERNS = [
    # Order matters: more specific before less specific.
    # "semi-senior" must be checked BEFORE "senior" to avoid substring match.
    (2, r"(?i)(?:^|\s)(semi-senior|mid|intermediate|ssr)(?:\s|$)"),
    (3, r"(?i)(?:^|\s)(senior|sr\.?|lead|principal|staff)(?:\s|$)"),
    (0, r"(?i)(?:^|\s)(junior|jr\.?|trainee|entry)(?:\s|$)"),
]

EXPERIENCE_MAP = {3: 6, 2: 4, 1: 2, 0: 0}

MODALITY_MAP = {"remoto": 0, "hibrido": 1, "presencial": 2}

KEYWORD_FEATURES = [
    "python", "aws", "spark", "docker", "sql", "tensorflow",
    "kubernetes", "airflow", "dbt", "kafka", "azure", "gcp",
    "pytorch", "scikit", "pandas", "hadoop", "snowflake",
    "bigquery", "redshift", "terraform", "jenkins", "git",
    "linux", "mlops", "databricks", "powerbi", "tableau",
    "mongodb", "postgresql", "mysql", "react", "nodejs",
    "flask", "django", "fastapi", "go", "rust", "java", "scala",
]

MIN_TRAINING_RECORDS = 30


def compute_salary_mid(salary_min, salary_max):
    return (float(salary_min or 0) + float(salary_max or 0)) / 2


def compute_salary_mid_usd(salary_mid, currency):
    if currency == "MXN":
        return salary_mid / MXN_USD_RATE
    return salary_mid


def has_salary(salary_min, salary_max):
    return salary_min is not None and salary_max is not None


def is_outlier(salary_mid, currency, has_sal):
    if not has_sal:
        return False
    if currency != "MXN":
        return False
    return salary_mid < OUTLIER_MIN_MXN or salary_mid > OUTLIER_MAX_MXN


def detect_seniority(title):
    title = str(title)
    for level, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, title):
            return level
    return 1


def map_experience(seniority):
    return EXPERIENCE_MAP.get(seniority, 1)


def map_modality(job_type):
    return MODALITY_MAP.get(str(job_type).lower(), 1)


def has_keyword(description, keyword):
    desc = str(description).lower()
    return int(bool(re.search(rf"\b{re.escape(keyword)}\b", desc)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSalaryFeatures:
    def test_salary_mid_averages_min_and_max(self):
        assert compute_salary_mid(20000, 40000) == 30000.0

    def test_salary_mid_treats_none_as_zero(self):
        assert compute_salary_mid(None, None) == 0.0
        assert compute_salary_mid(20000, None) == 10000.0

    def test_salary_mid_usd_converts_mxn(self):
        assert compute_salary_mid_usd(35000, "MXN") == 2000.0

    def test_salary_mid_usd_passes_non_mxn_through(self):
        assert compute_salary_mid_usd(5000, "USD") == 5000.0

    def test_has_salary_true_only_when_both_not_null(self):
        assert has_salary(20000, 40000) is True
        assert has_salary(20000, None) is False
        assert has_salary(None, None) is False


class TestOutlierFilter:
    def test_keeps_valid_mxn_salary(self):
        assert is_outlier(35000, "MXN", True) is False

    def test_filters_below_minimum(self):
        assert is_outlier(3000, "MXN", True) is True

    def test_filters_above_maximum(self):
        assert is_outlier(200000, "MXN", True) is True

    def test_keeps_non_salary_records(self):
        assert is_outlier(0, "MXN", False) is False

    def test_passes_non_mxn_through(self):
        assert is_outlier(5000, "USD", True) is False


class TestSeniorityFeatures:
    def test_detects_senior_titles(self):
        for title in [
            "Senior Data Engineer",
            "Sr. Cloud Architect",
            "Lead Backend Developer",
            "Principal Engineer",
            "Staff Software Engineer",
        ]:
            assert detect_seniority(title) == 3, f"Failed for: {title}"

    def test_detects_semi_senior_titles(self):
        for title in [
            "Semi-Senior Developer",
            "Mid Level Engineer",
            "Intermediate Analyst",
            "SSR Backend",
        ]:
            assert detect_seniority(title) == 2, f"Failed for: {title}"

    def test_detects_junior_titles(self):
        for title in [
            "Junior Developer",
            "Jr. Data Analyst",
            "Trainee Engineer",
            "Entry Level Programmer",
        ]:
            assert detect_seniority(title) == 0, f"Failed for: {title}"

    def test_defaults_to_mid_level(self):
        assert detect_seniority("Backend Developer") == 1
        assert detect_seniority("Data Engineer") == 1

    def test_maps_experience_from_seniority(self):
        assert map_experience(3) == 6
        assert map_experience(2) == 4
        assert map_experience(1) == 2
        assert map_experience(0) == 0
        assert map_experience(99) == 1  # unknown defaults to 1


class TestModalityFeatures:
    def test_maps_remoto_to_zero(self):
        assert map_modality("remoto") == 0

    def test_maps_hibrido_to_one(self):
        assert map_modality("hibrido") == 1

    def test_maps_presencial_to_two(self):
        assert map_modality("presencial") == 2

    def test_defaults_to_one_for_unknown(self):
        assert map_modality("freelance") == 1
        assert map_modality(None) == 1


class TestKeywordFeatures:
    def test_matches_word_boundaries(self):
        assert has_keyword("We need python and aws experience", "python") == 1
        assert has_keyword("We need python and aws experience", "aws") == 1

    def test_is_case_insensitive(self):
        assert has_keyword("We use Python and AWS daily", "python") == 1

    def test_does_not_match_substrings(self):
        assert has_keyword("We use javascript for frontend", "java") == 0

    def test_no_keywords_returns_zero(self):
        assert has_keyword("No tech keywords here", "python") == 0

    def test_handles_none_description(self):
        assert has_keyword(None, "python") == 0

    def test_all_keywords_have_columns(self):
        """Verify all 39 keyword features are present (matching Glue job)."""
        assert len(KEYWORD_FEATURES) == 39
        assert "python" in KEYWORD_FEATURES
        assert "scala" in KEYWORD_FEATURES


class TestCareerFilter:
    def test_is_valid_for_training_requires_min_records(self):
        """Career with <30 salary records is not valid for training."""
        career_counts = {"Data Engineer": 25, "Data Analyst": 45}
        valid_careers = {
            career for career, count in career_counts.items()
            if count >= MIN_TRAINING_RECORDS
        }
        assert "Data Engineer" not in valid_careers
        assert "Data Analyst" in valid_careers
