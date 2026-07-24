from fastapi import APIRouter, Depends, UploadFile, File

from app.deps import get_ocr_service
from app.models.schemas import OcrResult
from app.services.ocr_service import OcrService

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


@router.post("", response_model=OcrResult)
async def run_ocr(file: UploadFile = File(...), svc: OcrService = Depends(get_ocr_service)):
    content = await file.read()
    result = svc.extract(file.filename, content)
    return result
