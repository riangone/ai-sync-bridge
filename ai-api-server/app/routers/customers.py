from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_customer_service
from app.models.schemas import Customer, CustomerCreate, CustomerUpdate
from app.operator_auth import require_operator
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=list[Customer])
def list_customers(svc: CustomerService = Depends(get_customer_service)):
    return svc.list()


@router.get("/{customer_id}", response_model=Customer)
def get_customer(customer_id: int, svc: CustomerService = Depends(get_customer_service)):
    c = svc.get(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


# 書き込みは公開デモのパネルから使っていないので運用者限定(tests/test_public_surface.py)
@router.post("", response_model=Customer, status_code=201, dependencies=[Depends(require_operator)])
def create_customer(payload: CustomerCreate, svc: CustomerService = Depends(get_customer_service)):
    return svc.create(payload.model_dump())


@router.put("/{customer_id}", response_model=Customer, dependencies=[Depends(require_operator)])
def update_customer(customer_id: int, payload: CustomerUpdate, svc: CustomerService = Depends(get_customer_service)):
    c = svc.update(customer_id, payload.model_dump(exclude_unset=True))
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


@router.delete("/{customer_id}", status_code=204, dependencies=[Depends(require_operator)])
def delete_customer(customer_id: int, svc: CustomerService = Depends(get_customer_service)):
    if not svc.delete(customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
