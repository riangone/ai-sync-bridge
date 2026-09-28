import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_ai_provider, get_realestate_advisory_service
from app.models.schemas import (
    CommissionCheckRequest,
    CommissionCheckResponse,
    InsightResponse,
    ValuationRequest,
    ValuationResponse,
    ViewingConflictResponse,
)
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.realestate_advisory_service import RealestateAdvisoryService

router = APIRouter(prefix="/api/realestate", tags=["realestate"])


# ---- 査定AI(comparable物件の㎡単価統計による想定成約価格帯) ----
@router.post("/valuation", response_model=ValuationResponse)
async def valuation(
    body: ValuationRequest,
    svc: RealestateAdvisoryService = Depends(get_realestate_advisory_service),
):
    try:
        return await svc.valuation(body.property_type, body.building_area, body.land_area, body.address_keyword)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc


@router.get("/valuation/insight", response_model=InsightResponse)
async def valuation_insight(
    property_type: str | None = Query(None),
    building_area: float | None = Query(None),
    land_area: float | None = Query(None),
    address_keyword: str | None = Query(None),
    svc: RealestateAdvisoryService = Depends(get_realestate_advisory_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    """cross-analysis/generate/insight と同じくGETベースのオプトイン解釈エンドポイント
    (質問/条件からレポートを再生成した上でAIに渡す)。ctx.runInsight(GET専用)からそのまま
    呼べるよう、他の/insight系と同様にQueryパラメータのみで完結させる。"""
    try:
        result = await svc.valuation(property_type, building_area, land_area, address_keyword)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc
    comment = await insight_service.interpret_valuation(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)


# ---- 宅建業法 仲介手数料上限チェック(速算式) ----
@router.post("/commission-check", response_model=CommissionCheckResponse)
def commission_check(
    body: CommissionCheckRequest,
    svc: RealestateAdvisoryService = Depends(get_realestate_advisory_service),
):
    return svc.commission_check(body.contract_amount, body.requested_amount)


@router.get("/commission-check/insight", response_model=InsightResponse)
async def commission_check_insight(
    contract_amount: float = Query(...),
    requested_amount: float | None = Query(None),
    svc: RealestateAdvisoryService = Depends(get_realestate_advisory_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    result = svc.commission_check(contract_amount, requested_amount)
    comment = await insight_service.interpret_commission_check(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)


# ---- 内見(Viewing)日程重複/エージェント過密検知(inventory anomaliesと同じくAI非依存) ----
@router.get("/viewing-conflicts", response_model=ViewingConflictResponse)
async def viewing_conflicts(svc: RealestateAdvisoryService = Depends(get_realestate_advisory_service)):
    try:
        return await svc.viewing_conflicts()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc
