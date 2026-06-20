"""Service layer for XGBoost salary prediction.

Loads the trained model from disk (or S3) and exposes a predict function.
Model loading is deferred to ``load_xgboost()`` which is called once at
startup by the FastAPI lifespan.
"""

import logging
import os
from typing import Optional

import numpy as np

from src.api.schemas.prediction import SalaryFeatures, SalaryPrediction

logger = logging.getLogger(__name__)


def load_xgboost() -> Optional[object]:
    """Load the XGBoost model from the configured path.

    Supports two loading strategies:
    1. Local file path via ``XGBOOST_MODEL_PATH`` env var (a .json or
       binary XGBoost model file).
    2. If the path is empty, returns None (model unavailable).

    Returns:
        A loaded XGBoost Booster, or None if the model cannot be loaded.
    """
    try:
        import xgboost as xgb

        model_path = os.environ.get("XGBOOST_MODEL_PATH", "")
        if not model_path:
            logger.warning("XGBOOST_MODEL_PATH not set; prediction endpoint will return 503")
            return None

        if not os.path.exists(model_path):
            logger.warning("XGBoost model not found at %s", model_path)
            return None

        model = xgb.Booster()
        model.load_model(model_path)
        logger.info("XGBoost model loaded from %s", model_path)
        return model
    except Exception:  # noqa: BLE001 - optimistic load, log and continue
        logger.warning("XGBoost model unavailable; prediction will return 503")
        return None


# Feature column order must match the XGBoost training data exactly.
FEATURE_ORDER: list[str] = [
    "seniority", "modality", "years_experience",
] + [f"has_{kw}" for kw in [
    "python", "aws", "spark", "docker", "sql", "tensorflow",
    "kubernetes", "airflow", "dbt", "kafka", "azure", "gcp",
    "pytorch", "scikit", "pandas", "hadoop", "snowflake",
    "bigquery", "redshift", "terraform", "jenkins", "git",
    "linux", "mlops", "databricks", "powerbi", "tableau",
    "mongodb", "postgresql", "mysql", "react", "nodejs",
    "flask", "django", "fastapi", "go", "rust", "java", "scala",
]]


def predict_salary(model: object, features: SalaryFeatures) -> SalaryPrediction:
    """Run XGBoost prediction on a feature vector.

    Args:
        model: A loaded XGBoost Booster.
        features: Feature values matching the model input format.

    Returns:
        ``SalaryPrediction`` with the predicted salary midpoint in MXN.
    """
    feature_values = [getattr(features, name) for name in FEATURE_ORDER]
    feature_array = np.array([feature_values], dtype=np.float32)

    import xgboost as xgb

    dmatrix = xgb.DMatrix(feature_array, feature_names=FEATURE_ORDER)
    prediction = float(model.predict(dmatrix)[0])

    features_used = {name: value for name, value in zip(FEATURE_ORDER, feature_values)}
    return SalaryPrediction(
        predicted_salary_mid_mxn=round(prediction, 2),
        currency="MXN",
        features_used=features_used,
    )