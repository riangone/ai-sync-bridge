from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_ai_provider, get_recommend_service
from app.models.schemas import InsightResponse, RecommendRequest, RecommendResponse
from app.services import insight_service
from app.services.ai_client import AiProvider
from app.services.recommend_service import RecommendService

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post("/recommend", response_model=RecommendResponse)
def recommend(payload: RecommendRequest, svc: RecommendService = Depends(get_recommend_service)):
    try:
        return svc.recommend(
            payload.table_name,
            payload.id,
            payload.max_results,
            payload.include_explanation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- AI解釈コメント (類似度計算そのものはAI非依存。ここだけがオプトインでAIを使う) ----
@router.get("/recommend/insight", response_model=InsightResponse)
async def recommend_insight(
    table_name: str = Query(...),
    id: int = Query(...),
    max_results: int = Query(default=5),
    svc: RecommendService = Depends(get_recommend_service),
    ai: AiProvider = Depends(get_ai_provider),
):
    try:
        result = svc.recommend(table_name, id, max_results, include_explanation=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    comment = await insight_service.interpret_recommend(ai, result)
    return InsightResponse(comment=comment, provider=ai.name)
