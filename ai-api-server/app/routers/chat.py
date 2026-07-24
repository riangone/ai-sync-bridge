from fastapi import APIRouter, Depends

from app.deps import get_chat_service, get_ai_provider
from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.ai_client import AiProvider

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    svc: ChatService = Depends(get_chat_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    reply, history_len = await svc.send(payload.session_id, payload.message)
    return ChatResponse(
        session_id=payload.session_id,
        reply=reply,
        provider=ai.name,
        history_length=history_len,
    )
