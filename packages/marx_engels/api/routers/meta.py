"""Corpus and release metadata routes."""

from fastapi import APIRouter

from marx_engels.contracts import (
    CorporaResponse,
    ErrorResponse,
    ReleaseMetadataResponse,
    ScopeTreeResponse,
)
from marx_engels.errors import DomainError

router = APIRouter(tags=["metadata"])


@router.get("/corpora", response_model=CorporaResponse, operation_id="list_corpora")
async def list_corpora() -> CorporaResponse:
    return CorporaResponse(items=[])


@router.get(
    "/corpora/{corpus_id}/scope-tree",
    response_model=ScopeTreeResponse,
    responses={404: {"model": ErrorResponse}},
    operation_id="get_corpus_scope_tree",
)
async def scope_tree(corpus_id: str) -> ScopeTreeResponse:
    raise DomainError(
        "CORPUS_NOT_FOUND",
        "Corpus is not available in the current published release.",
        details={"corpus_id": corpus_id},
    )


@router.get(
    "/meta/release",
    response_model=ReleaseMetadataResponse,
    operation_id="get_release_metadata",
)
async def release_metadata() -> ReleaseMetadataResponse:
    return ReleaseMetadataResponse(release=None)
