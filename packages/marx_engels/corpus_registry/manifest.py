"""Validated corpus-package manifest contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    corpus_id: str = Field(pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1)
    language: str = Field(min_length=2)
    edition_id: str = Field(pattern=r"^[a-z0-9_]+$")
    publisher: str
    publish_year: int | None = None
    volume_count: int = Field(ge=1)
    rights_status: Literal["pending_review", "approved", "restricted", "rejected"]
    release_status: Literal["draft", "validating", "published", "retired"]
