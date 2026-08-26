"""PDF preflight: page count, metadata, sampled text layer, MinerU limit flags."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from marx_engels.ingestion.constants import (
    MINERU_MAX_BYTES,
    MINERU_MAX_PAGES,
    SPLIT_MAX_BYTES,
    SPLIT_MAX_PAGES,
    TEXT_LAYER_MIN_CHARS,
)


class PdfPreflightError(Exception):
    """Raised when a source PDF cannot be opened for preflight."""


@dataclass(frozen=True)
class SampledPage:
    pdf_page: int
    char_count: int
    has_text_layer: bool


@dataclass(frozen=True)
class PreflightReport:
    volume_number: int
    file_name: str
    file_size_bytes: int
    sha256: str
    page_count: int
    metadata: dict[str, str]
    sampled_pages: tuple[SampledPage, ...]
    needs_ocr: bool
    exceeds_mineru_limits: bool
    requires_split: bool
    warnings: tuple[str, ...]


def sample_page_numbers(page_count: int, sample_size: int = 5) -> list[int]:
    if page_count < 1:
        return []
    if page_count <= sample_size:
        return list(range(1, page_count + 1))
    picks = {
        1,
        max(1, page_count // 4),
        max(1, page_count // 2),
        max(1, (3 * page_count) // 4),
        page_count,
    }
    return sorted(picks)


def _metadata_map(reader: PdfReader) -> dict[str, str]:
    meta = reader.metadata
    if meta is None:
        return {}
    mapping: dict[str, str] = {}
    for key in ("/Title", "/Author", "/Creator", "/Producer", "/CreationDate"):
        value = meta.get(key)
        if value:
            mapping[key.lstrip("/")] = str(value)
    return mapping


def inspect_pdf(path: Path) -> tuple[int, dict[str, str], tuple[SampledPage, ...], tuple[str, ...]]:
    warnings: list[str] = []
    try:
        reader = PdfReader(str(path), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfPreflightError(f"Unable to read PDF {path.name}") from exc
    if getattr(reader, "is_encrypted", False):
        raise PdfPreflightError(f"PDF {path.name} is encrypted")
    page_count = len(reader.pages)
    if page_count < 1:
        raise PdfPreflightError(f"PDF {path.name} has no pages")
    sampled: list[SampledPage] = []
    for page_number in sample_page_numbers(page_count):
        page = reader.pages[page_number - 1]
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
            warnings.append(f"text extraction failed on PDF page {page_number}")
        char_count = len(text.strip())
        sampled.append(
            SampledPage(
                pdf_page=page_number,
                char_count=char_count,
                has_text_layer=char_count >= TEXT_LAYER_MIN_CHARS,
            )
        )
    return page_count, _metadata_map(reader), tuple(sampled), tuple(warnings)


def needs_ocr(sampled_pages: tuple[SampledPage, ...]) -> bool:
    if not sampled_pages:
        return True
    with_text = sum(1 for page in sampled_pages if page.has_text_layer)
    return with_text * 2 < len(sampled_pages)


def preflight_volume(
    *,
    volume_number: int,
    path: Path,
    file_name: str,
    file_size_bytes: int,
    sha256: str,
) -> PreflightReport:
    page_count, metadata, sampled, warnings = inspect_pdf(path)
    ocr_required = needs_ocr(sampled)
    exceeds = file_size_bytes > MINERU_MAX_BYTES or page_count > MINERU_MAX_PAGES
    split = file_size_bytes > SPLIT_MAX_BYTES or page_count > SPLIT_MAX_PAGES
    extra_warnings = list(warnings)
    if exceeds:
        extra_warnings.append("exceeds MinerU precision API limits (200 MB / 200 pages)")
    if split:
        extra_warnings.append("requires derived chunks (over 180 MB or 180 pages)")
    if ocr_required:
        extra_warnings.append("sampled pages lack a usable text layer; is_ocr will be enabled")
    return PreflightReport(
        volume_number=volume_number,
        file_name=file_name,
        file_size_bytes=file_size_bytes,
        sha256=sha256,
        page_count=page_count,
        metadata=metadata,
        sampled_pages=sampled,
        needs_ocr=ocr_required,
        exceeds_mineru_limits=exceeds,
        requires_split=split,
        warnings=tuple(extra_warnings),
    )


def report_to_dict(report: PreflightReport) -> dict[str, Any]:
    return {
        "volume_number": report.volume_number,
        "file_name": report.file_name,
        "file_size_bytes": report.file_size_bytes,
        "sha256": report.sha256,
        "page_count": report.page_count,
        "metadata": report.metadata,
        "sampled_pages": [
            {
                "pdf_page": page.pdf_page,
                "char_count": page.char_count,
                "has_text_layer": page.has_text_layer,
            }
            for page in report.sampled_pages
        ],
        "needs_ocr": report.needs_ocr,
        "exceeds_mineru_limits": report.exceeds_mineru_limits,
        "requires_split": report.requires_split,
        "warnings": list(report.warnings),
        "layer": "raw",
    }
