"""FastAPI application factory and composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request

from marx_engels.api.container import ApplicationContainer, build_container
from marx_engels.api.error_handlers import install_error_handlers
from marx_engels.api.routers import evidence, feedback, health, meta, search
from marx_engels.settings import Settings

API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None,
    container: ApplicationContainer | None = None,
) -> FastAPI:
    resolved_container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = resolved_container
        yield

    app = FastAPI(
        title="Marx–Engels InsightMatch API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.container = resolved_container

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    install_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(meta.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(evidence.router, prefix=API_PREFIX)
    app.include_router(feedback.router, prefix=API_PREFIX)
    return app


app = create_app()
