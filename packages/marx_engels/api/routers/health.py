"""Liveness and readiness routes."""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from marx_engels.api.container import ApplicationContainer
from marx_engels.contracts import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse, operation_id="health_live")
async def live() -> HealthResponse:
    return HealthResponse(status="ok", checks={"process": True})


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    operation_id="health_ready",
)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    container: ApplicationContainer = request.app.state.container
    sqlite_ready = container.sqlite.healthcheck()
    checks = {"sqlite": sqlite_ready, "contract_v1": True}
    if not sqlite_ready:
        payload = HealthResponse(status="not_ready", checks=checks)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )
    return HealthResponse(status="ok", checks=checks)
