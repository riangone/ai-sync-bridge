from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_inventory_service
from app.models.schemas import InventoryAnomalyResponse, Product, ProductCreate, ProductUpdate
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


# 注意: /anomalies は /{product_id} より前に定義すること(FastAPIはパス定義順にマッチするため、
# 後ろに置くと "anomalies" が int パスパラメータとして解釈されて 422 になる)。
@router.get("/anomalies", response_model=InventoryAnomalyResponse)
def list_anomalies(svc: InventoryService = Depends(get_inventory_service)):
    return svc.anomalies()


@router.get("", response_model=list[Product])
def list_products(svc: InventoryService = Depends(get_inventory_service)):
    return svc.list()


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: int, svc: InventoryService = Depends(get_inventory_service)):
    p = svc.get(product_id)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return p


@router.post("", response_model=Product, status_code=201)
def create_product(payload: ProductCreate, svc: InventoryService = Depends(get_inventory_service)):
    return svc.create(payload.model_dump())


@router.put("/{product_id}", response_model=Product)
def update_product(product_id: int, payload: ProductUpdate, svc: InventoryService = Depends(get_inventory_service)):
    p = svc.update(product_id, payload.model_dump(exclude_unset=True))
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return p
