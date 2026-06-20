"""Tests for the salary prediction router and service layer."""

from unittest.mock import MagicMock

import numpy as np
import pytest


def _mock_xgboost_model() -> MagicMock:
    """Return an XGBoost Booster mock that predicts a fixed salary."""
    model = MagicMock()
    model.predict.return_value = np.array([42500.0])
    return model


def test_predict_salary_success(app, client):
    """POST /predict/salary returns a salary prediction."""
    model = _mock_xgboost_model()
    app.state.xgboost = model
    try:
        payload = {
            "seniority": 3,
            "modality": 0,
            "years_experience": 6,
            "has_python": 1,
            "has_aws": 1,
            "has_sql": 1,
            "has_docker": 1,
            "has_kubernetes": 1,
        }
        response = client.post("/predict/salary", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "predicted_salary_mid_mxn" in data
        assert data["currency"] == "MXN"
        assert "features_used" in data
        assert data["features_used"]["seniority"] == 3
        assert data["features_used"]["has_python"] == 1
    finally:
        app.state.xgboost = None


def test_predict_salary_defaults(app, client):
    """POST /predict/salary uses default values for missing fields."""
    model = _mock_xgboost_model()
    app.state.xgboost = model
    try:
        payload = {}
        response = client.post("/predict/salary", json=payload)
        assert response.status_code == 200
        data = response.json()
        # Default values: seniority=1, modality=2, years_experience=2
        assert data["features_used"]["seniority"] == 1
        assert data["features_used"]["modality"] == 2
        assert data["features_used"]["years_experience"] == 2
    finally:
        app.state.xgboost = None


def test_predict_salary_model_not_loaded(app, client):
    """POST /predict/salary returns 503 when model is unavailable."""
    app.state.xgboost = None
    payload = {"seniority": 2, "modality": 0, "years_experience": 4}
    response = client.post("/predict/salary", json=payload)
    assert response.status_code == 503