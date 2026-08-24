"""Evidence routes are present but intentionally unimplemented in the baseline."""

from fastapi import APIRouter, Query

from marx_engels.contracts import ContextResponse, ErrorResponse, Evidence, PdfLocationResponse
from marx_engels.errors import DomainError

router = APIRouter(prefix="/evidence", tags=["evidence"])


def unavailable(evidence_id: str) -> DomainError:
    return DomainError(
        "EVIDENCE_NOT_AVAILABLE",
        "Evidence is not available in the current published release.",
        details={"evidence_id": evidence_id},
    )


@router.get(
    "/{evidence_id}",
    response_model=Evidence,
    responses={404: {"model": ErrorResponse}},
    operation_id="get_evidence",
)
async def get_evidence(evidence_id: str) -> Evidence:
    raise unavailable(evidence_id)


@router.get(
    "/{evidence_id}/context",
    response_model=ContextResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="get_evidence_context",
)
async def get_context(
    evidence_id: str,
    before: int = Query(default=1, ge=0, le=3),
    after: int = Query(default=1, ge=0, le=3),
) -> ContextResponse:
    del before, after
    raise unavailable(evidence_id)


@router.get(
    "/{evidence_id}/pdf-location",
    response_model=PdfLocationResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="get_evidence_pdf_location",
)
async def get_pdf_location(evidence_id: str) -> PdfLocationResponse:
    raise unavailable(evidence_id)
