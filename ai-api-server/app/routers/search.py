from fastapi import APIRouter, Depends

from app.deps import get_search_service
from app.models.schemas import SearchRequest, SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(payload: SearchRequest, svc: SearchService = Depends(get_search_service)):
    result = await svc.search(payload.query, payload.top_k)
    return result
