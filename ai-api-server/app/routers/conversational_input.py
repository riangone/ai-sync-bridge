from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_conversational_input_service
from app.models.schemas import (
    ConversationalInputRegisterRequest,
    ConversationalInputRegisterResponse,
    ConversationalInputRequest,
    ConversationalInputResponse,
)
from app.services.conversational_input_service import ConversationalInputService

router = APIRouter(prefix="/api/conversational-input", tags=["conversational-input"])


@router.post("", response_model=ConversationalInputResponse)
async def conversational_input(
    payload: ConversationalInputRequest,
    svc: ConversationalInputService = Depends(get_conversational_input_service),
):
    """README 5.3節: POST /api/conversational-input。自然言語→フォームデータ変換
    (panel-conv-input.js)。"""
    try:
        result = await svc.parse(
            message=payload.message,
            target_screen=payload.target_screen,
            screen_context=payload.screen_context,
            conversation_id=payload.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/register", response_model=ConversationalInputRegisterResponse)
def conversational_input_register(
    payload: ConversationalInputRegisterRequest,
    svc: ConversationalInputService = Depends(get_conversational_input_service),
):
    """仕入先検索(/api/company/register)・OCR(/api/ocr/register)と同じ位置付け:
    抽出済みfieldsをtarget_screenのレガシーフォームのフィールド名に正規化するだけで、
    DBには書き込まない。"""
    try:
        return svc.register(payload.fields, payload.target_screen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
