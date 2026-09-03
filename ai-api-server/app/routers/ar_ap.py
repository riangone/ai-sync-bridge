from fastapi import APIRouter, Depends

from app.deps import get_ai_provider, get_ar_ap_service
from app.models.schemas import ArApAgingResponse, InsightResponse
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.ar_ap_service import ArApService

router = APIRouter(prefix="/api/ar-ap", tags=["ar-ap"])


@router.post("/aging", response_model=ArApAgingResponse)
def aging(svc: ArApService = Depends(get_ar_ap_service)):
    """README 5.3節: POST /api/ar-ap/aging。"""
    return svc.aging()


# ---- AI解釈コメント (エイジング集計そのものはルールベース。ここだけがオプトインでAIを使う) ----
@router.get("/aging/insight", response_model=InsightResponse)
async def aging_insight(
    svc: ArApService = Depends(get_ar_ap_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    result = svc.aging()
    comment = await insight_service.interpret_aging(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)
