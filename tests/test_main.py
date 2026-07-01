"""Tests for the env-driven dispatch contract in ``src/main.py``.

These tests pin the external ``EXECUTION_MODE`` env contract so workflow/yaml
drift is caught: each mode must dispatch to the correct pipeline function with
the expected arguments, and the legacy ``cloud_extraction`` /
``local_enrichment_only`` modes must keep working.
"""

from unittest.mock import patch

import pytest

from main import main


@pytest.fixture
def stub_exports(monkeypatch):
    """Pin the multi-profile config exports so dispatch args are deterministic."""
    monkeypatch.setattr("main.DAILY_SCOUT_PROFILES", ["tech_mx", "industrial_irapuato_bajio"])
    monkeypatch.setattr("main.PROFILE_COOLDOWN_SECONDS", 60)
    yield


class TestMainDispatchContract:
    def test_multi_profile_mode_dispatches_with_profiles_and_cooldown(
        self, monkeypatch, stub_exports
    ):
        monkeypatch.setenv("EXECUTION_MODE", "multi_profile_cloud_extraction")
        with patch("main.run_multi_profile_cloud_extraction") as mock_multi, \
             patch("main.run_cloud_extraction_pipeline") as mock_cloud, \
             patch("main.run_local_enrichment_pipeline") as mock_local, \
             patch("main.run_pipeline") as mock_full, \
             patch("main.export_jobs") as mock_export:
            main()

        mock_multi.assert_called_once_with(
            profiles=["tech_mx", "industrial_irapuato_bajio"],
            cooldown_seconds=60,
        )
        # Other modes must NOT fire.
        mock_cloud.assert_not_called()
        mock_local.assert_not_called()
        mock_full.assert_not_called()
        mock_export.assert_called_once()

    def test_cloud_extraction_mode_preserved(self, monkeypatch):
        monkeypatch.setenv("EXECUTION_MODE", "cloud_extraction")
        with patch("main.run_cloud_extraction_pipeline") as mock_cloud, \
             patch("main.run_multi_profile_cloud_extraction") as mock_multi, \
             patch("main.export_jobs"):
            main()

        mock_cloud.assert_called_once()
        mock_multi.assert_not_called()

    def test_local_enrichment_only_mode_preserved(self, monkeypatch):
        monkeypatch.setenv("EXECUTION_MODE", "local_enrichment_only")
        with patch("main.run_local_enrichment_pipeline") as mock_local, \
             patch("main.run_multi_profile_cloud_extraction") as mock_multi, \
             patch("main.run_cloud_extraction_pipeline") as mock_cloud, \
             patch("main.export_jobs"):
            main()

        mock_local.assert_called_once()
        mock_multi.assert_not_called()
        mock_cloud.assert_not_called()

    def test_unknown_mode_runs_no_pipeline_and_skips_export(self, monkeypatch):
        monkeypatch.setenv("EXECUTION_MODE", "totally_bogus_mode")
        with patch("main.run_cloud_extraction_pipeline") as mock_cloud, \
             patch("main.run_multi_profile_cloud_extraction") as mock_multi, \
             patch("main.run_local_enrichment_pipeline") as mock_local, \
             patch("main.run_pipeline") as mock_full, \
             patch("main.export_jobs") as mock_export:
            main()

        # Unknown mode returns early: no pipeline function and no export.
        mock_cloud.assert_not_called()
        mock_multi.assert_not_called()
        mock_local.assert_not_called()
        mock_full.assert_not_called()
        mock_export.assert_not_called()

    def test_default_mode_when_env_unset_is_local_full(self, monkeypatch):
        monkeypatch.delenv("EXECUTION_MODE", raising=False)
        with patch("main.run_pipeline") as mock_full, \
             patch("main.run_local_enrichment_pipeline") as mock_local, \
             patch("main.run_multi_profile_cloud_extraction") as mock_multi, \
             patch("main.run_cloud_extraction_pipeline") as mock_cloud, \
             patch("main.include_linkedin_today", return_value=False), \
             patch("main.export_jobs"):
            main()

        mock_full.assert_called_once()
        mock_local.assert_called_once()
        mock_multi.assert_not_called()
        mock_cloud.assert_not_called()