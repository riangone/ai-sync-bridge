from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_notification_center
from app.models.schemas import Notification, NotificationCreate, NotificationMarkResult
from app.services.notification_service import NotificationCenter

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[Notification])
def list_notifications(
    unread_only: bool = False,
    limit: int = 100,
    center: NotificationCenter = Depends(get_notification_center),
):
    return center.list(unread_only=unread_only, limit=limit)


@router.get("/unread-count")
def unread_count(center: NotificationCenter = Depends(get_notification_center)):
    return {"unread_count": center.unread_count()}


@router.post("", response_model=Notification, status_code=201)
def create_notification(
    payload: NotificationCreate,
    center: NotificationCenter = Depends(get_notification_center),
):
    """手動通知の作成(管理画面やAI側からの任意アラート発行用)。"""
    return center.push(**payload.model_dump())


@router.post("/{notification_id}/read", response_model=NotificationMarkResult)
def mark_read(notification_id: int, center: NotificationCenter = Depends(get_notification_center)):
    if not center.mark_read(notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"marked": 1}


@router.post("/read-all", response_model=NotificationMarkResult)
def mark_all_read(center: NotificationCenter = Depends(get_notification_center)):
    return {"marked": center.mark_all_read()}
