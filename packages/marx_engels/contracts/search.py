"""Search-domain contracts frozen for V1 parallel development."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from marx_engels.contracts.base import ContractModel
from marx_engels.contracts.enums import (
    AuthorCode,
    ContentType,
    DatePrecision,
    SearchMode,
    SupportLabel,
)

Identifier = str


class SearchScope(ContractModel):
    corpus_ids: list[Identifier] = Field(min_length=1)
    edition_ids: list[Identifier] = Field(default_factory=list)
    volume_ids: list[Identifier] = Field(default_factory=list)
    work_ids: list[Identifier] = Field(default_factory=list)
    authors: list[AuthorCode] = Field(default_factory=list)
    content_types: list[ContentType] = Field(
        default_factory=lambda: [ContentType.MAIN_TEXT, ContentType.AUTHOR_NOTE]
    )

    @field_validator(
        "corpus_ids",
        "edition_ids",
        "volume_ids",
        "work_ids",
        "authors",
        "content_types",
    )
    @classmethod
    def reject_duplicates(cls, values: list[object]) -> list[object]:
        if len(values) != len(set(values)):
            raise ValueError("scope lists must not contain duplicates")
        return values


class SearchOptions(ContractModel):
    include_generated_summaries: bool = True
    include_counter_evidence: bool = True


class SearchRequest(ContractModel):
    query: str = Field(min_length=1, max_length=500)
    mode: SearchMode
    scope: SearchScope
    sort: Literal["relevance", "document_order"] | None = None
    cursor: str | None = Field(default=None, max_length=2048)
    page_size: int = Field(default=20, ge=1, le=100)
    options: SearchOptions = Field(default_factory=SearchOptions)

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain a non-whitespace character")
        return value

    @model_validator(mode="after")
    def validate_sort_for_mode(self) -> "SearchRequest":
        if self.sort == "document_order" and self.mode not in {
            SearchMode.EXACT,
            SearchMode.TIMELINE,
        }:
            raise ValueError("document_order sort is only valid for exact or timeline")
        return self


class Candidate(ContractModel):
    """Internal retrieval object; it intentionally contains no formal quotation."""

    evidence_id: Identifier
    retrieval_unit_ids: list[Identifier] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    exact_match_count: int | None = Field(default=None, ge=0)
    lexical_rank: int | None = Field(default=None, ge=1)
    lexical_score: float | None = None
    vector_rank: int | None = Field(default=None, ge=1)
    vector_score: float | None = None
    fusion_score: float | None = None
    rerank_score: float | None = None
    support_label: SupportLabel | None = None
    text_hash: str | None = None
    exclusion_reasons: list[str] = Field(default_factory=list)
    rank_reasons: list[str] = Field(default_factory=list)


class Evidence(ContractModel):
    evidence_id: Identifier
    verified_text: str = Field(min_length=1)
    content_type: ContentType
    author: str
    work_title: str
    corpus_name: str
    edition_label: str
    volume_no: int = Field(ge=1)
    work_date_start: str | None = None
    work_date_end: str | None = None
    date_precision: DatePrecision
    printed_pages: list[str] = Field(default_factory=list)
    pdf_pages: list[int] = Field(default_factory=list)
    prev_evidence_id: Identifier | None = None
    next_evidence_id: Identifier | None = None
    match_type: str
    support_label: SupportLabel | None = None
    rank_reasons: list[str] = Field(default_factory=list)
    exact_match_count: int | None = Field(default=None, ge=0)
    match_offsets: list[int] = Field(default_factory=list)


class ReleaseInfo(ContractModel):
    data_version: str
    index_version: str | None = None
    embedding_model: str | None = None
    released_at: str | None = None


class Warning(ContractModel):
    code: str
    message: str
    stage: str


class Insufficiency(ContractModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class SearchOverview(ContractModel):
    evidence_count: int = Field(ge=0)
    work_count: int = Field(ge=0)
    volume_count: int = Field(ge=0)
    result_note: str = "以下组织只基于列出的证据。"


class ResultGroup(ContractModel):
    group_id: str
    label: str
    group_type: str
    evidence_ids: list[Identifier] = Field(default_factory=list)
    summary: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    date_start: str | None = None
    date_end: str | None = None
    date_precision: DatePrecision | None = None


class SearchResponse(ContractModel):
    request_id: str
    mode: SearchMode
    query: str
    scope_snapshot: SearchScope
    release: ReleaseInfo
    overview: SearchOverview
    groups: list[ResultGroup] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    next_cursor: str | None = None
    insufficiency: Insufficiency | None = None
    warnings: list[Warning] = Field(default_factory=list)
    classification_notice: str | None = None
