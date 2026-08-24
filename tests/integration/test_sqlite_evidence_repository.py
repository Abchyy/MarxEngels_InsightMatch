from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest

from marx_engels.contracts import Candidate, SearchScope
from marx_engels.evidence import EvidenceExclusionReason, EvidenceService, ExactMatchQuery
from marx_engels.storage import SQLiteEvidenceRepository
from marx_engels.storage import sqlite as sqlite_adapter
from tests.synthetic_corpus.builder import build_synthetic_corpus

pytestmark = pytest.mark.integration

SYNTHETIC_SCOPE = SearchScope(corpus_ids=["synthetic_mecw_test"])
FORBIDDEN = ("ev_syn_unpublished_001", "ev_syn_unverified_001", "ev_syn_decoy_001")


def _build(tmp_path: Path) -> SQLiteEvidenceRepository:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    return SQLiteEvidenceRepository(build.database)


def _get(repository: SQLiteEvidenceRepository, *evidence_ids: str):
    return asyncio.run(repository.get_by_ids(evidence_ids))


def test_batch_read_omits_missing_ids_and_deduplicates_input(tmp_path: Path) -> None:
    repository = _build(tmp_path)
    observed_sql: list[str] = []
    original_connect = repository._database.connect

    def connect(*, create_parent: bool = False) -> sqlite3.Connection:
        connection = original_connect(create_parent=create_parent)
        connection.set_trace_callback(observed_sql.append)
        return connection

    repository._database.connect = connect  # type: ignore[method-assign]
    records = _get(
        repository,
        "ev_syn_early_001",
        "missing_id",
        "ev_syn_early_001",
        "ev_syn_mid_crosspage",
    )

    assert set(records) == {"ev_syn_early_001", "ev_syn_mid_crosspage"}
    assert "missing_id" not in records
    select_statements = [
        statement for statement in observed_sql if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(select_statements) == 2
    joined = "\n".join(observed_sql).lower()
    assert "passage_fts" not in joined
    assert "search_text" not in joined


def test_cross_page_printed_and_pdf_order_follows_passage_page(tmp_path: Path) -> None:
    records = _get(_build(tmp_path), "ev_syn_mid_crosspage")
    record = records["ev_syn_mid_crosspage"]
    assert record.printed_pages == ("4", "5")
    assert record.pdf_pages == (13, 14)
    assert record.page_mapping_statuses == ("verified", "verified")
    assert record.verified_text.startswith("【合成数据，非原典】")
    assert "[合成语料]" not in record.verified_text
    assert "search_text" not in record.__dataclass_fields__


def test_unpublished_neighbor_is_marked_unreleased(tmp_path: Path) -> None:
    records = _get(_build(tmp_path), "ev_syn_unknown_001")
    record = records["ev_syn_unknown_001"]
    assert record.next_evidence_id == "ev_syn_unpublished_001"
    assert record.next_is_released is False


def test_evidence_service_blocks_unpublished_unverified_and_out_of_scope(
    tmp_path: Path,
) -> None:
    repository = _build(tmp_path)
    service = EvidenceService(repository)
    candidates = [
        Candidate(evidence_id="ev_syn_early_001", channels=["exact"]),
        Candidate(evidence_id="ev_syn_unpublished_001", channels=["exact"]),
        Candidate(evidence_id="ev_syn_unverified_001", channels=["exact"]),
        Candidate(evidence_id="ev_syn_decoy_001", channels=["exact"]),
    ]
    result = asyncio.run(
        service.hydrate(
            candidates,
            SYNTHETIC_SCOPE,
            exact_query=ExactMatchQuery(query="劳动"),
        )
    )
    assert [item.evidence_id for item in result.evidence] == ["ev_syn_early_001"]
    exclusions = {item.evidence_id: item.reason for item in result.exclusions}
    assert exclusions["ev_syn_unpublished_001"] is EvidenceExclusionReason.NOT_PUBLISHED
    assert exclusions["ev_syn_unverified_001"] is EvidenceExclusionReason.NOT_VERIFIED
    assert exclusions["ev_syn_decoy_001"] is EvidenceExclusionReason.OUT_OF_SCOPE
    assert result.evidence[0].exact_match_count == 2
    assert all(item.evidence_id not in FORBIDDEN for item in result.evidence)


def test_cross_work_and_cross_corpus_neighbors_are_not_public(tmp_path: Path) -> None:
    repository = _build(tmp_path)
    database = repository._database
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE passage
            SET prev_id = 'ev_syn_decoy_001', next_id = 'ev_syn_late_001'
            WHERE evidence_id = 'ev_syn_early_001'
            """
        )
    records = _get(repository, "ev_syn_early_001", "ev_syn_mid_002")
    early = records["ev_syn_early_001"]
    mid = records["ev_syn_mid_002"]
    assert early.prev_evidence_id == "ev_syn_decoy_001"
    assert early.next_evidence_id == "ev_syn_late_001"
    assert early.prev_is_released is False
    assert early.next_is_released is False
    assert mid.next_evidence_id == "ev_syn_mid_crosspage"
    assert mid.next_is_released is True

    result = asyncio.run(
        EvidenceService(repository).hydrate(
            [
                Candidate(evidence_id="ev_syn_early_001", channels=["exact"]),
                Candidate(evidence_id="ev_syn_mid_002", channels=["exact"]),
            ],
            SYNTHETIC_SCOPE,
            exact_query=ExactMatchQuery(query="劳动"),
        )
    )
    by_id = {item.evidence_id: item for item in result.evidence}
    public_early = by_id["ev_syn_early_001"].model_dump()
    assert public_early["prev_evidence_id"] is None
    assert public_early["next_evidence_id"] is None
    assert "ev_syn_late_001" not in public_early.values()
    assert "ev_syn_decoy_001" not in public_early.values()
    assert by_id["ev_syn_mid_002"].next_evidence_id == "ev_syn_mid_crosspage"



def test_sqlite_work_runs_on_one_worker_not_the_event_loop(tmp_path: Path) -> None:
    repository = _build(tmp_path)
    database = repository._database
    observed: dict[str, int] = {}
    original_connect = database.connect
    original_sqlite_connect = sqlite_adapter.sqlite3.connect

    class TracingConnection(sqlite3.Connection):
        def execute(self, *args: object, **kwargs: object) -> sqlite3.Cursor:
            observed["execute"] = threading.get_ident()
            cursor = super().execute(*args, **kwargs)
            original_fetchall = cursor.fetchall

            def fetchall() -> list[sqlite3.Row]:
                observed["fetchall"] = threading.get_ident()
                return original_fetchall()

            try:
                cursor.fetchall = fetchall  # type: ignore[method-assign]
            except AttributeError:
                observed["fetchall"] = observed["execute"]
            return cursor

        def close(self) -> None:
            observed["close"] = threading.get_ident()
            super().close()

    def sqlite_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = TracingConnection
        return original_sqlite_connect(*args, **kwargs)

    def connect(*, create_parent: bool = False) -> sqlite3.Connection:
        observed["connect"] = threading.get_ident()
        return original_connect(create_parent=create_parent)

    database.connect = connect  # type: ignore[method-assign]
    sqlite_adapter.sqlite3.connect = sqlite_connect  # type: ignore[method-assign]

    async def run_from_event_loop() -> tuple[int, object]:
        loop_ident = threading.get_ident()
        records = await repository.get_by_ids(["ev_syn_early_001"])
        return loop_ident, records

    try:
        loop_ident, records = asyncio.run(run_from_event_loop())
    finally:
        sqlite_adapter.sqlite3.connect = original_sqlite_connect  # type: ignore[method-assign]

    assert records
    worker_ids = {observed[key] for key in ("connect", "execute", "fetchall", "close")}
    assert len(worker_ids) == 1
    assert loop_ident not in worker_ids
