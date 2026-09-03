from fastapi import APIRouter, Depends

from app.deps import get_assistant_service
from app.models.schemas import AssistRequest, AssistResponse
from app.services.assistant_service import AssistantService

router = APIRouter(prefix="/api/local-ai", tags=["local-ai"])


@router.post("/assist", response_model=AssistResponse)
async def assist(payload: AssistRequest, svc: AssistantService = Depends(get_assistant_service)):
    """README 5.3節: POST /api/local-ai/assist。画面コンテキストを認識する会話型アシスタント
    (panel-assistant.js)。"""
    result = await svc.assist(
        message=payload.message,
        screen_context=payload.screen_context,
        conversation_id=payload.conversation_id,
    )
    return result
