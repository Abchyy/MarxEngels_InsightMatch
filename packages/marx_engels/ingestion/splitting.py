"""Create derived PDF chunks without modifying the original source file."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.corpus_registry.ids import chunk_id
from marx_engels.ingestion.atomic import atomic_write_bytes, atomic_write_json
from marx_engels.ingestion.constants import SPLIT_MAX_BYTES, SPLIT_MAX_PAGES
from marx_engels.ingestion.mapping import (
    PageMappingError,
    assert_complete_coverage,
    mapping_from_range,
)
from marx_engels.ingestion.models import PageRangeMapping


class PdfSplitError(Exception):
    """Raised when a derived chunk cannot be produced within size/page limits."""


class OversizedPageError(PdfSplitError):
    """A single PDF page exceeds the derived-chunk size budget."""


@dataclass(frozen=True)
class PlannedRange:
    start_page: int
    end_page: int


@dataclass(frozen=True)
class MaterializedChunk:
    mapping: PageRangeMapping
    path: Path
    size_bytes: int


def plan_page_ranges(
    page_count: int,
    file_size_bytes: int,
    *,
    max_bytes: int = SPLIT_MAX_BYTES,
    max_pages: int = SPLIT_MAX_PAGES,
) -> list[PlannedRange]:
    if page_count < 1:
        raise PdfSplitError("cannot split a PDF with no pages")
    if file_size_bytes <= max_bytes and page_count <= max_pages:
        return [PlannedRange(1, page_count)]
    bytes_per_page = max(1.0, file_size_bytes / page_count)
    max_pages_by_size = max(1, int((max_bytes * 0.9) / bytes_per_page))
    window = max(1, min(max_pages, max_pages_by_size))
    ranges: list[PlannedRange] = []
    start = 1
    while start <= page_count:
        end = min(page_count, start + window - 1)
        ranges.append(PlannedRange(start, end))
        start = end + 1
    return ranges


def _write_pages(reader: PdfReader, start_page: int, end_page: int, dest: Path) -> None:
    writer = PdfWriter()
    for index in range(start_page - 1, end_page):
        writer.add_page(reader.pages[index])
    dest.parent.mkdir(parents=True, exist_ok=True)
    buffer = _serialize_writer(writer)
    atomic_write_bytes(dest, buffer)


def _serialize_writer(writer: PdfWriter) -> bytes:
    import io

    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _fit_end_page(
    reader: PdfReader,
    start_page: int,
    proposed_end: int,
    dest: Path,
    *,
    max_bytes: int,
    max_pages: int,
) -> tuple[int, int]:
    end_page = min(proposed_end, start_page + max_pages - 1, len(reader.pages))
    while True:
        _write_pages(reader, start_page, end_page, dest)
        size = dest.stat().st_size
        if size <= max_bytes:
            return end_page, size
        if end_page == start_page:
            dest.unlink(missing_ok=True)
            raise OversizedPageError(
                f"PDF page {start_page} produces a {size}-byte chunk "
                f"over the {max_bytes} byte budget"
            )
        page_span = end_page - start_page + 1
        shrunk = start_page + max(0, int(page_span * (max_bytes / size) * 0.9) - 1)
        if shrunk >= end_page:
            shrunk = end_page - 1
        end_page = max(start_page, shrunk)


def _reuse_existing_chunks(
    output_dir: Path,
    *,
    volume_number: int,
    source_sha256: str,
    page_count: int,
    max_bytes: int,
    max_pages: int,
) -> list[MaterializedChunk] | None:
    mapping_files = sorted(output_dir.glob("*.mapping.json"))
    if not mapping_files:
        return None
    mappings = [
        PageRangeMapping.model_validate_json(path.read_text(encoding="utf-8"))
        for path in mapping_files
    ]
    if any(
        item.source_sha256 != source_sha256 or item.volume_number != volume_number
        for item in mappings
    ):
        return None
    try:
        assert_complete_coverage(page_count, mappings)
    except PageMappingError:
        return None
    chunks: list[MaterializedChunk] = []
    for mapping in sorted(mappings, key=lambda item: item.original_start_page):
        dest = output_dir / (
            f"v{volume_number:02d}_{mapping.original_start_page:04d}_"
            f"{mapping.original_end_page:04d}.pdf"
        )
        if not dest.is_file() or sha256_file(dest) != mapping.chunk_sha256:
            return None
        if dest.stat().st_size > max_bytes or mapping.chunk_page_count > max_pages:
            return None
        chunks.append(MaterializedChunk(mapping=mapping, path=dest, size_bytes=dest.stat().st_size))
    return chunks


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        stale = path.with_name(path.name + ".stale")
        try:
            path.replace(stale)
            stale.unlink(missing_ok=True)
        except OSError:
            return


def _persist_mapping(output_dir: Path, mapping: PageRangeMapping) -> None:
    atomic_write_json(
        output_dir / f"{mapping.chunk_id}.mapping.json", json.loads(mapping.model_dump_json())
    )


def materialize_chunks(
    source_path: Path,
    *,
    volume_number: int,
    source_sha256: str,
    page_count: int,
    output_dir: Path,
    max_bytes: int = SPLIT_MAX_BYTES,
    max_pages: int = SPLIT_MAX_PAGES,
) -> list[MaterializedChunk]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reused = _reuse_existing_chunks(
        output_dir,
        volume_number=volume_number,
        source_sha256=source_sha256,
        page_count=page_count,
        max_bytes=max_bytes,
        max_pages=max_pages,
    )
    if reused is not None:
        return reused
    for leftover in output_dir.glob("*.mapping.json"):
        _unlink_quietly(leftover)
    for leftover in output_dir.glob("v*.pdf"):
        _unlink_quietly(leftover)
    planned = plan_page_ranges(
        page_count, source_path.stat().st_size, max_bytes=max_bytes, max_pages=max_pages
    )
    if source_path.stat().st_size <= max_bytes and page_count <= max_pages:
        dest = output_dir / f"v{volume_number:02d}_0001_{page_count:04d}.pdf"
        if not dest.exists() or sha256_file(dest) != source_sha256:
            shutil.copyfile(source_path, dest)
        digest = sha256_file(dest)
        identifier = chunk_id(volume_number, 1, page_count, source_sha256)
        mapping = mapping_from_range(
            chunk_id=identifier,
            volume_number=volume_number,
            source_sha256=source_sha256,
            chunk_sha256=digest,
            start_page=1,
            end_page=page_count,
        )
        _persist_mapping(output_dir, mapping)
        return [MaterializedChunk(mapping=mapping, path=dest, size_bytes=dest.stat().st_size)]

    try:
        reader = PdfReader(str(source_path), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfSplitError(f"unable to open {source_path.name} for splitting") from exc

    chunks: list[MaterializedChunk] = []
    start = 1
    while start <= page_count:
        proposed = min(page_count, start + max_pages - 1)
        for item in planned:
            if item.start_page == start:
                proposed = item.end_page
                break
        temp = output_dir / f".v{volume_number:02d}_{start:04d}.partial.pdf"
        end_page, size = _fit_end_page(
            reader,
            start,
            proposed,
            temp,
            max_bytes=max_bytes,
            max_pages=max_pages,
        )
        dest = output_dir / f"v{volume_number:02d}_{start:04d}_{end_page:04d}.pdf"
        if dest.exists() and dest != temp:
            dest.unlink()
        temp.replace(dest)
        digest = sha256_file(dest)
        identifier = chunk_id(volume_number, start, end_page, source_sha256)
        mapping = mapping_from_range(
            chunk_id=identifier,
            volume_number=volume_number,
            source_sha256=source_sha256,
            chunk_sha256=digest,
            start_page=start,
            end_page=end_page,
        )
        _persist_mapping(output_dir, mapping)
        chunks.append(MaterializedChunk(mapping=mapping, path=dest, size_bytes=size))
        start = end_page + 1
    return chunks


def materialize_page_window(
    source_path: Path,
    *,
    volume_number: int,
    source_sha256: str,
    start_page: int,
    end_page: int,
    output_dir: Path,
    max_bytes: int = SPLIT_MAX_BYTES,
    max_pages: int = SPLIT_MAX_PAGES,
) -> MaterializedChunk:
    page_span = end_page - start_page + 1
    if page_span < 1:
        raise PdfSplitError("pilot page window is empty")
    if page_span > max_pages:
        raise PdfSplitError(f"pilot window {start_page}-{end_page} exceeds {max_pages} pages")
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"v{volume_number:02d}_{start_page:04d}_{end_page:04d}.pdf"
    try:
        reader = PdfReader(str(source_path), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfSplitError(f"unable to open {source_path.name} for a derived window") from exc
    if end_page > len(reader.pages):
        raise PdfSplitError(f"window {start_page}-{end_page} exceeds {len(reader.pages)} pages")
    _write_pages(reader, start_page, end_page, dest)
    size = dest.stat().st_size
    if size > max_bytes:
        dest.unlink(missing_ok=True)
        raise PdfSplitError(f"derived window is {size} bytes, over the {max_bytes} byte budget")
    digest = sha256_file(dest)
    identifier = chunk_id(volume_number, start_page, end_page, source_sha256)
    mapping = mapping_from_range(
        chunk_id=identifier,
        volume_number=volume_number,
        source_sha256=source_sha256,
        chunk_sha256=digest,
        start_page=start_page,
        end_page=end_page,
    )
    _persist_mapping(output_dir, mapping)
    return MaterializedChunk(mapping=mapping, path=dest, size_bytes=size)
