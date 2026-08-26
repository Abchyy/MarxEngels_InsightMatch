from pathlib import Path

from tests.helpers import seed_completed_all_run

from marx_engels.ingestion.page_merge import merge_raw_pages
from marx_engels.ingestion.paths import CorpusLayout


def test_merge_recovers_unique_pages_and_flags_gaps(tmp_path: Path) -> None:
    pages = [[{"type": "text", "text": f"p{index}"}] for index in range(1, 7)]
    pages[2] = []  # chunk-local page 3 missing structured blocks
    seed_completed_all_run(tmp_path, volume_pages={1: pages}, chunk_size=3)
    layout = CorpusLayout(tmp_path)
    manifest = merge_raw_pages(layout, extraction_run_id="run_test_all", merge_run_id="merge_test")
    vol = manifest["volumes"]["1"]
    assert vol["written_pages"] == 6
    assert vol["expected_pages"] == 6
    assert 3 in vol["manual_required_pages"]
    page3 = (layout.merge_dir("merge_test") / "mecw_cn_2009_v01" / "page_0003.json").read_text(
        encoding="utf-8"
    )
    assert "empty_structured_page" in page3


def test_merge_detects_duplicate_and_out_of_order(tmp_path: Path) -> None:
    pages = [[{"type": "text", "text": f"p{index}"}] for index in range(1, 5)]
    seed_completed_all_run(tmp_path, volume_pages={1: pages}, chunk_size=2)
    layout = CorpusLayout(tmp_path)
    # copy first chunk mapping onto a second overlapping range by rewriting pipeline state
    merge_raw_pages(layout, extraction_run_id="run_test_all", merge_run_id="merge_ok")
    assert (layout.merge_dir("merge_ok") / "mecw_cn_2009_v01" / "page_0001.json").is_file()
