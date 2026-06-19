"""Shared fixtures for Hirenovik tests."""

import pandas as pd
import pytest


@pytest.fixture
def sample_job_df() -> pd.DataFrame:
    """Minimal valid DataFrame matching JobSpy scraper output columns."""
    return pd.DataFrame(
        {
            "site": ["indeed", "indeed"],
            "job_url": [
                "https://example.com/job/1",
                "https://example.com/job/2",
            ],
            "title": ["Data Engineer", "Cloud Engineer"],
            "company": ["TechCorp", "CloudCo"],
            "location": ["Leon, Guanajuato", "Queretaro"],
            "description": [
                "Python AWS Spark $25,000 a $35,000 mensuales",
                "Azure Kubernetes Docker remoto $50,000",
            ],
            "date_posted": ["2026-05-01", "2026-05-02"],
            "min_amount": [25000.0, 50000.0],
            "max_amount": [35000.0, 50000.0],
            "currency": ["MXN", "MXN"],
            "job_type": ["remoto", "hibrido"],
        }
    )
