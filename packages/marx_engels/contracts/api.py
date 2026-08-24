"""HTTP-facing contracts frozen for API V1."""

from typing import Literal

from pydantic import Field

from marx_engels.contracts.base import ContractModel
from marx_engels.contracts.enums import SearchMode
from marx_engels.contracts.search import Evidence, ReleaseInfo


class ErrorBody(ContractModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    retryable: bool = False


class ErrorResponse(ContractModel):
    request_id: str
    error: ErrorBody


class ModeSuggestionRequest(ContractModel):
    query: str = Field(min_length=1, max_length=500)


class ModeSuggestionResponse(ContractModel):
    suggested_mode: SearchMode | None
    confidence: float = Field(ge=0, le=1)
    requires_user_selection: bool
    allowed_modes: list[SearchMode]
    reason_code: str


class CorpusSummary(ContractModel):
    corpus_id: str
    display_name: str
    language: str
    release_status: str


class CorporaResponse(ContractModel):
    items: list[CorpusSummary] = Field(default_factory=list)


class ScopeNode(ContractModel):
    node_id: str
    node_type: Literal["corpus", "edition", "volume", "work", "author"]
    label: str
    release_status: str
    children: list["ScopeNode"] = Field(default_factory=list)


class ScopeTreeResponse(ContractModel):
    corpus_id: str
    data_version: str | None = None
    roots: list[ScopeNode] = Field(default_factory=list)


class ReleaseMetadataResponse(ContractModel):
    release: ReleaseInfo | None
    contract_version: Literal["v1"] = "v1"


class ContextItem(ContractModel):
    evidence: Evidence
    is_target: bool


class ContextResponse(ContractModel):
    target_evidence_id: str
    items: list[ContextItem]


class PdfLocationResponse(ContractModel):
    evidence_id: str
    asset_id: str
    viewer_url: str
    start_pdf_page: int = Field(ge=1)
    end_pdf_page: int = Field(ge=1)
    printed_pages: list[str]
    coordinates: list[float] | None = None


class FeedbackRequest(ContractModel):
    request_id: str | None = None
    evidence_id: str | None = None
    category: Literal[
        "ocr_error",
        "page_mismatch",
        "work_metadata_error",
        "author_error",
        "context_boundary_error",
        "irrelevant_result",
        "other",
    ]
    comment: str = Field(min_length=1, max_length=2000)
    client_context: dict[str, str] = Field(default_factory=dict)


class FeedbackResponse(ContractModel):
    feedback_id: str
    status: Literal["pending"] = "pending"


class HealthResponse(ContractModel):
    status: Literal["ok", "not_ready"]
    checks: dict[str, bool] = Field(default_factory=dict)
