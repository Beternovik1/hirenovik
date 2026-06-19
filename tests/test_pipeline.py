"""Tests for the two-phase scraping architecture's status lifecycle.

Tests _map_phase1_records() which converts Phase 1 scraper DataFrames
into Job model dicts with status='PENDING_ENRICHMENT'.
"""

import os
from unittest.mock import patch

import pandas as pd
import pytest

from scrapers.pipeline import _map_phase1_records


class TestMapPhase1Records:
    def test_records_have_pending_enrichment_status(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Data Engineer"],
                "company": ["TechCorp"],
                "raw_location": ["Leon, GTO"],
                "job_type": ["Remoto"],
                "salary_min": [25000.0],
                "salary_max": [35000.0],
                "currency": ["MXN"],
                "date_posted": ["2026-05-01"],
            }
        )
        records = _map_phase1_records(df, "Data Engineer", "Ingenieria de Datos")
        assert len(records) == 1
        assert records[0]["status"] == "PENDING_ENRICHMENT"

    def test_description_is_always_none_in_phase1(self):
        """Phase 1 never visits detail pages, so description must be None."""
        df = pd.DataFrame(
            {
                "site": ["occ"],
                "job_url": ["https://example.com/job/1"],
                "title": ["DevOps"],
                "company": ["CloudCo"],
                "raw_location": ["Queretaro"],
                "job_type": ["Hibrido"],
            }
        )
        records = _map_phase1_records(df, "DevOps", "Infraestructura Cloud")
        assert records[0]["description"] is None

    def test_skips_records_with_null_job_url(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo", "computrabajo"],
                "job_url": [None, "https://example.com/job/1"],
                "title": ["Bad Record", "Good Record"],
                "company": ["Corp", "Corp"],
                "raw_location": ["CDMX", "CDMX"],
                "job_type": ["Remoto", "Remoto"],
            }
        )
        records = _map_phase1_records(df, "Dev", "Desarrollo")
        assert len(records) == 1
        assert records[0]["job_url"] == "https://example.com/job/1"

    def test_maps_job_type_to_lowercase(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Backend Dev"],
                "company": ["Corp"],
                "raw_location": ["CDMX"],
                "job_type": ["Remoto"],
            }
        )
        records = _map_phase1_records(df, "Backend", "Desarrollo")
        assert records[0]["job_type"] == "remoto"

    def test_maps_hybrid_with_accent_to_lowercase(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Fullstack"],
                "company": ["Corp"],
                "raw_location": ["CDMX"],
                "job_type": ["Híbrido"],
            }
        )
        records = _map_phase1_records(df, "Fullstack", "Desarrollo")
        assert records[0]["job_type"] == "hibrido"

    def test_detects_state_from_raw_location(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Data Analyst"],
                "company": ["Corp"],
                "raw_location": ["Irapuato, Guanajuato"],
                "job_type": ["Presencial"],
            }
        )
        records = _map_phase1_records(df, "Data Analyst", "BI")
        assert records[0]["state"] == "Guanajuato"

    def test_title_is_uppercased(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo"],
                "job_url": ["https://example.com/job/1"],
                "title": ["data engineer junior"],
                "company": ["Corp"],
                "raw_location": ["CDMX"],
                "job_type": ["Remoto"],
            }
        )
        records = _map_phase1_records(df, "Data Engineer", "Ingenieria de Datos")
        assert records[0]["title"] == "DATA ENGINEER JUNIOR"

    def test_default_company_for_missing(self):
        df = pd.DataFrame(
            {
                "site": ["occ"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Developer"],
                "raw_location": ["CDMX"],
                "job_type": ["Remoto"],
            }
        )
        records = _map_phase1_records(df, "Developer", "Desarrollo")
        assert records[0]["company"] == "Empresa confidencial"

    def test_empty_dataframe_returns_empty_list(self):
        df = pd.DataFrame(
            columns=["site", "job_url", "title", "company", "raw_location", "job_type"]
        )
        records = _map_phase1_records(df, "Dev", "Desarrollo")
        assert records == []

    def test_handles_dataframe_without_job_type_column(self):
        df = pd.DataFrame(
            {
                "site": ["computrabajo"],
                "job_url": ["https://example.com/job/1"],
                "title": ["Developer"],
                "company": ["Corp"],
                "raw_location": ["CDMX"],
            }
        )
        records = _map_phase1_records(df, "Developer", "Desarrollo")
        assert len(records) == 1
