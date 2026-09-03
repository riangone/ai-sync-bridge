from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_ai_provider, get_push_service
from app.models.schemas import (
    InsightResponse,
    PushCheckResponse,
    PushSubscribeResult,
    PushSubscription,
    PushSubscriptionCreate,
    PushUnsubscribeRequest,
)
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.push_service import PushService

router = APIRouter(prefix="/api/push", tags=["push"])


@router.post("/check", response_model=PushCheckResponse)
def check(svc: PushService = Depends(get_push_service)):
    """README 5.3節: POST /api/push/check。在庫異常検知(Inventory)とAR/AP高リスク滞留を
    アラートとして集約する。"""
    return svc.check()


# ---- AI解釈コメント (アラート集約そのものはルールベース。ここだけがオプトインでAIを使う) ----
@router.get("/check/insight", response_model=InsightResponse)
async def check_insight(
    svc: PushService = Depends(get_push_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    result = svc.check()
    comment = await insight_service.interpret_alerts(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)


@router.post("/subscribe", response_model=PushSubscribeResult)
def subscribe(payload: PushSubscriptionCreate, svc: PushService = Depends(get_push_service)):
    svc.subscribe(
        endpoint=payload.endpoint,
        p256dh=payload.p256dh,
        auth=payload.auth,
        device_name=payload.device_name,
    )
    return {"success": True}


@router.post("/unsubscribe", response_model=PushSubscribeResult)
def unsubscribe(payload: PushUnsubscribeRequest, svc: PushService = Depends(get_push_service)):
    if not svc.unsubscribe(payload.endpoint):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"success": True}


@router.get("/subscriptions", response_model=list[PushSubscription])
def list_subscriptions(svc: PushService = Depends(get_push_service)):
    return svc.list_subscriptions()
