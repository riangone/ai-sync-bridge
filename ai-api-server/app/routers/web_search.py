from fastapi import APIRouter, Depends

from app.deps import get_company_search_service, get_property_search_service
from app.models.schemas import (
    CompanyRegisterRequest,
    CompanyRegisterResponse,
    CompanySearchRequest,
    CompanySearchResponse,
    PropertyRegisterRequest,
    PropertyRegisterResponse,
    PropertySearchRequest,
    PropertySearchResponse,
)
from app.services.web_search_service import CompanySearchService, PropertySearchService

router = APIRouter(prefix="/api", tags=["web-search"])


@router.post("/company/search", response_model=CompanySearchResponse)
async def company_search(
    payload: CompanySearchRequest,
    svc: CompanySearchService = Depends(get_company_search_service),
):
    return await svc.search(payload.keyword)


@router.post("/company/register", response_model=CompanyRegisterResponse)
def company_register(
    payload: CompanyRegisterRequest,
    svc: CompanySearchService = Depends(get_company_search_service),
):
    return svc.register(payload.company_data)


@router.post("/property/search", response_model=PropertySearchResponse)
async def property_search(
    payload: PropertySearchRequest,
    svc: PropertySearchService = Depends(get_property_search_service),
):
    return await svc.search(payload.keyword)


@router.post("/property/register", response_model=PropertyRegisterResponse)
def property_register(
    payload: PropertyRegisterRequest,
    svc: PropertySearchService = Depends(get_property_search_service),
):
    return svc.register(payload.property_data)
