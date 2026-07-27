from fastapi import APIRouter, Depends, HTTPException
import httpx

from app.deps import get_ai_provider, get_cross_analysis_service
from app.models.schemas import CrossAnalysisReportMeta, CrossAnalysisResponse, InsightResponse
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.cross_analysis_service import CrossAnalysisService

router = APIRouter(prefix="/api/cross-analysis", tags=["cross-analysis"])


@router.get("/reports", response_model=list[CrossAnalysisReportMeta])
async def list_reports(svc: CrossAnalysisService = Depends(get_cross_analysis_service)):
    """フロント側が定型レポートのボタン一覧を動的に組み立てるためのメタ情報。"""
    return await svc.list_reports()


@router.get("/{report}", response_model=CrossAnalysisResponse)
async def run_report(report: str, svc: CrossAnalysisService = Depends(get_cross_analysis_service)):
    try:
        return await svc.run(report)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc


# ---- AI解釈コメント (集計そのものはAI非依存。ここだけがオプトインでAIを使う) ----
@router.get("/{report}/insight", response_model=InsightResponse)
async def report_insight(
    report: str,
    svc: CrossAnalysisService = Depends(get_cross_analysis_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    try:
        result = await svc.run(report)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc
    comment = await insight_service.interpret_cross_analysis(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)
