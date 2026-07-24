from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_order_service
from app.models.schemas import Order, OrderCreate
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=list[Order])
def list_orders(svc: OrderService = Depends(get_order_service)):
    return svc.list()


@router.get("/{order_id}", response_model=Order)
def get_order(order_id: int, svc: OrderService = Depends(get_order_service)):
    o = svc.get(order_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return o


@router.post("", response_model=Order, status_code=201)
def create_order(payload: OrderCreate, svc: OrderService = Depends(get_order_service)):
    return svc.create(payload.model_dump())


@router.get("/by-customer/{customer_id}", response_model=list[Order])
def list_orders_by_customer(customer_id: int, svc: OrderService = Depends(get_order_service)):
    return svc.list_by_customer(customer_id)
