from marx_engels.ingestion.cleaning import clean_page, text_hash
from marx_engels.ingestion.id_registry import IdRegistry
from marx_engels.ingestion.layer_models import RawBlock, RawPageRecord
from marx_engels.ingestion.rules import CorpusRules


def _raw(text: str, *blocks: RawBlock) -> RawPageRecord:
    return RawPageRecord(
        volume_id="mecw_cn_2009_v01",
        volume_number=1,
        pdf_page=10,
        extraction_run_id="run_x",
        chunk_id="chunk",
        chunk_page_index=0,
        source_sha256="a" * 64,
        raw_text=text,
        blocks=list(blocks),
    )


def test_clean_is_idempotent_and_audits_nfc() -> None:
    rules = CorpusRules.load()
    registry = IdRegistry()
    composed = "A\u030a"
    page, records = clean_page(_raw(composed), rules, registry)
    assert page.clean_text == "Å"
    assert any(item.rule_name == "unicode_nfc" for item in records)
    again, second = clean_page(
        _raw(page.clean_text, RawBlock(source_type="text", kind="text", text=page.clean_text)),
        rules,
        registry,
    )
    assert again.text_hash == page.text_hash
    assert not any(item.rule_name == "unicode_nfc" for item in second)


def test_clean_does_not_join_poetry_or_convert_script() -> None:
    rules = CorpusRules.load()
    poetry = _raw(
        "春\n秋\n冬",
        RawBlock(source_type="text", kind="text", text="春"),
        RawBlock(source_type="text", kind="text", text="秋"),
        RawBlock(source_type="text", kind="text", text="冬"),
    )
    page, records = clean_page(poetry, rules, IdRegistry())
    assert page.clean_text.splitlines() == ["春", "秋", "冬"]
    assert all(item.rule_name != "cross_line_join" for item in records)
    traditional = _raw("馬克思", RawBlock(source_type="text", kind="text", text="馬克思"))
    cleaned, _ = clean_page(traditional, rules, IdRegistry())
    assert "馬克思" in cleaned.clean_text
    assert "马克思" not in cleaned.clean_text


def test_header_and_page_number_are_candidates() -> None:
    rules = CorpusRules.load()
    raw = _raw(
        "马克思恩格斯文集\n正文开始。\n12",
        RawBlock(source_type="header", kind="header", text="马克思恩格斯文集"),
        RawBlock(source_type="text", kind="text", text="正文开始。"),
        RawBlock(source_type="page_number", kind="page_number", text="12"),
    )
    page, records = clean_page(raw, rules, IdRegistry())
    assert page.printed_page_label == "12"
    assert page.printed_page_number == 12
    assert "马克思恩格斯文集" not in page.clean_text
    assert any(item.rule_name == "header_footer_candidate" for item in records)
    assert any(item.before_hash and item.after_hash for item in records)
    assert text_hash("正文开始。") == text_hash(page.clean_text) or "正文开始。" in page.clean_text
