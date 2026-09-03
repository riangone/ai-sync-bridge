from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.deps import get_ocr_service
from app.models.schemas import OcrEntitiesResponse, OcrRegisterRequest, OcrRegisterResponse, OcrResult
from app.services.ocr_service import OcrService

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


@router.post("", response_model=OcrResult)
async def run_ocr(file: UploadFile = File(...), svc: OcrService = Depends(get_ocr_service)):
    content = await file.read()
    result = await svc.extract(file.filename, content, mime=file.content_type)
    return result


@router.get("/entities", response_model=OcrEntitiesResponse)
def ocr_entities(svc: OcrService = Depends(get_ocr_service)):
    """この業態(instance)でOCR結果のジャンプ/自動入力先として選べるエンティティ名一覧。
    フロント(panel-ocr.js)がテスト画像生成/フォーム遷移先の選択肢を組み立てるのに使う。"""
    return {"entities": svc.entities()}


@router.post("/register", response_model=OcrRegisterResponse)
def ocr_register(payload: OcrRegisterRequest, svc: OcrService = Depends(get_ocr_service)):
    """仕入先検索(/api/company/register)と同じ位置付け:
    OCRのfieldsを指定エンティティのレガシーフォームのフィールド名に正規化するだけで、
    DBには書き込まない。"""
    try:
        return svc.register(payload.fields, payload.entity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
