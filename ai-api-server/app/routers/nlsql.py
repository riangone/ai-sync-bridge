import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_nlsql_service
from app.models.schemas import NLSQLQueryRequest, NLSQLQueryResponse
from app.services.nlsql_service import NLSQLService

router = APIRouter(prefix="/api/nlsql", tags=["nlsql"])


@router.post("/query", response_model=NLSQLQueryResponse)
async def nlsql_query(
    body: NLSQLQueryRequest,
    service: NLSQLService = Depends(get_nlsql_service),
):
    """自然言語→構造化フィルタ検索(5.4.11差分実装)。生SQLは一切使わない。詳細は
    nlsql_service.py のモジュールdocstring参照。"""
    try:
        return await service.query(body.entity, body.question)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, f"unknown entity: {body.entity}") from exc
        raise HTTPException(502, f"legacy system error: {exc}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"legacy system unreachable: {exc}") from exc
