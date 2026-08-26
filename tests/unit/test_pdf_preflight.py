from pathlib import Path

from tests.helpers import write_pdf

from marx_engels.ingestion.preflight import (
    inspect_pdf,
    needs_ocr,
    preflight_volume,
    sample_page_numbers,
)


def test_sample_page_numbers_cover_edges() -> None:
    assert sample_page_numbers(3) == [1, 2, 3]
    sampled = sample_page_numbers(20)
    assert sampled[0] == 1
    assert sampled[-1] == 20
    assert len(sampled) == 5


def test_preflight_detects_text_layer_and_limits(tmp_path: Path) -> None:
    pages = [
        f"enough visible text layer content on page {index} for sampling"
        for index in range(1, 6)
    ]
    path = write_pdf(tmp_path / "doc.pdf", pages)
    report = preflight_volume(
        volume_number=1,
        path=path,
        file_name=path.name,
        file_size_bytes=path.stat().st_size,
        sha256="a" * 64,
    )
    assert report.page_count == 5
    assert report.needs_ocr is False
    assert report.requires_split is False
    assert report.exceeds_mineru_limits is False
    assert all(page.has_text_layer for page in report.sampled_pages)


def test_preflight_marks_ocr_when_text_layer_missing(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "scan.pdf", ["", "", ""])
    page_count, _metadata, sampled, _warnings = inspect_pdf(path)
    assert page_count == 3
    assert needs_ocr(sampled) is True
