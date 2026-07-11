"""Tests for the two-phase scraping architecture's status lifecycle.

Tests _map_phase1_records() which converts Phase 1 scraper DataFrames
into Job model dicts with status='PENDING_ENRICHMENT'.
"""

import os
from unittest.mock import patch

import pandas as pd
import pytest

from scrapers.pipeline import _map_phase1_records, _filter_occ_by_alert_geography
from notifications.profiles import INDUSTRIAL_IRAPUATO_BAJIO_PROFILE


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


# ---------------------------------------------------------------------------
# OCC Industrial Bajío alert-geography filtering (Phase 1 insert gate)
# ---------------------------------------------------------------------------


_ALERT_NICHE = "Industrial Bajío"
_ALERT_CITIES = INDUSTRIAL_IRAPUATO_BAJIO_PROFILE.allowed_cities


def _occ_df(locations):
    """Build a minimal OCC scraper DataFrame with the given raw_location rows."""
    return pd.DataFrame(
        {
            "site": ["occ"] * len(locations),
            "job_url": [f"https://example.com/job/{i}" for i in range(len(locations))],
            "title": ["Operador de Producción"] * len(locations),
            "company": ["Industrias Bajío"] * len(locations),
            "raw_location": locations,
            "job_type": ["Presencial"] * len(locations),
        }
    )


class TestFilterOccAlertGeography:
    def test_industrial_bajio_keeps_celaya_gua_mx(self):
        df = _occ_df(["Celaya, GUA, MX"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert len(kept) == 1
        assert kept.iloc[0]["raw_location"] == "Celaya, GUA, MX"

    def test_industrial_bajio_keeps_leon_guanajuato(self):
        df = _occ_df(["León, Guanajuato"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert len(kept) == 1
        assert kept.iloc[0]["raw_location"] == "León, Guanajuato"

    def test_industrial_bajio_drops_tizayuca_hidalgo(self):
        df = _occ_df(["Tizayuca, Hidalgo"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert kept.empty

    def test_industrial_bajio_drops_chihuahua(self):
        df = _occ_df(["Chihuahua, Chihuahua"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert kept.empty

    def test_industrial_bajio_drops_miguel_hidalgo_cdmx(self):
        df = _occ_df(["Miguel Hidalgo, Ciudad de México"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert kept.empty

    def test_industrial_bajio_mixed_locations_keeps_only_geography(self):
        df = _occ_df(
            [
                "Celaya, GUA, MX",
                "Tizayuca, Hidalgo",
                "León, Guanajuato",
                "Chihuahua, Chihuahua",
                "Irapuato, Guanajuato",
                "Miguel Hidalgo, Ciudad de México",
            ]
        )
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert list(kept["raw_location"]) == [
            "Celaya, GUA, MX",
            "León, Guanajuato",
            "Irapuato, Guanajuato",
        ]

    def test_non_alert_niche_is_not_filtered(self):
        # Tech/general niche must keep nationwide rows (all-Mexico behaviour).
        df = _occ_df(["Tizayuca, Hidalgo", "Celaya, GUA, MX"])
        kept = _filter_occ_by_alert_geography(df, "Desarrollo", _ALERT_CITIES)
        assert len(kept) == 2

    def test_non_alert_niche_with_none_cities_is_not_filtered(self):
        df = _occ_df(["Monterrey, Nuevo León", "Tijuana, Baja California"])
        kept = _filter_occ_by_alert_geography(df, "tech_mx", ())
        assert len(kept) == 2

    def test_alert_niche_empty_cities_skips_filter_to_avoid_dropping_all(self):
        # Missing alert profile -> empty allowed_cities. Fail safe: keep all
        # rows rather than silently emptying the OCC insert.
        df = _occ_df(["Celaya, GUA, MX", "Tizayuca, Hidalgo"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, ())
        assert len(kept) == 2

    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame(columns=["site", "job_url", "raw_location"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert kept.empty

    def test_filter_does_not_mutate_input_dataframe(self):
        df = _occ_df(["Celaya, GUA, MX", "Tizayuca, Hidalgo"])
        original_len = len(df)
        _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        assert len(df) == original_len
        assert list(df["raw_location"]) == ["Celaya, GUA, MX", "Tizayuca, Hidalgo"]

    def test_kept_rows_feed_map_phase1_records_successfully(self):
        # Integration guard: the filtered DataFrame must still map cleanly.
        df = _occ_df(["Celaya, GUA, MX", "Tizayuca, Hidalgo"])
        kept = _filter_occ_by_alert_geography(df, _ALERT_NICHE, _ALERT_CITIES)
        records = _map_phase1_records(kept, "Operador", _ALERT_NICHE)
        assert len(records) == 1
        assert records[0]["raw_location"] == "Celaya, GUA, MX"
        assert records[0]["industry_niche"] == _ALERT_NICHE
        assert records[0]["status"] == "PENDING_ENRICHMENT"
