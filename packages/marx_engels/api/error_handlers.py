"""Map domain and validation failures to the frozen HTTP error contract."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from marx_engels.api.request_context import request_id
from marx_engels.contracts import ErrorBody, ErrorResponse
from marx_engels.errors import DomainError

STATUS_BY_CODE = {
    "INVALID_REQUEST": 400,
    "MODE_SELECTION_REQUIRED": 400,
    "INVALID_SCOPE": 400,
    "CORPUS_NOT_FOUND": 404,
    "EVIDENCE_NOT_AVAILABLE": 404,
    "PIPELINE_NOT_IMPLEMENTED": 501,
    "STORAGE_NOT_CONFIGURED": 501,
    "STALE_CURSOR": 409,
    "RELEASE_MISMATCH": 409,
    "QUERY_TOO_LONG": 422,
    "RATE_LIMITED": 429,
    "SQLITE_UNAVAILABLE": 503,
    "VECTOR_INDEX_UNAVAILABLE": 503,
    "SEARCH_TIMEOUT": 504,
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        payload = ErrorResponse(
            request_id=request_id(request),
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                retryable=exc.retryable,
            ),
        )
        return JSONResponse(
            status_code=STATUS_BY_CODE.get(exc.code, 500),
            content=payload.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()
        ]
        payload = ErrorResponse(
            request_id=request_id(request),
            error=ErrorBody(
                code="INVALID_REQUEST",
                message="Request validation failed.",
                details={"errors": safe_errors},
            ),
        )
        return JSONResponse(status_code=400, content=payload.model_dump(mode="json"))
