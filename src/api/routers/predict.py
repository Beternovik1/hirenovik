"""Router for salary prediction endpoint.

Uses the XGBoost model loaded at startup. Returns HTTP 503 when the
model is not available.
"""

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas.prediction import SalaryFeatures, SalaryPrediction
from src.api.services import predict_service

router = APIRouter()


@router.post("/salary", response_model=SalaryPrediction)
def predict_salary(
    features: SalaryFeatures,
    request: Request,
) -> SalaryPrediction:
    """Predict salary midpoint in MXN from a 41-feature vector."""
    model = request.app.state.xgboost
    if model is None:
        raise HTTPException(
            status_code=503,
            detail="XGBoost model not loaded; set XGBOOST_MODEL_PATH to enable predictions",
        )
    return predict_service.predict_salary(model, features)