from fastapi import APIRouter, Depends

from app.deps import get_admin_service, get_ai_provider
from app.models.schemas import AdminStats, AuditLogEntry, InsightResponse
from app.services import insight_service
from app.services.admin_service import AdminService
from app.services.ai_client import AiProvider

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStats)
def stats(service: AdminService = Depends(get_admin_service)):
    return service.stats()


@router.get("/stats/insight", response_model=InsightResponse)
async def stats_insight(
    service: AdminService = Depends(get_admin_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    comment = await insight_service.interpret_admin_stats(ai, service.stats())
    return InsightResponse(comment=comment, provider=ai.name)


@router.get("/audit-log", response_model=list[AuditLogEntry])
def audit_log(limit: int = 100, service: AdminService = Depends(get_admin_service)):
    return service.audit_log.list(limit)


@router.post("/reset-demo-data", response_model=AdminStats)
def reset_demo_data(service: AdminService = Depends(get_admin_service)):
    return service.reset_demo_data()
