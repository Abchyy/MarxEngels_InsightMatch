"""Stable fingerprint used to skip duplicate MinerU uploads."""

from __future__ import annotations

from marx_engels.corpus_registry.hashing import canonical_json_sha256
from marx_engels.ingestion.models import ExtractOptions


def extraction_fingerprint(
    *,
    source_sha256: str,
    chunk_sha256: str,
    provider: str,
    provider_version: str,
    options: ExtractOptions,
) -> str:
    payload: dict[str, object] = {
        "source_sha256": source_sha256,
        "chunk_sha256": chunk_sha256,
        "provider": provider,
        "provider_version": provider_version,
        "model_version": options.model_version,
        "language": options.language,
        "enable_table": options.enable_table,
        "enable_formula": options.enable_formula,
        "is_ocr": options.is_ocr,
    }
    return canonical_json_sha256(payload)
