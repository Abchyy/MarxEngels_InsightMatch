"""Page-range coverage checks for derived PDF chunks."""

from __future__ import annotations

from marx_engels.ingestion.models import PageRangeMapping


class PageMappingError(Exception):
    """Raised when chunk page ranges are gapped, overlapping, or incomplete."""


def mapping_from_range(
    *,
    chunk_id: str,
    volume_number: int,
    source_sha256: str,
    chunk_sha256: str,
    start_page: int,
    end_page: int,
) -> PageRangeMapping:
    if end_page < start_page:
        raise PageMappingError(f"invalid page range {start_page}-{end_page}")
    count = end_page - start_page + 1
    return PageRangeMapping(
        chunk_id=chunk_id,
        volume_number=volume_number,
        source_sha256=source_sha256,
        chunk_sha256=chunk_sha256,
        original_start_page=start_page,
        original_end_page=end_page,
        chunk_page_count=count,
        offset=start_page - 1,
    )


def assert_complete_coverage(page_count: int, mappings: list[PageRangeMapping]) -> None:
    if page_count < 1:
        raise PageMappingError("page_count must be >= 1")
    if not mappings:
        raise PageMappingError("no page mappings were provided")
    ordered = sorted(mappings, key=lambda item: item.original_start_page)
    expected = 1
    seen_ids: set[str] = set()
    for mapping in ordered:
        if mapping.chunk_id in seen_ids:
            raise PageMappingError(f"duplicate chunk_id {mapping.chunk_id}")
        seen_ids.add(mapping.chunk_id)
        if mapping.original_start_page != expected:
            if mapping.original_start_page < expected:
                raise PageMappingError(
                    f"overlapping range at PDF page {mapping.original_start_page}"
                )
            raise PageMappingError(f"gap before PDF page {mapping.original_start_page}")
        if mapping.original_end_page < mapping.original_start_page:
            raise PageMappingError(f"inverted range on {mapping.chunk_id}")
        if mapping.chunk_page_count != mapping.original_end_page - mapping.original_start_page + 1:
            raise PageMappingError(f"chunk_page_count mismatch on {mapping.chunk_id}")
        if mapping.offset != mapping.original_start_page - 1:
            raise PageMappingError(f"offset mismatch on {mapping.chunk_id}")
        if mapping.original_page_for(1) != mapping.original_start_page:
            raise PageMappingError(
                f"chunk page 1 does not map to original start on {mapping.chunk_id}"
            )
        expected = mapping.original_end_page + 1
    if expected != page_count + 1:
        raise PageMappingError(f"coverage ended at page {expected - 1}, expected {page_count}")
