"""Rebuild unique original-PDF pages from completed ALL-run MinerU JSON."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from marx_engels.corpus_registry.ids import volume_id as volume_id_for
from marx_engels.corpus_registry.models import SourceRecord
from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.constants import MINERU_MAX_PAGES
from marx_engels.ingestion.layer_models import RawBlock, RawPageRecord
from marx_engels.ingestion.models import (
    ChunkStatus,
    ExtractionChunk,
    ExtractionRun,
    PageRangeMapping,
    RunMode,
    RunStatus,
)
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.pipeline import load_source_records, new_run_id
from marx_engels.ingestion.state import load_pipeline_state

LOGGER = logging.getLogger(__name__)

_KIND_MAP = {
    "header": "header",
    "footer": "footer",
    "page_number": "page_number",
    "page_footnote": "footnote",
    "footnote": "footnote",
    "title": "title",
    "paragraph": "text",
    "text": "text",
    "image": "image",
    "table": "table",
    "list": "list",
}


class PageMergeError(Exception):
    """Raised when an ALL extraction run cannot be selected or read."""


def select_all_extraction_run(state: dict[str, Any], run_id: str | None = None) -> ExtractionRun:
    runs = state.get("runs") or {}
    if run_id:
        payload = runs.get(run_id)
        if not payload:
            raise PageMergeError(f"extraction run {run_id} was not found")
        run = ExtractionRun.model_validate(payload)
        if run.mode is not RunMode.ALL:
            raise PageMergeError(f"run {run_id} is {run.mode.value}, expected all")
        return run
    completed: list[ExtractionRun] = []
    for payload in runs.values():
        run = ExtractionRun.model_validate(payload)
        if run.mode is not RunMode.ALL:
            continue
        if run.status is not RunStatus.COMPLETED:
            continue
        if any(chunk.chunk_page_count > MINERU_MAX_PAGES for chunk in run.chunks):
            continue
        if not all(chunk.status is ChunkStatus.COMPLETED for chunk in run.chunks):
            continue
        completed.append(run)
    if not completed:
        raise PageMergeError("no completed ALL extraction run is available")
    completed.sort(key=lambda item: item.updated_at, reverse=True)
    return completed[0]


def merge_raw_pages(
    layout: CorpusLayout,
    *,
    extraction_run_id: str | None = None,
    merge_run_id: str | None = None,
) -> dict[str, Any]:
    layout.ensure()
    state = load_pipeline_state(layout)
    run = select_all_extraction_run(state, extraction_run_id)
    records = {item.volume_number: item for item in load_source_records(layout)}
    merge_id = merge_run_id or f"merge_{new_run_id().removeprefix('run_')}"
    merge_root = layout.merge_dir(merge_id)
    merge_root.mkdir(parents=True, exist_ok=True)
    by_volume: dict[int, list[ExtractionChunk]] = defaultdict(list)
    for chunk in run.chunks:
        if chunk.status is ChunkStatus.COMPLETED:
            by_volume[chunk.volume_number].append(chunk)
    volume_reports: dict[str, Any] = {}
    total_pages = 0
    total_manual = 0
    for volume_number, chunks in sorted(by_volume.items()):
        record = records.get(volume_number)
        try:
            report = _merge_volume(layout, merge_root, run, record, volume_number, chunks)
        except Exception as exc:
            LOGGER.exception("volume %s merge failed", volume_number)
            volume_reports[str(volume_number)] = {
                "error": str(exc),
                "manual_required": True,
            }
            continue
        volume_reports[str(volume_number)] = report
        total_pages += int(report["recovered_pages"])
        total_manual += len(report["manual_required_pages"])
    manifest = {
        "merge_run_id": merge_id,
        "extraction_run_id": run.run_id,
        "provider_neutral": True,
        "volumes": volume_reports,
        "recovered_pages": total_pages,
        "manual_required_pages": total_manual,
        "chunk_count": sum(1 for chunk in run.chunks if chunk.status is ChunkStatus.COMPLETED),
    }
    atomic_write_json(merge_root / "manifest.json", manifest)
    atomic_write_json(layout.raw_pages / "latest.json", {"merge_run_id": merge_id})
    return manifest


def load_merged_pages(
    layout: CorpusLayout, merge_run_id: str, volume_id: str
) -> list[RawPageRecord]:
    directory = layout.merge_dir(merge_run_id) / volume_id
    pages = [
        RawPageRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("page_*.json"))
    ]
    return sorted(pages, key=lambda item: item.pdf_page)


def _merge_volume(
    layout: CorpusLayout,
    merge_root: Path,
    run: ExtractionRun,
    record: SourceRecord | None,
    volume_number: int,
    chunks: list[ExtractionChunk],
) -> dict[str, Any]:
    volume_id = record.volume_id if record is not None else volume_id_for(volume_number)
    expected = record.pdf_page_count if record is not None and record.pdf_page_count else None
    if expected is None:
        expected = max(chunk.original_end_page for chunk in chunks)
    recovered: dict[int, RawPageRecord] = {}
    duplicates: list[int] = []
    ordered_chunks = sorted(chunks, key=lambda item: item.original_start_page)
    previous_end = 0
    out_of_order: list[str] = []
    for chunk in ordered_chunks:
        if chunk.original_start_page < previous_end:
            out_of_order.append(chunk.chunk_id)
        previous_end = max(previous_end, chunk.original_end_page)
        mapping = _load_mapping(layout, run.run_id, chunk)
        pages = _pages_from_chunk(layout, run.run_id, chunk, mapping)
        for page in pages:
            existing = recovered.get(page.pdf_page)
            if existing is not None:
                duplicates.append(page.pdf_page)
                existing.duplicate = True
                existing.warnings.append(f"duplicate from {page.chunk_id}")
                existing.manual_required = True
                continue
            recovered[page.pdf_page] = page
    missing = [page for page in range(1, expected + 1) if page not in recovered]
    source_sha = (
        record.sha256
        if record is not None
        else (ordered_chunks[0].source_sha256 if ordered_chunks else "")
    )
    for pdf_page in missing:
        recovered[pdf_page] = RawPageRecord(
            volume_id=volume_id,
            volume_number=volume_number,
            pdf_page=pdf_page,
            extraction_run_id=run.run_id,
            source_sha256=source_sha,
            warnings=["missing_structured_page"],
            manual_required=True,
            missing=True,
        )
    volume_dir = merge_root / volume_id
    volume_dir.mkdir(parents=True, exist_ok=True)
    manual_pages = sorted(page.pdf_page for page in recovered.values() if page.manual_required)
    for page in recovered.values():
        atomic_write_json(
            layout.volume_page_file(merge_root, volume_id, page.pdf_page),
            json.loads(page.model_dump_json()),
        )
    return {
        "volume_id": volume_id,
        "expected_pages": expected,
        "recovered_pages": len([page for page in recovered.values() if not page.missing]),
        "written_pages": len(recovered),
        "missing_pages": missing,
        "duplicate_pages": sorted(set(duplicates)),
        "out_of_order_chunks": out_of_order,
        "manual_required_pages": manual_pages,
        "chunk_ids": [chunk.chunk_id for chunk in ordered_chunks],
    }


def _load_mapping(layout: CorpusLayout, run_id: str, chunk: ExtractionChunk) -> PageRangeMapping:
    result_dir = layout.result_dir(run_id, chunk.volume_number, chunk.chunk_id)
    mapping_path = result_dir / "page_mapping.json"
    if mapping_path.is_file():
        return PageRangeMapping.model_validate_json(mapping_path.read_text(encoding="utf-8"))
    fallback = layout.volume_chunk_dir(chunk.volume_number) / f"{chunk.chunk_id}.mapping.json"
    if fallback.is_file():
        return PageRangeMapping.model_validate_json(fallback.read_text(encoding="utf-8"))
    raise PageMergeError(f"missing page mapping for {chunk.chunk_id}")


def _pages_from_chunk(
    layout: CorpusLayout,
    run_id: str,
    chunk: ExtractionChunk,
    mapping: PageRangeMapping,
) -> list[RawPageRecord]:
    result_dir = layout.result_dir(run_id, chunk.volume_number, chunk.chunk_id)
    grouped, artifact_name = load_chunk_page_blocks(result_dir, chunk.chunk_page_count)
    pages: list[RawPageRecord] = []
    for chunk_index in range(chunk.chunk_page_count):
        pdf_page = mapping.original_page_for(chunk_index + 1)
        blocks = grouped.get(chunk_index, [])
        raw_blocks = [_normalize_block(item) for item in blocks]
        text_blocks = [item for item in raw_blocks if item.text.strip() and item.kind != "image"]
        raw_text = "\n".join(item.text for item in text_blocks)
        warnings: list[str] = []
        manual = False
        if not raw_blocks:
            warnings.append("empty_structured_page")
            manual = True
        elif not text_blocks:
            warnings.append("image_or_empty_text")
            manual = True
        pages.append(
            RawPageRecord(
                volume_id=volume_id_for(chunk.volume_number),
                volume_number=chunk.volume_number,
                pdf_page=pdf_page,
                extraction_run_id=run_id,
                chunk_id=chunk.chunk_id,
                chunk_page_index=chunk_index,
                source_sha256=chunk.source_sha256,
                artifact_name=artifact_name,
                raw_text=raw_text,
                blocks=raw_blocks,
                warnings=warnings,
                manual_required=manual,
            )
        )
    return pages


def load_chunk_page_blocks(
    result_dir: Path, page_count: int
) -> tuple[dict[int, list[dict[str, Any]]], str]:
    grouped: dict[int, list[dict[str, Any]]] = {index: [] for index in range(page_count)}
    v1 = _find_artifact(result_dir, suffix="content_list.json", exclude="v2")
    v2 = _find_artifact(result_dir, suffix="content_list_v2.json")
    artifact_name = v1.name if v1 else (v2.name if v2 else None)
    if v1 is not None:
        payload = json.loads(v1.read_text(encoding="utf-8"))
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                index = int(item.get("page_idx") or 0)
                if 0 <= index < page_count:
                    grouped[index].append(item)
            artifact_name = v1.name
    if v2 is not None:
        payload = json.loads(v2.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for index, page in enumerate(payload):
                if index >= page_count:
                    break
                if grouped[index]:
                    continue
                if isinstance(page, list):
                    grouped[index] = [item for item in page if isinstance(item, dict)]
            artifact_name = artifact_name or v2.name
    return grouped, artifact_name or "missing"


def _find_artifact(result_dir: Path, *, suffix: str, exclude: str | None = None) -> Path | None:
    matches = [
        path
        for path in result_dir.rglob("*")
        if path.is_file()
        and path.name.endswith(suffix)
        and (exclude is None or exclude not in path.name)
    ]
    return sorted(matches)[0] if matches else None


def _normalize_block(item: dict[str, Any]) -> RawBlock:
    source_type = str(item.get("type") or "other")
    kind = _KIND_MAP.get(source_type, source_type)
    text = _block_text(item)
    bbox = item.get("bbox")
    bbox_values = [float(value) for value in bbox] if isinstance(bbox, list) else None
    level = item.get("text_level")
    text_level = int(level) if isinstance(level, int) else None
    if text_level is not None and kind == "text":
        kind = "title"
    return RawBlock(
        source_type=source_type, kind=kind, text=text, bbox=bbox_values, text_level=text_level
    )


def _block_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_block_text(item) for item in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return str(value["text"])
        if isinstance(value.get("content"), str):
            return str(value["content"])
        for key in (
            "title_content",
            "paragraph_content",
            "page_footnote_content",
            "page_number_content",
            "content",
        ):
            if key in value:
                return _block_text(value[key])
        return "".join(
            _block_text(item)
            for key, item in value.items()
            if key not in {"bbox", "type", "page_idx"}
        )
    return ""
