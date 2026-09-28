from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.deps import get_ocr_service
from app.models.schemas import OcrEntitiesResponse, OcrRegisterRequest, OcrRegisterResponse, OcrResult
from app.services.ocr_service import OcrService

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


@router.post("", response_model=OcrResult)
async def run_ocr(
    file: UploadFile = File(...),
    # doc_type="floorplan": instance=="realestate"専用。物件の間取り図/図面/現況写真を
    # 専用プロンプトで読み取る(ocr_service.OcrService.extract参照)。他instanceでは無視され
    # 従来通りの帳票OCRになる。省略時は従来通り"document"(帳票)。
    doc_type: str = Form("document"),
    svc: OcrService = Depends(get_ocr_service),
):
    content = await file.read()
    result = await svc.extract(file.filename, content, mime=file.content_type, doc_type=doc_type)
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
