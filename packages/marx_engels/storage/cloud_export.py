"""Deterministic local cloud-ingest export. Does not upload or call any API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marx_engels.corpus_registry.hashing import sha256_bytes, sha256_file
from marx_engels.corpus_registry.local_asset import (
    DEFAULT_EXPORT_ROOT,
    DEFAULT_SEED_PATH,
    QUOTATION_POLICY_SQLITE,
    TRUST_POLICY_SOURCE_DERIVED,
    load_expected_sha256,
    load_local_asset_manifest,
    verify_seed_file,
)
from marx_engels.errors import DomainError
from marx_engels.ingestion.atomic import atomic_write_text
from marx_engels.retrieval_core.units import (
    DEFAULT_RETRIEVAL_UNIT_CHAR_LIMIT,
    retrieval_units_for_passage,
)
from marx_engels.storage.local_publish import assert_sqlite_matches_spec
from marx_engels.storage.readonly import connect_readonly

_SELECT_PASSAGES = """
SELECT
    p.evidence_id AS evidence_id,
    p.verified_text AS verified_text,
    p.text_hash AS text_hash,
    p.content_type AS content_type,
    w.work_id AS work_id,
    w.title AS work_title,
    v.volume_id AS volume_id,
    v.volume_no AS volume_no,
    e.edition_id AS edition_id,
    e.edition_label AS edition_label,
    c.corpus_id AS corpus_id,
    c.name AS corpus_name
FROM passage AS p
JOIN section AS s ON s.section_id = p.section_id
JOIN work AS w ON w.work_id = s.work_id
JOIN volume AS v ON v.volume_id = w.volume_id
JOIN edition AS e ON e.edition_id = v.edition_id
JOIN corpus AS c ON c.corpus_id = e.corpus_id
ORDER BY
    v.volume_no ASC,
    w.order_no ASC,
    s.order_no ASC,
    p.order_no ASC,
    p.evidence_id ASC
"""


def export_cloud_ingest(
    *,
    seed_path: Path | None = None,
    output_root: Path | None = None,
    manifest_path: Path | None = None,
    sha256_path: Path | None = None,
    char_limit: int = DEFAULT_RETRIEVAL_UNIT_CHAR_LIMIT,
) -> dict[str, Any]:
    spec = load_local_asset_manifest(manifest_path)
    expected = load_expected_sha256(sha256_path)
    if expected != spec.sha256:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Tracked SHA-256 file does not match the asset manifest.",
            details={"manifest_sha256": spec.sha256, "sha256_file": expected},
        )
    seed = seed_path or DEFAULT_SEED_PATH
    seed_digest = verify_seed_file(seed, spec)
    assert_sqlite_matches_spec(seed, spec, readonly=True)
    destination = (output_root or DEFAULT_EXPORT_ROOT) / spec.data_version
    destination.mkdir(parents=True, exist_ok=True)

    units_path = destination / "retrieval_units.jsonl"
    mapping_path = destination / "retrieval_unit_map.jsonl"
    manifest_out = destination / "manifest.json"

    unit_lines: list[str] = []
    mapping_lines: list[str] = []
    connection = connect_readonly(seed)
    try:
        rows = connection.execute(_SELECT_PASSAGES).fetchall()
        for row in rows:
            evidence_id = str(row["evidence_id"])
            for unit in retrieval_units_for_passage(
                evidence_id, str(row["verified_text"]), char_limit=char_limit
            ):
                record = {
                    "retrieval_unit_id": unit.retrieval_unit_id,
                    "evidence_id": evidence_id,
                    "corpus_id": str(row["corpus_id"]),
                    "corpus_name": str(row["corpus_name"]),
                    "edition_id": str(row["edition_id"]),
                    "edition_label": str(row["edition_label"] or ""),
                    "volume_id": str(row["volume_id"]),
                    "volume_no": int(row["volume_no"]),
                    "work_id": str(row["work_id"]),
                    "work_title": str(row["work_title"]),
                    "content_type": str(row["content_type"]),
                    "order_no": unit.order_no,
                    "search_text": unit.search_text,
                    "search_text_hash": unit.search_text_hash,
                    "passage_text_hash": str(row["text_hash"]),
                    "quotation_policy": QUOTATION_POLICY_SQLITE,
                    "search_text_is_not_quotation": True,
                }
                unit_lines.append(_canonical_json(record))
                mapping_lines.append(
                    _canonical_json(
                        {
                            "retrieval_unit_id": unit.retrieval_unit_id,
                            "evidence_id": evidence_id,
                            "order_no": unit.order_no,
                        }
                    )
                )
    finally:
        connection.close()

    units_payload = "\n".join(unit_lines) + ("\n" if unit_lines else "")
    mapping_payload = "\n".join(mapping_lines) + ("\n" if mapping_lines else "")
    atomic_write_text(units_path, units_payload)
    atomic_write_text(mapping_path, mapping_payload)
    units_sha256 = sha256_bytes(units_payload.encode("utf-8"))
    mapping_sha256 = sha256_bytes(mapping_payload.encode("utf-8"))
    manifest: dict[str, Any] = {
        "corpus_id": spec.corpus_id,
        "data_version": spec.data_version,
        "edition_id": spec.edition_id,
        "human_reviewed": False,
        "quotation_policy": QUOTATION_POLICY_SQLITE,
        "seed_sha256": seed_digest,
        "trust_policy": TRUST_POLICY_SOURCE_DERIVED,
        "unit_count": len(unit_lines),
        "units_sha256": units_sha256,
        "mapping_sha256": mapping_sha256,
        "upload": False,
        "search_text_is_not_quotation": True,
        "restore_quotation_from": "sqlite_canonical_verified_text_via_evidence_id",
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(manifest_out, manifest_text)
    return {
        "data_version": spec.data_version,
        "output_dir": str(destination),
        "unit_count": len(unit_lines),
        "units_path": str(units_path),
        "mapping_path": str(mapping_path),
        "manifest_path": str(manifest_out),
        "units_sha256": units_sha256,
        "mapping_sha256": mapping_sha256,
        "seed_sha256": seed_digest,
        "upload": False,
        "trust_policy": TRUST_POLICY_SOURCE_DERIVED,
        "human_reviewed": False,
        "manifest_sha256": sha256_file(manifest_out),
    }


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
