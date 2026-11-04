from fastapi import APIRouter, Depends, Request

from app.bridge.runtime import BridgeRuntime
from app.deps import get_ai_provider, get_bridge, get_chat_service
from app.models.schemas import ChatRequest, ChatResponse
from app.routers.bridge import answer_or_http_error
from app.services.ai_client import AiProvider
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    if payload.grounded:
        # 業務データに基づく回答は必ずブリッジ経由(ACL前置フィルタ + 監査)。
        # 主体はブリッジの認証設定(api_key / trusted_header)で解決する。
        bridge: BridgeRuntime = get_bridge()
        p = bridge.resolver.resolve(request)
        r = await answer_or_http_error(bridge, p, payload.message, payload.session_id)
        return ChatResponse(
            session_id=payload.session_id, reply=r["answer"], provider=ai.name,
            history_length=r["history_length"], grounded=r["grounded"],
            citations=r["citations"], audit_id=r["audit_id"],
        )
    reply, history_len = await svc.send(payload.session_id, payload.message)
    return ChatResponse(
        session_id=payload.session_id,
        reply=reply,
        provider=ai.name,
        history_length=history_len,
    )
