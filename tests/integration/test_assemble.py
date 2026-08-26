import json
from pathlib import Path

import pytest

from marx_engels.ingestion.assemble import assemble_corpus
from marx_engels.ingestion.paths import CorpusLayout
from tests.helpers import seed_completed_all_run


def _work_pages() -> list[list[dict[str, object]]]:
    return [
        [
            {"type": "header", "text": "马克思恩格斯文集"},
            {"type": "text", "text": "目录"},
            {"type": "text", "text": "《黑格尔法哲学批判》导言 3"},
        ],
        [
            {"type": "text", "text": "卡·马克思"},
            {"type": "title", "text": "《黑格尔法哲学批判》导言", "text_level": 1},
            {"type": "text", "text": "就德国来说，对宗教的批判基本上已经结束"},
            {"type": "page_number", "text": "1"},
        ],
        [
            {"type": "text", "text": "而是其他一切批判的前提。"},
            {"type": "page_footnote", "text": "①见西塞罗。——编者注"},
            {"type": "page_number", "text": "2"},
        ],
        [
            {"type": "text", "text": "一、历史前提"},
            {"type": "text", "text": "　这是一个新的自然段。"},
            {"type": "page_number", "text": "3"},
        ],
        [
            {"type": "text", "text": "（完）"},
            {"type": "page_number", "text": "4"},
        ],
        [
            {"type": "text", "text": "人名索引"},
            {"type": "page_number", "text": "5"},
        ],
    ]


@pytest.mark.integration
def test_assemble_raw_to_ids_without_mineru(tmp_path: Path) -> None:
    seed_completed_all_run(tmp_path, volume_pages={1: _work_pages()}, chunk_size=3)
    layout = CorpusLayout(tmp_path)
    report = assemble_corpus(layout, extraction_run_id="run_test_all")
    assert report["chunks"] == 2
    assert report["recovered_pages"] == 6
    assert report["clean_pages"] == 6
    assert report["works"] >= 1
    assert report["passages"] >= 1
    assert report["evidence_ids"] == report["passages"]
    assert report["passage_pages"] >= report["passages"]
    assert report["all_passages_unverified_draft"] is True
    second = assemble_corpus(layout, extraction_run_id="run_test_all")
    first_ids = {
        item["evidence_id"]
        for item in json.loads(
            (
                layout.passage_dir(str(report["assemble_run_id"])) / "mecw_cn_2009_v01.json"
            ).read_text(encoding="utf-8")
        )
    }
    second_ids = {
        item["evidence_id"]
        for item in json.loads(
            (
                layout.passage_dir(str(second["assemble_run_id"])) / "mecw_cn_2009_v01.json"
            ).read_text(encoding="utf-8")
        )
    }
    assert first_ids == second_ids
    assert (layout.clean_pages / str(report["clean_run_id"])).is_dir()
    assert (layout.clean_pages / str(second["clean_run_id"])).is_dir()
    assert report["clean_run_id"] != second["clean_run_id"]
