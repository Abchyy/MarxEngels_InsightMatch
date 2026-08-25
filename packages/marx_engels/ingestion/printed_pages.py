"""Printed-page candidate mapping and passage-page links. Never auto-verified."""

from __future__ import annotations

from marx_engels.ingestion.layer_models import (
    CleanPageRecord,
    MappingStatus,
    PageMapRecord,
    PassageCandidate,
    PassagePageLink,
)


def build_page_maps(pages: list[CleanPageRecord]) -> list[PageMapRecord]:
    ordered = sorted(pages, key=lambda item: item.pdf_page)
    numbers = [page.printed_page_number for page in ordered]
    offset_changes = _offset_change_pages(ordered)
    maps: list[PageMapRecord] = []
    for index, page in enumerate(ordered):
        warnings: list[str] = list(page.warnings)
        signals = ["printed_label"] if page.printed_page_label else []
        status = MappingStatus.CANDIDATE
        confidence = 0.7 if page.printed_page_number is not None else 0.2
        manual = page.manual_required
        previous_number = numbers[index - 1] if index else None
        current = page.printed_page_number
        if previous_number is not None and current is not None:
            if current == previous_number:
                warnings.append("duplicate_printed_page")
                status = MappingStatus.DISPUTED
                manual = True
            elif current < previous_number:
                warnings.append("printed_page_restart_or_reverse")
                signals.append("sequence_break")
            elif current > previous_number + 1:
                warnings.append("printed_page_skip")
                status = MappingStatus.DISPUTED
        if page.pdf_page in offset_changes:
            warnings.append("offset_change")
            signals.append("offset_change")
            status = MappingStatus.DISPUTED
        if current is None:
            warnings.append("missing_printed_page_label")
            confidence = min(confidence, 0.3)
        maps.append(
            PageMapRecord(
                page_id=page.page_id,
                volume_id=page.volume_id,
                pdf_page=page.pdf_page,
                page_type=page.page_type,
                printed_page_label=page.printed_page_label,
                printed_page_number=page.printed_page_number,
                mapping_status=status,
                confidence=confidence,
                signals=signals,
                warnings=warnings,
                manual_required=manual or status is MappingStatus.DISPUTED,
            )
        )
    return maps


def build_passage_pages(
    passages: list[PassageCandidate],
    pages: list[CleanPageRecord],
    page_maps: list[PageMapRecord],
) -> list[PassagePageLink]:
    by_pdf = {page.pdf_page: page for page in pages}
    maps = {item.pdf_page: item for item in page_maps}
    links: list[PassagePageLink] = []
    for passage in passages:
        order_no = 1
        for pdf_page in range(passage.pdf_page_start, passage.pdf_page_end + 1):
            page = by_pdf.get(pdf_page)
            page_map = maps.get(pdf_page)
            if page is None:
                continue
            start, end, missing = _offsets_on_page(passage.text, page.clean_text)
            warnings: list[str] = []
            manual = False
            if missing:
                warnings.append("offset_unresolved")
                manual = True
            links.append(
                PassagePageLink(
                    evidence_id=passage.evidence_id,
                    page_id=page.page_id,
                    pdf_page=pdf_page,
                    printed_page_label=page_map.printed_page_label
                    if page_map
                    else page.printed_page_label,
                    order_no=order_no,
                    start_offset=start,
                    end_offset=end,
                    warnings=warnings,
                    manual_required=manual,
                )
            )
            order_no += 1
    return links


def _offset_change_pages(pages: list[CleanPageRecord]) -> set[int]:
    changes: set[int] = set()
    previous_offset: int | None = None
    for page in pages:
        if page.printed_page_number is None:
            continue
        offset = page.printed_page_number - page.pdf_page
        if previous_offset is not None and offset != previous_offset:
            changes.add(page.pdf_page)
        previous_offset = offset
    return changes


def _offsets_on_page(passage_text: str, page_text: str) -> tuple[int | None, int | None, bool]:
    if not passage_text or not page_text:
        return None, None, True
    if passage_text in page_text:
        start = page_text.index(passage_text)
        return start, start + len(passage_text), False
    if page_text in passage_text:
        return 0, len(page_text), False
    limit = min(len(passage_text), len(page_text))
    for length in range(limit, 0, -1):
        prefix = passage_text[:length]
        if prefix and prefix in page_text:
            start = page_text.index(prefix)
            return start, start + len(prefix), False
        suffix = passage_text[-length:]
        if suffix and suffix in page_text:
            start = page_text.index(suffix)
            return start, start + len(suffix), False
    return None, None, True
