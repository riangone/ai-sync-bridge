from fastapi import APIRouter, Depends, HTTPException, Query
import httpx

from app.deps import get_ai_provider, get_cross_analysis_service, get_dynamic_analysis_service
from app.models.schemas import (
    CrossAnalysisReportMeta,
    CrossAnalysisResponse,
    DynamicAnalysisRequest,
    DynamicAnalysisResponse,
    InsightResponse,
)
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.cross_analysis_service import CrossAnalysisService
from app.services.dynamic_analysis_service import DynamicAnalysisService

router = APIRouter(prefix="/api/cross-analysis", tags=["cross-analysis"])


@router.get("/reports", response_model=list[CrossAnalysisReportMeta])
async def list_reports(svc: CrossAnalysisService = Depends(get_cross_analysis_service)):
    """フロント側が定型レポートのボタン一覧を動的に組み立てるためのメタ情報。"""
    return await svc.list_reports()


# ---- AI自動生成レポート(汎用集計エンジン) ----
# /generate, /generate/insight という固定パスは、下記の /{report} 系の動的パスより
# 前にルーティング宣言する必要がある(そうしないと report="generate" として
# /{report} 側にマッチしてしまう)。
@router.post("/generate", response_model=DynamicAnalysisResponse)
async def generate_report(
    body: DynamicAnalysisRequest,
    svc: DynamicAnalysisService = Depends(get_dynamic_analysis_service),
):
    try:
        return await svc.generate(body.question)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc


@router.get("/generate/insight", response_model=InsightResponse)
async def generate_report_insight(
    question: str = Query(...),
    svc: DynamicAnalysisService = Depends(get_dynamic_analysis_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    """既存の定型レポート(/{report}/insight)と同じGETベースのopt-in解釈エンドポイント。
    質問文からレポートを再生成した上で、summary+chart上位N件のみをAIに渡す
    (insight_service.interpret_cross_analysis は label/summary/chart の形さえ
    合っていれば定型レポートと汎用生成レポートの両方に使い回せる)。"""
    try:
        result = await svc.generate(question)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc
    comment = await insight_service.interpret_cross_analysis(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)


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
