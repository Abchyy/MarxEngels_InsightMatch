from pathlib import Path

import pytest
from tests.helpers import write_pdf

from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.ingestion.mapping import assert_complete_coverage
from marx_engels.ingestion.splitting import (
    OversizedPageError,
    materialize_chunks,
    materialize_page_window,
    plan_page_ranges,
)


def test_plan_ranges_keep_single_chunk_when_under_limits() -> None:
    ranges = plan_page_ranges(40, 10_000, max_bytes=180_000, max_pages=180)
    assert [(item.start_page, item.end_page) for item in ranges] == [(1, 40)]


def test_default_page_budget_splits_above_live_api_limit() -> None:
    ranges = plan_page_ranges(201, 10_000)
    pages = [(item.start_page, item.end_page) for item in ranges]
    assert pages[0][0] == 1
    assert pages[-1][1] == 201
    assert all(end - start + 1 <= 180 for start, end in pages)


def test_plan_ranges_respect_page_and_size_caps() -> None:
    ranges = plan_page_ranges(12, 12_000, max_bytes=3_000, max_pages=4)
    pages = [(item.start_page, item.end_page) for item in ranges]
    assert pages[0][0] == 1
    assert pages[-1][1] == 12
    for start, end in pages:
        assert end - start + 1 <= 4


def test_split_coverage_has_no_gaps_or_overlaps(tmp_path: Path) -> None:
    source = write_pdf(tmp_path / "source.pdf", [f"page {index}" for index in range(1, 11)])
    chunks = materialize_chunks(
        source,
        volume_number=5,
        source_sha256=sha256_file(source),
        page_count=10,
        output_dir=tmp_path / "chunks",
        max_bytes=10**9,
        max_pages=3,
    )
    mappings = [chunk.mapping for chunk in chunks]
    assert_complete_coverage(10, mappings)
    assert all(chunk.size_bytes > 0 for chunk in chunks)
    assert mappings[0].original_page_for(1) == 1


def test_split_is_idempotent(tmp_path: Path) -> None:
    source = write_pdf(tmp_path / "source.pdf", [f"page {index}" for index in range(1, 6)])
    digest = sha256_file(source)
    first = materialize_chunks(
        source,
        volume_number=1,
        source_sha256=digest,
        page_count=5,
        output_dir=tmp_path / "chunks",
        max_bytes=10**9,
        max_pages=180,
    )
    second = materialize_chunks(
        source,
        volume_number=1,
        source_sha256=digest,
        page_count=5,
        output_dir=tmp_path / "chunks",
        max_bytes=10**9,
        max_pages=180,
    )
    assert [item.mapping.chunk_sha256 for item in first] == [
        item.mapping.chunk_sha256 for item in second
    ]


def test_oversized_single_page_raises(tmp_path: Path) -> None:
    source = write_pdf(tmp_path / "huge.pdf", ["page"], junk_per_page=80_000)
    with pytest.raises(OversizedPageError):
        materialize_chunks(
            source,
            volume_number=5,
            source_sha256=sha256_file(source),
            page_count=1,
            output_dir=tmp_path / "chunks",
            max_bytes=200,
            max_pages=180,
        )


def test_pilot_window_keeps_original_offset(tmp_path: Path) -> None:
    source = write_pdf(tmp_path / "source.pdf", [f"page {index}" for index in range(1, 31)])
    chunk = materialize_page_window(
        source,
        volume_number=1,
        source_sha256=sha256_file(source),
        start_page=21,
        end_page=30,
        output_dir=tmp_path / "chunks",
    )
    assert chunk.mapping.offset == 20
    assert chunk.mapping.original_page_for(1) == 21
    assert chunk.mapping.original_page_for(10) == 30
    assert source.read_bytes()  # original remains readable
