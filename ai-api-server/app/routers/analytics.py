from fastapi import APIRouter, Depends, Query

from app.deps import get_predictive_service
from app.models.schemas import ForecastResponse, PredictionResponse
from app.services.predictive_service import PredictiveService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/forecast", response_model=ForecastResponse)
def forecast_sales(
    months_ahead: int = Query(default=3, ge=1, le=12),
    svc: PredictiveService = Depends(get_predictive_service),
):
    return svc.forecast_sales(months_ahead)


@router.get("/reorder-predictions", response_model=PredictionResponse)
def reorder_predictions(svc: PredictiveService = Depends(get_predictive_service)):
    return svc.predict_reorders()
