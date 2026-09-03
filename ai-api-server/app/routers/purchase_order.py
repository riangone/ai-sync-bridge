from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_ai_provider, get_purchase_order_service
from app.models.schemas import (
    GoodsReceiptRequest,
    InsightResponse,
    PurchaseOrder,
    PurchaseOrderCreate,
    PurchaseOrderProposalResponse,
    SupplierEvaluationResponse,
)
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.purchase_order_service import PurchaseOrderService

router = APIRouter(prefix="/api/purchase-order", tags=["purchase-order"])


# 固定パス(propose/propose/insight/supplier-evaluation)は inventory.py と同じ理由で
# "/{purchase_order_id}" 系より前に定義する。
@router.get("/propose", response_model=PurchaseOrderProposalResponse)
def propose(svc: PurchaseOrderService = Depends(get_purchase_order_service)):
    return svc.propose()


# ---- AI解釈コメント (発注提案そのものはルールベース。ここだけがオプトインでAIを使う) ----
@router.get("/propose/insight", response_model=InsightResponse)
async def propose_insight(
    svc: PurchaseOrderService = Depends(get_purchase_order_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    proposal = svc.propose()
    comment = await insight_service.interpret_purchase_proposal(ai, proposal)
    return InsightResponse(comment=comment, provider=ai.name)


@router.get("/supplier-evaluation", response_model=SupplierEvaluationResponse)
def supplier_evaluation(svc: PurchaseOrderService = Depends(get_purchase_order_service)):
    return svc.evaluate_suppliers()


@router.post("/goods-receipt", response_model=PurchaseOrder)
def goods_receipt(payload: GoodsReceiptRequest, svc: PurchaseOrderService = Depends(get_purchase_order_service)):
    try:
        return svc.receive_goods(payload.purchase_order_id, payload.received_qty)
    except ValueError:
        raise HTTPException(status_code=404, detail="Purchase order not found")


@router.get("", response_model=list[PurchaseOrder])
def list_purchase_orders(svc: PurchaseOrderService = Depends(get_purchase_order_service)):
    return svc.list()


@router.get("/{purchase_order_id}", response_model=PurchaseOrder)
def get_purchase_order(purchase_order_id: int, svc: PurchaseOrderService = Depends(get_purchase_order_service)):
    po = svc.get(purchase_order_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


@router.post("", response_model=PurchaseOrder, status_code=201)
def create_purchase_order(payload: PurchaseOrderCreate, svc: PurchaseOrderService = Depends(get_purchase_order_service)):
    return svc.create(payload.model_dump())
