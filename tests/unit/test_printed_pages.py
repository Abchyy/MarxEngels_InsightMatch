from marx_engels.ingestion.layer_models import (
    CleanPageRecord,
    ContentKind,
    ContentSpan,
    MappingStatus,
    PassageCandidate,
    VerificationStatus,
)
from marx_engels.ingestion.printed_pages import build_page_maps, build_passage_pages


def _page(pdf_page: int, label: str | None, number: int | None, text: str) -> CleanPageRecord:
    return CleanPageRecord(
        page_id=f"page_{pdf_page}",
        volume_id="mecw_cn_2009_v01",
        volume_number=1,
        pdf_page=pdf_page,
        clean_text=text,
        text_hash="x",
        spans=[ContentSpan(content_type=ContentKind.MAIN_TEXT, text=text)],
        printed_page_label=label,
        printed_page_number=number,
    )


def test_printed_mapping_flags_skip_duplicate_and_offset_change() -> None:
    pages = [
        _page(10, "1", 1, "a"),
        _page(11, "2", 2, "b"),
        _page(12, "2", 2, "c"),
        _page(13, "4", 4, "d"),
        _page(14, "20", 20, "e"),
    ]
    maps = build_page_maps(pages)
    assert maps[0].mapping_status is MappingStatus.CANDIDATE
    assert maps[2].mapping_status is MappingStatus.DISPUTED
    assert "duplicate_printed_page" in maps[2].warnings
    assert "printed_page_skip" in maps[3].warnings
    assert "offset_change" in maps[4].warnings
    assert all(item.mapping_status is not MappingStatus.VERIFIED for item in maps)


def test_passage_page_keeps_order_and_null_offsets() -> None:
    pages = [_page(10, "1", 1, "前半"), _page(11, "2", 2, "后半结束。")]
    maps = build_page_maps(pages)
    passage = PassageCandidate(
        evidence_id="ev_1",
        work_id="work_1",
        section_id="sec_1",
        volume_id="mecw_cn_2009_v01",
        content_type=ContentKind.MAIN_TEXT,
        text="前半后半结束。",
        text_hash="t",
        pdf_page_start=10,
        pdf_page_end=11,
        verification_status=VerificationStatus.UNVERIFIED,
    )
    links = build_passage_pages([passage], pages, maps)
    assert [item.order_no for item in links] == [1, 2]
    assert links[0].start_offset == 0
    assert links[1].end_offset == len("后半结束。")
    missing = PassageCandidate(
        evidence_id="ev_2",
        work_id="work_1",
        section_id="sec_1",
        volume_id="mecw_cn_2009_v01",
        content_type=ContentKind.MAIN_TEXT,
        text="不在页面上的文字",
        text_hash="t",
        pdf_page_start=10,
        pdf_page_end=10,
    )
    unresolved = build_passage_pages([missing], pages, maps)
    assert unresolved[0].start_offset is None
    assert unresolved[0].manual_required is True
