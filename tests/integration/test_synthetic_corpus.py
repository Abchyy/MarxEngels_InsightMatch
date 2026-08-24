import asyncio
import json
from pathlib import Path

import pytest

from marx_engels.contracts import SearchScope
from marx_engels.evaluation import validate_golden_dataset
from marx_engels.storage import SQLiteExactSearchIndex
from tests.synthetic_corpus.builder import FIXTURE_ROOT, build_synthetic_corpus


@pytest.mark.integration
def test_synthetic_fixture_builds_authoritative_sqlite_and_vectors(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")

    assert build.fixture_version == "synthetic_corpus_v1"
    assert "禁止作为引文" in build.notice
    assert len(build.vector_records) == 10
    assert all(len(record["vector"]) == 4 for record in build.vector_records)

    with build.database.connect() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        published = connection.execute(
            """
            SELECT count(*)
            FROM passage AS p
            JOIN section AS s ON s.section_id = p.section_id
            JOIN work AS w ON w.work_id = s.work_id
            JOIN volume AS v ON v.volume_id = w.volume_id
            JOIN edition AS e ON e.edition_id = v.edition_id
            WHERE e.corpus_id = 'synthetic_mecw_test'
              AND p.verification_status = 'verified'
              AND p.release_status = 'published'
            """
        ).fetchone()[0]
        assert published == 9
        assert connection.execute("SELECT count(*) FROM passage_fts").fetchone()[0] == 10
        assert connection.execute("SELECT count(*) FROM index_outbox").fetchone()[0] == 10


@pytest.mark.integration
def test_synthetic_exact_truth_is_scope_and_release_safe(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    index = SQLiteExactSearchIndex(build.database)

    target = asyncio.run(
        index.search_exact(
            "劳动",
            SearchScope(corpus_ids=["synthetic_mecw_test"]),
            limit=20,
        )
    )
    assert [candidate.evidence_id for candidate in target] == [
        "ev_syn_early_001",
        "ev_syn_mid_002",
    ]
    assert [candidate.exact_match_count for candidate in target] == [2, 1]
    assert all(candidate.channels == ["exact"] for candidate in target)

    decoy = asyncio.run(
        index.search_exact(
            "劳动",
            SearchScope(corpus_ids=["synthetic_scope_decoy"]),
            limit=20,
        )
    )
    assert [candidate.evidence_id for candidate in decoy] == ["ev_syn_decoy_001"]


@pytest.mark.integration
def test_synthetic_cross_page_and_context_links_are_consistent(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    with build.database.connect() as connection:
        pages = connection.execute(
            """
            SELECT pm.printed_page_label, pm.pdf_page
            FROM passage_page AS pp
            JOIN page_map AS pm ON pm.page_id = pp.page_id
            WHERE pp.evidence_id = 'ev_syn_mid_crosspage'
            ORDER BY pp.order_no
            """
        ).fetchall()
        assert [(row[0], row[1]) for row in pages] == [("4", 13), ("5", 14)]
        links = connection.execute(
            """
            SELECT evidence_id, prev_id, next_id
            FROM passage
            WHERE section_id = 'syn_sec_mid'
            ORDER BY order_no
            """
        ).fetchall()
        assert [(row[0], row[1], row[2]) for row in links] == [
            ("ev_syn_mid_001", None, "ev_syn_mid_002"),
            ("ev_syn_mid_002", "ev_syn_mid_001", "ev_syn_mid_crosspage"),
            ("ev_syn_mid_crosspage", "ev_syn_mid_002", None),
        ]


def test_synthetic_cases_are_complete_and_never_claim_human_review() -> None:
    case_dir = FIXTURE_ROOT / "cases"
    expected_files = {
        "exact_cases.jsonl",
        "claim_cases.jsonl",
        "timeline_cases.jsonl",
        "thematic_cases.jsonl",
        "evidence_gate_cases.jsonl",
    }
    assert {path.name for path in case_dir.glob("*.jsonl")} == expected_files

    case_ids: set[str] = set()
    for path in sorted(case_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            assert payload["dataset_version"] == "synthetic_corpus_v1"
            assert payload["annotator"].startswith("codex-synthetic-")
            assert payload["reviewer"].startswith("codex-synthetic-")
            assert payload["case_id"] not in case_ids
            case_ids.add(payload["case_id"])


def test_synthetic_cases_pass_shared_golden_structure_validation() -> None:
    report = validate_golden_dataset(FIXTURE_ROOT / "cases")

    assert report.ok is True
    assert report.case_count == 6
    assert report.dataset_version == "synthetic_corpus_v1"
    assert report.issues == ()


def test_synthetic_builder_refuses_to_overwrite_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "existing.db"
    path.write_bytes(b"not a database")
    with pytest.raises(FileExistsError):
        build_synthetic_corpus(path)
