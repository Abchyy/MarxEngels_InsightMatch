from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from marx_engels.contracts import SearchMode, SearchRequest, SearchScope
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines.exact import ExactPipeline
from marx_engels.settings import Settings
from marx_engels.storage import (
    SQLiteEvidenceRepository,
    SQLiteExactSearchIndex,
    SQLiteReleaseResolver,
    SQLiteScopeResolver,
)
from tests.synthetic_corpus.builder import build_synthetic_corpus

pytestmark = pytest.mark.integration

SCOPE = SearchScope(corpus_ids=["synthetic_mecw_test"])
FORBIDDEN = {"ev_syn_unpublished_001", "ev_syn_unverified_001", "ev_syn_decoy_001"}


def _pipeline(tmp_path: Path) -> ExactPipeline:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        app_env="test",
    )
    return ExactPipeline(
        scope_resolver=SQLiteScopeResolver(build.database),
        exact_index=SQLiteExactSearchIndex(build.database),
        evidence_service=EvidenceService(SQLiteEvidenceRepository(build.database)),
        release_resolver=SQLiteReleaseResolver(build.database, settings),
    )


def _execute(pipeline: ExactPipeline, request: SearchRequest):
    return asyncio.run(pipeline.execute(request, "req_synthetic"))


def test_labor_query_returns_two_authoritative_hits(tmp_path: Path) -> None:
    response = _execute(
        _pipeline(tmp_path),
        SearchRequest(query="劳动", mode=SearchMode.EXACT, scope=SCOPE),
    )
    ids = [item.evidence_id for item in response.evidence]
    assert ids == ["ev_syn_early_001", "ev_syn_mid_002"]
    assert [item.exact_match_count for item in response.evidence] == [2, 1]
    assert all(item.verified_text.startswith("【合成数据，非原典】") for item in response.evidence)
    assert FORBIDDEN.isdisjoint(ids)
    assert all("[合成语料]" not in item.verified_text for item in response.evidence)
    assert response.overview.work_count == 2
    assert response.overview.volume_count == 1
    assert response.next_cursor is None
    assert response.release.data_version == "data_synthetic_v1"
    assert response.release.index_version is None


def test_document_order_is_stable_and_differs_from_relevance_when_pages_differ(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)
    relevance = _execute(
        pipeline,
        SearchRequest(query="公共讨论", mode=SearchMode.EXACT, scope=SCOPE),
    )
    document_order = _execute(
        pipeline,
        SearchRequest(
            query="公共讨论",
            mode=SearchMode.EXACT,
            scope=SCOPE,
            sort="document_order",
        ),
    )
    relevance_ids = [item.evidence_id for item in relevance.evidence]
    document_ids = [item.evidence_id for item in document_order.evidence]
    assert document_ids == [
        "ev_syn_early_002",
        "ev_syn_mid_001",
        "ev_syn_disputed_001",
        "ev_syn_late_001",
        "ev_syn_unknown_001",
    ]
    assert set(relevance_ids) == set(document_ids)
    assert relevance_ids != document_ids
    assert FORBIDDEN.isdisjoint(document_ids)


def test_empty_exact_result_is_legal(tmp_path: Path) -> None:
    response = _execute(
        _pipeline(tmp_path),
        SearchRequest(query="不存在词组", mode=SearchMode.EXACT, scope=SCOPE),
    )
    assert response.evidence == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_EXACT_MATCH"
    assert response.overview.evidence_count == 0
    assert response.next_cursor is None


def test_page_size_does_not_return_empty_when_top_hit_is_unpublished(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    with build.database.connect() as connection:
        connection.execute(
            "UPDATE work SET release_status = 'draft' WHERE work_id = 'syn_work_early'"
        )
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        app_env="test",
    )
    pipeline = ExactPipeline(
        scope_resolver=SQLiteScopeResolver(build.database),
        exact_index=SQLiteExactSearchIndex(build.database),
        evidence_service=EvidenceService(SQLiteEvidenceRepository(build.database)),
        release_resolver=SQLiteReleaseResolver(build.database, settings),
    )
    response = _execute(
        pipeline,
        SearchRequest(query="劳动", mode=SearchMode.EXACT, scope=SCOPE, page_size=1),
    )
    assert [item.evidence_id for item in response.evidence] == ["ev_syn_mid_002"]
    assert response.evidence[0].verified_text.startswith("【合成数据，非原典】")
    assert response.insufficiency is None
