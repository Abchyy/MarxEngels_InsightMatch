"""Canonical local SQLite asset: Git-ignored seed, expected hash, and counts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.errors import DomainError

DEFAULT_ASSET_MANIFEST = Path("corpora/marx_engels_collected_works_cn/sqlite/local_asset.yaml")
DEFAULT_SEED_PATH = Path("corpora/marx_engels_collected_works_cn/sqlite/corpus.db")
DEFAULT_SHA256_PATH = Path("corpora/marx_engels_collected_works_cn/sqlite/corpus.sha256")
DEFAULT_RUNTIME_PATH = Path("runtime-data/sqlite/corpus.db")
DEFAULT_EXPORT_ROOT = Path("runtime-data/cloud-export")
SIDECAR_FILENAME = "local_release.json"
TRUST_POLICY_SOURCE_DERIVED = "source_derived_trusted"
QUOTATION_POLICY_SQLITE = "sqlite_canonical_text_only"


class LocalAssetManifest(BaseModel):
    """Tracked description of the Git-ignored Canonical SQLite seed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    corpus_id: str
    edition_id: str
    data_version: str
    sqlite_filename: str
    sha256: str
    byte_size: int = Field(gt=0)
    volume_count: int = Field(ge=1)
    work_count: int = Field(ge=1)
    section_count: int = Field(ge=1)
    passage_count: int = Field(ge=1)
    trust_policy: Literal["source_derived_trusted"]
    human_reviewed: Literal[False]
    quotation_policy: str
    git_tracked: Literal[False]

    @field_validator("sha256")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("sha256 must be a lowercase 64-character hex digest")
        return value


class LocalReleaseSidecar(BaseModel):
    """Runtime-only record of a completed source-derived local publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_version: str
    corpus_id: str
    trust_policy: Literal["source_derived_trusted"]
    human_reviewed: Literal[False]
    quotation_policy: str
    seed_sha256: str
    init_complete: Literal[True]
    published_at: str
    seed_path: str
    runtime_path: str


def load_local_asset_manifest(path: Path | None = None) -> LocalAssetManifest:
    manifest_path = path or DEFAULT_ASSET_MANIFEST
    if not manifest_path.is_file():
        raise DomainError(
            "STORAGE_NOT_CONFIGURED",
            "Canonical SQLite asset manifest is missing.",
            details={"path": str(manifest_path)},
        )
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return LocalAssetManifest.model_validate(payload)


def load_expected_sha256(path: Path | None = None) -> str:
    sha_path = path or DEFAULT_SHA256_PATH
    if not sha_path.is_file():
        raise DomainError(
            "STORAGE_NOT_CONFIGURED",
            "Expected Canonical SQLite SHA-256 file is missing.",
            details={"path": str(sha_path)},
        )
    line = sha_path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    digest = line.split()[0].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise DomainError(
            "STORAGE_NOT_CONFIGURED",
            "Expected Canonical SQLite SHA-256 is malformed.",
            details={"path": str(sha_path)},
        )
    return digest


def sidecar_path_for(database_path: Path) -> Path:
    return database_path.parent / SIDECAR_FILENAME


def load_release_sidecar(database_path: Path) -> LocalReleaseSidecar | None:
    path = sidecar_path_for(database_path)
    if not path.is_file():
        return None
    return LocalReleaseSidecar.model_validate_json(path.read_text(encoding="utf-8"))


def wal_sidecar_path(database_path: Path) -> Path:
    return Path(str(database_path) + "-wal")


def assert_no_unhashed_wal(database_path: Path) -> None:
    """Fail closed when a non-empty WAL sidecar exists outside corpus.sha256."""

    wal_path = wal_sidecar_path(database_path)
    if not wal_path.is_file():
        return
    wal_bytes = wal_path.stat().st_size
    if wal_bytes == 0:
        return
    raise DomainError(
        "RELEASE_MISMATCH",
        "Canonical SQLite seed has a non-empty WAL file that is not covered by corpus.sha256.",
        details={
            "path": str(database_path),
            "wal_path": str(wal_path),
            "wal_bytes": wal_bytes,
        },
    )


def verify_seed_file(seed_path: Path, spec: LocalAssetManifest) -> str:
    """Fail closed when the Canonical seed is missing, hashed differently, or has unhashed WAL."""

    if not seed_path.is_file():
        raise DomainError(
            "SQLITE_UNAVAILABLE",
            "Canonical SQLite seed is missing. Obtain the local corpus asset and retry.",
            details={"path": str(seed_path)},
        )
    size = seed_path.stat().st_size
    if size != spec.byte_size:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Canonical SQLite seed size does not match the tracked asset manifest.",
            details={
                "path": str(seed_path),
                "actual_bytes": size,
                "expected_bytes": spec.byte_size,
            },
        )
    digest = sha256_file(seed_path)
    if digest != spec.sha256:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Canonical SQLite seed SHA-256 does not match the tracked expected hash.",
            details={
                "path": str(seed_path),
                "actual_sha256": digest,
                "expected_sha256": spec.sha256,
            },
        )
    assert_no_unhashed_wal(seed_path)
    return digest


def assert_not_canonical_seed(path: Path, seed_path: Path) -> None:
    if path.resolve() == seed_path.resolve():
        raise DomainError(
            "STORAGE_NOT_CONFIGURED",
            "Canonical seed is read-only. Use the Git-ignored runtime copy.",
            details={"path": str(path), "seed_path": str(seed_path)},
        )
