"""Internal source-registration models. These are not public V1 contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceStatus(StrEnum):
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    PREFLIGHT_FAILED = "preflight_failed"
    READY = "ready"
    SPLIT_REQUIRED = "split_required"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    FAILED = "failed"


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_record_id: str
    corpus_id: str
    edition_id: str
    volume_id: str
    volume_number: int = Field(ge=1, le=10)
    file_name: str = Field(min_length=1)
    source_uri: str = Field(pattern=r"^internal://")
    file_size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pdf_page_count: int | None = Field(default=None, ge=1)
    registered_at: datetime
    status: SourceStatus
    rights_note: str = "待版权台账确认"


class InventoryIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    file_name: str | None = None
    volume_number: int | None = None
