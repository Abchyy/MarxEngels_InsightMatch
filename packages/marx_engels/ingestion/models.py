"""Internal extraction workflow models. Markdown output stays on the Raw layer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TextLayer(StrEnum):
    RAW = "raw"
    CLEAN = "clean"


class ChunkStatus(StrEnum):
    PLANNED = "planned"
    MATERIALIZED = "materialized"
    UPLOADING = "uploading"
    POLLING = "polling"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunMode(StrEnum):
    PILOT = "pilot"
    ALL = "all"


class ProviderTaskState(StrEnum):
    WAITING_FILE = "waiting-file"
    PENDING = "pending"
    RUNNING = "running"
    CONVERTING = "converting"
    DONE = "done"
    FAILED = "failed"


class ExtractOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = "vlm"
    language: str = "ch"
    enable_table: bool = True
    enable_formula: bool = True
    is_ocr: bool = False


class PageRangeMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    volume_number: int = Field(ge=1, le=10)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    chunk_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    original_start_page: int = Field(ge=1)
    original_end_page: int = Field(ge=1)
    chunk_page_count: int = Field(ge=1)
    offset: int = Field(ge=0)

    def original_page_for(self, chunk_page: int) -> int:
        if chunk_page < 1 or chunk_page > self.chunk_page_count:
            raise ValueError(f"chunk page {chunk_page} is outside 1-{self.chunk_page_count}")
        return chunk_page + self.offset


class ExtractionChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    volume_number: int = Field(ge=1, le=10)
    source_sha256: str
    chunk_sha256: str | None = None
    original_start_page: int = Field(ge=1)
    original_end_page: int = Field(ge=1)
    chunk_page_count: int = Field(ge=1)
    offset: int = Field(ge=0)
    file_name: str
    status: ChunkStatus = ChunkStatus.PLANNED
    fingerprint: str | None = None
    batch_id: str | None = None
    data_id: str | None = None
    error: str | None = None
    layer: TextLayer = TextLayer.RAW


class ProviderTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    data_id: str
    file_name: str
    state: str
    full_zip_url: str | None = None
    err_msg: str | None = None
    extracted_pages: int | None = None
    total_pages: int | None = None


class ResultArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    sha256: str
    size_bytes: int
    kind: str
    layer: TextLayer = TextLayer.RAW


class ExtractionRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: RunMode
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    provider: str
    provider_version: str
    options: ExtractOptions
    chunks: list[ExtractionChunk] = Field(default_factory=list)
    notes: str = "MinerU Markdown is Raw extraction only; it is not verified quotation text."
