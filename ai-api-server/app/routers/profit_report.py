from fastapi import APIRouter, Depends

from app.deps import get_ai_provider, get_profit_report_service
from app.models.schemas import InsightResponse, ProfitReportResponse
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.profit_report_service import ProfitReportService

router = APIRouter(prefix="/api/profit-report", tags=["profit-report"])


@router.post("/report", response_model=ProfitReportResponse)
def report(period: str | None = None, svc: ProfitReportService = Depends(get_profit_report_service)):
    """README 5.3節: POST /api/profit-report/report。period(YYYY-MM)は任意のクエリパラメータ。"""
    return svc.report(period)


# ---- AI解釈コメント (粗利集計そのものはルールベース。ここだけがオプトインでAIを使う) ----
@router.get("/report/insight", response_model=InsightResponse)
async def report_insight(
    period: str | None = None,
    svc: ProfitReportService = Depends(get_profit_report_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    result = svc.report(period)
    comment = await insight_service.interpret_profit_report(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)
