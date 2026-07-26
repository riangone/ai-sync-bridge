from fastapi import APIRouter, Depends, Query

from app.deps import get_ai_provider, get_predictive_service
from app.models.schemas import ForecastResponse, InsightResponse, PredictionResponse
from app.services import insight_service
from app.services.ai_client import AiProvider
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


# ---- AI解釈コメント (統計そのものはAI非依存のまま。ここだけがオプトインでAIを使う) ----
@router.get("/forecast/insight", response_model=InsightResponse)
async def forecast_insight(
    months_ahead: int = Query(default=3, ge=1, le=12),
    svc: PredictiveService = Depends(get_predictive_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    forecast = svc.forecast_sales(months_ahead)
    comment = await insight_service.interpret_forecast(ai, forecast)
    return InsightResponse(comment=comment, provider=ai.name)


@router.get("/reorder-predictions/insight", response_model=InsightResponse)
async def reorder_predictions_insight(
    svc: PredictiveService = Depends(get_predictive_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    predictions = svc.predict_reorders()
    comment = await insight_service.interpret_reorders(ai, predictions)
    return InsightResponse(comment=comment, provider=ai.name)
