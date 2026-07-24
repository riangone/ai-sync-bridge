from fastapi import APIRouter, Depends

from app.deps import get_admin_service
from app.models.schemas import AdminStats, AuditLogEntry
from app.services.admin_service import AdminService

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStats)
def stats(service: AdminService = Depends(get_admin_service)):
    return service.stats()


@router.get("/audit-log", response_model=list[AuditLogEntry])
def audit_log(limit: int = 100, service: AdminService = Depends(get_admin_service)):
    return service.audit_log.list(limit)


@router.post("/reset-demo-data", response_model=AdminStats)
def reset_demo_data(service: AdminService = Depends(get_admin_service)):
    return service.reset_demo_data()
