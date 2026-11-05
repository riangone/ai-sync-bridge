from fastapi import APIRouter, Depends

from app.deps import get_analysis_history_service
from app.models.schemas import AnalysisHistoryCreate, AnalysisHistoryEntry
from app.operator_auth import require_operator
from app.services.analysis_history_service import AnalysisHistoryService

# フロントから使っておらず、他の訪問者の質問が読めてしまうので読み書きとも運用者限定
router = APIRouter(prefix="/api/analysis-history", tags=["analysis-history"], dependencies=[Depends(require_operator)])


@router.get("", response_model=list[AnalysisHistoryEntry])
def list_history(
    type: str | None = None,
    limit: int = 100,
    svc: AnalysisHistoryService = Depends(get_analysis_history_service),
):
    """README 5.3節: GET /api/analysis-history。"""
    return svc.list(type_=type, limit=limit)


@router.post("", response_model=AnalysisHistoryEntry, status_code=201)
def create_history(
    payload: AnalysisHistoryCreate,
    svc: AnalysisHistoryService = Depends(get_analysis_history_service),
):
    """README 5.3節: POST /api/analysis-history。他の分析系エンドポイントの
    質問(query)/結果(result)を後から振り返れるよう保存する(自動連携ではなく明示保存)。"""
    return svc.create(type_=payload.type, query=payload.query, result=payload.result)
