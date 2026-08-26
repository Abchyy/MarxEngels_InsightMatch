"""Corpus package verification used by the ingestion CLI."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from marx_engels.corpus_registry import CorpusManifest
from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.corpus_registry.ids import EXPECTED_VOLUME_COUNT
from marx_engels.corpus_registry.inventory import InventoryError, discover_volumes
from marx_engels.ingestion.config import CorpusSettings
from marx_engels.ingestion.mapping import PageMappingError, assert_complete_coverage
from marx_engels.ingestion.models import PageRangeMapping
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.pipeline import load_source_records

DEFAULT_MANIFEST = Path("corpora/marx_engels_collected_works_cn/manifest.example.yaml")


def validate_manifest(path: Path) -> CorpusManifest:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CorpusManifest.model_validate(payload)


def verify_registered_corpus(settings: CorpusSettings) -> list[str]:
    issues: list[str] = []
    layout = CorpusLayout(settings.corpus_data_root)
    records = load_source_records(layout)
    if not records:
        return issues
    numbers = [record.volume_number for record in records]
    if len(set(numbers)) != len(numbers):
        issues.append("source records contain duplicate volume numbers")
    if sorted(numbers) != list(range(1, EXPECTED_VOLUME_COUNT + 1)):
        issues.append("source records do not cover volumes 1-10 exactly")
    hashes = [record.sha256 for record in records]
    if len(set(hashes)) != len(hashes):
        issues.append("source records contain duplicate SHA-256 values")
    if settings.pdf_asset_root.exists():
        discovered, discovery_issues = discover_volumes(settings.pdf_asset_root)
        if discovery_issues:
            issues.extend(item.message for item in discovery_issues)
        by_volume = {item.volume_number: item for item in discovered}
        for record in records:
            item = by_volume.get(record.volume_number)
            if item is None:
                continue
            if item.sha256 != record.sha256:
                issues.append(
                    f"volume {record.volume_number} hash drift versus registered source record"
                )
            live = sha256_file(item.path)
            if live != record.sha256:
                issues.append(f"volume {record.volume_number} hash is not stable on disk")
    for volume_number in range(1, EXPECTED_VOLUME_COUNT + 1):
        mapping_dir = layout.volume_chunk_dir(volume_number)
        mapping_files = sorted(mapping_dir.glob("*.mapping.json"))
        if not mapping_files:
            continue
        volume_record = next(
            (item for item in records if item.volume_number == volume_number),
            None,
        )
        if volume_record is None or volume_record.pdf_page_count is None:
            continue
        mappings = [
            PageRangeMapping.model_validate_json(path.read_text(encoding="utf-8"))
            for path in mapping_files
        ]
        covering = [
            item
            for item in mappings
            if not any(
                item.chunk_id != other.chunk_id
                and item.original_start_page >= other.original_start_page
                and item.original_end_page <= other.original_end_page
                for other in mappings
            )
        ]
        try:
            assert_complete_coverage(volume_record.pdf_page_count, covering)
        except PageMappingError as exc:
            issues.append(f"volume {volume_number} page mapping: {exc}")
    latest_merge = layout.raw_pages / "latest.json"
    if latest_merge.is_file():
        merge_id = json.loads(latest_merge.read_text(encoding="utf-8")).get("merge_run_id")
        manifest_path = layout.merge_dir(str(merge_id)) / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key, payload in (manifest.get("volumes") or {}).items():
                expected = payload.get("expected_pages")
                written = payload.get("written_pages")
                if expected and written and int(written) != int(expected):
                    issues.append(f"volume {key} merged pages {written} != expected {expected}")
    return issues


def verify_corpus(
    manifest_path: Path | None, settings: CorpusSettings | None = None
) -> tuple[int, str]:
    path = manifest_path or DEFAULT_MANIFEST
    if path.exists():
        manifest = validate_manifest(path)
        message = f"Validated manifest contract for {manifest.corpus_id}."
    elif manifest_path is None:
        return (
            0,
            "Corpus verifier boundary is ready; pass --manifest when corpus data is available.",
        )
    else:
        return 2, f"Manifest not found: {path}"

    runtime = settings or CorpusSettings()
    try:
        extra = verify_registered_corpus(runtime)
    except InventoryError as exc:
        extra = [item.message for item in exc.issues]
    if extra:
        return 1, message + "\n" + "\n".join(extra)
    if runtime.pdf_asset_root.exists():
        discovered, issues = discover_volumes(runtime.pdf_asset_root)
        if issues:
            return 1, message + "\n" + "\n".join(item.message for item in issues)
        message += f"\nLocal inventory: {len(discovered)} volumes registered or available."
    return 0, message
