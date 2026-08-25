"""Internal Clean/Raw page and structure models. Not public V1 contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from marx_engels.ingestion.models import TextLayer


class ContentKind(StrEnum):
    MAIN_TEXT = "main_text"
    AUTHOR_NOTE = "author_note"
    EDITOR_NOTE = "editor_note"
    FOOTNOTE = "footnote"
    TOC = "toc"
    HEADER = "header"
    FOOTER = "footer"
    INDEX = "index"


class PageKind(StrEnum):
    COVER = "cover"
    TOC = "toc"
    MAIN = "main"
    APPENDIX = "appendix"
    BLANK = "blank"


class MappingStatus(StrEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class PassageLifecycle(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    DRAFT = "draft"
    VERIFIED = "verified"


class ReleaseStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    PUBLISHED = "published"
    RETIRED = "retired"


class RawBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    kind: str
    text: str = ""
    bbox: list[float] | None = None
    text_level: int | None = None


class RawPageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volume_id: str
    volume_number: int
    pdf_page: int = Field(ge=1)
    extraction_run_id: str
    chunk_id: str | None = None
    chunk_page_index: int | None = None
    source_sha256: str
    artifact_kind: str = "content_list"
    artifact_name: str | None = None
    layer: TextLayer = TextLayer.RAW
    raw_text: str = ""
    blocks: list[RawBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False
    missing: bool = False
    duplicate: bool = False


class TransformationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_name: str
    rule_version: str
    input_location: str
    before_hash: str
    after_hash: str
    confidence: float
    warnings: list[str] = Field(default_factory=list)


class ContentSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: ContentKind
    text: str
    joinable: bool = True
    confidence: float = 1.0
    signals: list[str] = Field(default_factory=list)


class CleanPageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str
    volume_id: str
    volume_number: int
    pdf_page: int = Field(ge=1)
    clean_text: str
    text_hash: str
    spans: list[ContentSpan] = Field(default_factory=list)
    printed_page_label: str | None = None
    printed_page_number: int | None = None
    page_type: PageKind = PageKind.MAIN
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False
    layer: TextLayer = TextLayer.CLEAN
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    normalization_version: str = "nfc-v1"
    transformation_count: int = 0


class RetrievalUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_unit_id: str
    evidence_id: str
    order_no: int
    text: str
    text_hash: str


class PassageCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    work_id: str
    section_id: str
    volume_id: str
    content_type: ContentKind
    text: str
    text_hash: str
    pdf_page_start: int
    pdf_page_end: int
    start_offset: int | None = None
    end_offset: int | None = None
    prev_id: str | None = None
    next_id: str | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    release_status: ReleaseStatus = ReleaseStatus.DRAFT
    lifecycle: PassageLifecycle = PassageLifecycle.ACTIVE
    supersedes_id: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    rule_version: str = "structure-v1"
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False
    retrieval_units: list[RetrievalUnit] = Field(default_factory=list)


class WorkCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_id: str
    volume_id: str
    title: str
    pdf_page_start: int
    pdf_page_end: int
    signals: list[str] = Field(default_factory=list)
    confidence: float
    rule_version: str = "structure-v1"
    accepted: bool
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False


class SectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    work_id: str
    parent_id: str | None = None
    title: str
    pdf_page_start: int
    pdf_page_end: int
    signals: list[str] = Field(default_factory=list)
    confidence: float
    rule_version: str = "structure-v1"
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False


class PageMapRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str
    volume_id: str
    pdf_page: int
    page_type: PageKind
    printed_page_label: str | None = None
    printed_page_number: int | None = None
    mapping_status: MappingStatus = MappingStatus.CANDIDATE
    confidence: float = 0.0
    signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False


class PassagePageLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    page_id: str
    pdf_page: int
    printed_page_label: str | None = None
    order_no: int
    start_offset: int | None = None
    end_offset: int | None = None
    warnings: list[str] = Field(default_factory=list)
    manual_required: bool = False


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    code: str
    volume_id: str
    pdf_pages: list[int] = Field(default_factory=list)
    target_id: str | None = None
    message: str
    rule_version: str | None = None
