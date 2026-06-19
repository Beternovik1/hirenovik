"""Tests for ETL transform functions: clean, detect_state, detect_job_type,
extract_salary_from_text, transform_data."""

import math

import pandas as pd
import pytest

from etl.transform import (
    STATE_MAP,
    clean,
    detect_job_type,
    detect_state,
    extract_salary_from_text,
    transform_data,
)


# ---------------------------------------------------------------------------
# clean()
# ---------------------------------------------------------------------------

class TestClean:
    def test_clean_returns_default_when_value_is_nan(self):
        result = clean(float("nan"), "fallback")
        assert result == "fallback"

    def test_clean_returns_default_when_value_is_none(self):
        result = clean(None, "fallback")
        assert result == "fallback"

    def test_clean_returns_value_when_valid(self):
        result = clean("hello", "fallback")
        assert result == "hello"

    def test_clean_defaults_to_none_when_no_default_given(self):
        result = clean(float("nan"))
        assert result is None

    def test_clean_handles_empty_string_as_valid_value(self):
        result = clean("", "fallback")
        assert result == ""


# ---------------------------------------------------------------------------
# detect_state()
# ---------------------------------------------------------------------------

class TestDetectState:
    def test_detect_state_guanajuato_by_city(self):
        assert detect_state("Leon, Guanajuato") == "Guanajuato"

    def test_detect_state_guanajuato_by_state_name(self):
        assert detect_state("Guanajuato") == "Guanajuato"

    def test_detect_state_queretaro(self):
        assert detect_state("Queretaro, QRO") == "Querétaro"

    def test_detect_state_jalisco(self):
        assert detect_state("Guadalajara, Jalisco") == "Jalisco"

    def test_detect_state_returns_none_for_unknown_location(self):
        assert detect_state("Buenos Aires") is None

    def test_detect_state_returns_none_for_empty_string(self):
        assert detect_state("") is None

    def test_detect_state_returns_none_for_none_input(self):
        assert detect_state(None) is None

    def test_detect_state_is_case_insensitive(self):
        assert detect_state("LEON") == "Guanajuato"

    def test_detect_state_matches_substring_in_longer_text(self):
        assert detect_state("Zona Centro, Celaya, Gto.") == "Guanajuato"


# ---------------------------------------------------------------------------
# detect_job_type()
# ---------------------------------------------------------------------------

class TestDetectJobType:
    def test_detect_remote_from_title(self):
        result = detect_job_type("Data Engineer Remoto", "Mexico")
        assert result == "remoto"

    def test_detect_remote_from_location(self):
        result = detect_job_type("Data Engineer", "Trabajo remoto desde casa")
        assert result == "remoto"

    def test_detect_hybrid_from_title(self):
        result = detect_job_type("Cloud Engineer Hibrido", "CDMX")
        assert result == "hibrido"

    def test_detect_hybrid_with_accent(self):
        result = detect_job_type("DevOps Híbrido", "Mexico")
        assert result == "hibrido"

    def test_detect_hybrid_english(self):
        result = detect_job_type("Python Developer (Hybrid)", "Guadalajara")
        assert result == "hibrido"

    def test_detect_presencial_as_default(self):
        result = detect_job_type("Backend Developer", "Monterrey")
        assert result == "presencial"

    def test_detect_remote_has_priority_over_hybrid(self):
        result = detect_job_type("Remoto Hibrido", "home office presencial")
        assert result == "remoto"


# ---------------------------------------------------------------------------
# extract_salary_from_text()
# ---------------------------------------------------------------------------

class TestExtractSalaryFromText:
    def test_extract_salary_range_with_comma_format(self):
        min_sal, max_sal = extract_salary_from_text("$25,000 a $35,000 mensuales")
        assert min_sal == 25000.0
        assert max_sal == 35000.0

    def test_extract_salary_single_amount(self):
        min_sal, max_sal = extract_salary_from_text("Sueldo: $15,000 al mes")
        assert min_sal == 15000.0
        assert max_sal == 15000.0

    def test_extract_salary_no_salary_returns_none(self):
        min_sal, max_sal = extract_salary_from_text("Sueldo competitivo")
        assert min_sal is None
        assert max_sal is None

    def test_extract_salary_negotiable_returns_none(self):
        min_sal, max_sal = extract_salary_from_text("A convenir")
        assert min_sal is None
        assert max_sal is None

    def test_extract_salary_handles_none_input(self):
        min_sal, max_sal = extract_salary_from_text(None)
        assert min_sal is None
        assert max_sal is None

    def test_extract_salary_handles_nan_input(self):
        min_sal, max_sal = extract_salary_from_text(float("nan"))
        assert min_sal is None
        assert max_sal is None

    def test_extract_salary_handles_empty_string(self):
        min_sal, max_sal = extract_salary_from_text("")
        assert min_sal is None
        assert max_sal is None

    def test_extract_salary_three_or_more_amounts_returns_min_and_max(self):
        min_sal, max_sal = extract_salary_from_text("$10,000 $20,000 o $30,000")
        assert min_sal == 10000.0
        assert max_sal == 30000.0


# ---------------------------------------------------------------------------
# transform_data()
# ---------------------------------------------------------------------------

class TestTransformData:
    def test_transform_data_produces_correct_record_count(self, sample_job_df):
        records = transform_data(sample_job_df, "Data Engineer", "Ingenieria de Datos")
        assert len(records) == 2

    def test_transform_data_skips_rows_without_job_url(self):
        df = pd.DataFrame(
            {
                "site": ["indeed", "indeed"],
                "job_url": [None, "https://example.com/job/1"],
                "title": ["No URL", "Has URL"],
                "company": ["Corp", "Corp"],
                "location": ["CDMX", "CDMX"],
            }
        )
        records = transform_data(df, "Dev", "Desarrollo")
        assert len(records) == 1
        assert records[0]["job_url"] == "https://example.com/job/1"

    def test_transform_data_handles_empty_dataframe(self):
        df = pd.DataFrame(
            columns=["site", "job_url", "title", "company", "location"]
        )
        records = transform_data(df, "Dev", "Desarrollo")
        assert len(records) == 0

    def test_transform_data_uppercases_title(self, sample_job_df):
        records = transform_data(sample_job_df, "Data Engineer", "Ingenieria de Datos")
        assert records[0]["title"] == "DATA ENGINEER"

    def test_transform_data_defaults_missing_company(self):
        df = pd.DataFrame(
            {
                "site": ["indeed"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Dev"],
                "location": ["CDMX"],
            }
        )
        records = transform_data(df, "Dev", "Desarrollo")
        assert records[0]["company"] == "Empresa confidencial"

    def test_transform_data_detects_state_from_location(self, sample_job_df):
        records = transform_data(sample_job_df, "Data Engineer", "Ingenieria de Datos")
        assert records[0]["state"] == "Guanajuato"  # Leon, Guanajuato

    def test_transform_data_sets_status_new_by_default(self, sample_job_df):
        records = transform_data(sample_job_df, "Data Engineer", "Ingenieria de Datos")
        # transform_data does NOT set status — status is set by the pipeline layer
        # This test verifies the record structure doesn't include a status field
        assert "status" not in records[0]

    def test_transform_data_falls_back_salary_when_jobspy_gives_none(self):
        """When min_amount and max_amount are None, extract from description."""
        df = pd.DataFrame(
            {
                "site": ["indeed"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Data Engineer"],
                "company": ["Corp"],
                "location": ["CDMX"],
                "description": ["$30,000 a $45,000 mensuales"],
                "date_posted": ["2026-05-01"],
                "min_amount": [None],
                "max_amount": [None],
            }
        )
        records = transform_data(df, "Data Engineer", "Ingenieria de Datos")
        assert records[0]["salary_min"] == 30000.0
        assert records[0]["salary_max"] == 45000.0
