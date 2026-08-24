"""Mode suggestion and search routes."""

from fastapi import APIRouter, Request

from marx_engels.api.container import ApplicationContainer
from marx_engels.api.request_context import request_id
from marx_engels.contracts import (
    ErrorResponse,
    ModeSuggestionRequest,
    ModeSuggestionResponse,
    SearchRequest,
    SearchResponse,
)
from marx_engels.pipelines.query_router import suggest_mode

router = APIRouter(tags=["search"])


@router.post(
    "/query-mode/suggest",
    response_model=ModeSuggestionResponse,
    operation_id="suggest_query_mode",
)
async def query_mode(payload: ModeSuggestionRequest) -> ModeSuggestionResponse:
    return suggest_mode(payload.query)


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={400: {"model": ErrorResponse}, 501: {"model": ErrorResponse}},
    operation_id="search",
)
async def search(payload: SearchRequest, request: Request) -> SearchResponse:
    container: ApplicationContainer = request.app.state.container
    pipeline = container.pipelines.get(payload.mode)
    return await pipeline.execute(payload, request_id(request))
