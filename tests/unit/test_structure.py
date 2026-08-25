from marx_engels.ingestion.cleaning import clean_page
from marx_engels.ingestion.id_registry import IdRegistry
from marx_engels.ingestion.layer_models import ContentKind, RawBlock, RawPageRecord
from marx_engels.ingestion.rules import CorpusRules
from marx_engels.ingestion.structure import assert_prev_next_consistent, recognize_structure


def _page(pdf_page: int, blocks: list[RawBlock]) -> RawPageRecord:
    return RawPageRecord(
        volume_id="mecw_cn_2009_v01",
        volume_number=1,
        pdf_page=pdf_page,
        extraction_run_id="run_x",
        chunk_id="c",
        chunk_page_index=pdf_page - 1,
        source_sha256="a" * 64,
        raw_text="\n".join(block.text for block in blocks),
        blocks=blocks,
    )


def test_work_requires_two_signals_and_links_cross_page_paragraph() -> None:
    rules = CorpusRules.load()
    registry = IdRegistry()
    raws = [
        _page(
            1,
            [
                RawBlock(source_type="text", kind="text", text="目录"),
                RawBlock(source_type="text", kind="text", text="《黑格尔法哲学批判》导言 3"),
            ],
        ),
        _page(
            2,
            [
                RawBlock(source_type="text", kind="text", text="卡·马克思"),
                RawBlock(source_type="title", kind="title", text="《黑格尔法哲学批判》导言"),
                RawBlock(
                    source_type="text", kind="text", text="就德国来说，对宗教的批判基本上已经结束"
                ),
            ],
        ),
        _page(
            3,
            [
                RawBlock(source_type="text", kind="text", text="而是其他一切批判的前提。"),
                RawBlock(source_type="page_footnote", kind="footnote", text="①见西塞罗。——编者注"),
            ],
        ),
    ]
    pages = [clean_page(raw, rules, registry)[0] for raw in raws]
    bundle = recognize_structure(pages, rules, registry)
    accepted = [work for work in bundle.works if work.accepted]
    assert len(accepted) == 1
    assert "toc_entry" in accepted[0].signals
    assert "author_line" in accepted[0].signals
    main = [item for item in bundle.passages if item.content_type is ContentKind.MAIN_TEXT]
    joined = next(item for item in main if "就德国来说" in item.text)
    assert "前提。" in joined.text
    assert joined.pdf_page_start == 2
    assert joined.pdf_page_end == 3
    notes = [item for item in bundle.passages if item.content_type is ContentKind.EDITOR_NOTE]
    assert notes
    assert_prev_next_consistent(
        [item for item in bundle.passages if item.work_id == accepted[0].work_id]
    )
    assert all(item.verification_status.value == "unverified" for item in bundle.passages)
    assert all(item.release_status.value == "draft" for item in bundle.passages)


def test_single_title_is_not_a_work() -> None:
    rules = CorpusRules.load()
    registry = IdRegistry()
    raw = _page(1, [RawBlock(source_type="title", kind="title", text="《只有题名》")])
    page, _ = clean_page(raw, rules, registry)
    bundle = recognize_structure([page], rules, registry)
    assert not any(work.accepted for work in bundle.works)
    assert any(issue.code == "weak_work_boundary" for issue in bundle.issues)
