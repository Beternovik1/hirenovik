"""Service layer for XGBoost salary prediction.

Loads the trained model from disk (or S3) and exposes a predict function.
Model loading is deferred to ``load_xgboost()`` which is called once at
startup by the FastAPI lifespan.
"""

import logging
import os
from typing import Optional

import numpy as np

from src.api.schemas.prediction import KEYWORD_FEATURES, SalaryFeatures, SalaryPrediction

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
] + [f"has_{kw}" for kw in KEYWORD_FEATURES]


def _skills_to_features(
    seniority: int,
    modality: int,
    years_experience: int,
    skills: list[str],
) -> dict[str, int]:
    """Convert a skills list into a 41-element feature dict.

    The three numeric features are passed through unchanged. Each known
    keyword in KEYWORD_FEATURES is mapped to a binary ``has_<kw>`` flag.
    Unknown skills are silently ignored.

    Args:
        seniority: Seniority level (0-3).
        modality: Work modality (0-2).
        years_experience: Years of experience (0-6).
        skills: List of technology skill names (case-insensitive).

    Returns:
        Dict with all 41 feature names mapped to integer values.
    """
    skill_set = {s.lower() for s in skills}
    features: dict[str, int] = {
        "seniority": seniority,
        "modality": modality,
        "years_experience": years_experience,
    }
    for kw in KEYWORD_FEATURES:
        features[f"has_{kw}"] = 1 if kw in skill_set else 0
    return features


def predict_salary(model: object, features: SalaryFeatures) -> SalaryPrediction:
    """Run XGBoost prediction on a feature vector.

    Converts the human-friendly ``skills`` list into the 41-element binary
    feature vector expected by the model, then runs inference.

    Args:
        model: A loaded XGBoost Booster.
        features: Salary features with seniority, modality, years_experience,
            and a skills list.

    Returns:
        ``SalaryPrediction`` with the predicted salary midpoint in MXN.
    """
    all_features = _skills_to_features(
        features.seniority, features.modality, features.years_experience, features.skills
    )
    feature_values = [all_features[name] for name in FEATURE_ORDER]
    feature_array = np.array([feature_values], dtype=np.float32)

    import xgboost as xgb

    dmatrix = xgb.DMatrix(feature_array, feature_names=FEATURE_ORDER)
    prediction = float(model.predict(dmatrix)[0])

    return SalaryPrediction(
        predicted_salary_mid_mxn=round(prediction, 2),
        currency="MXN",
        features_used=all_features,
    )