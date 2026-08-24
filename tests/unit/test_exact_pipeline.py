from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace

from marx_engels.contracts import (
    AuthorCode,
    Candidate,
    ContentType,
    ReleaseInfo,
    SearchMode,
    SearchRequest,
    SearchScope,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines.exact import ExactPipeline
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord

CORPUS_ID = "synthetic_mecw_test"


class FakeEvidenceRepository:
    def __init__(self, records: Mapping[str, AuthoritativeEvidenceRecord]) -> None:
        self.records = dict(records)
        self.calls: list[tuple[str, ...]] = []

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        self.calls.append(tuple(evidence_ids))
        return {
            evidence_id: self.records[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.records
        }


class FakeExactIndex:
    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self.candidates = list(candidates)
        self.queries: list[tuple[str, SearchScope, int]] = []

    async def search_exact(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        self.queries.append((query, scope, limit))
        return list(self.candidates[:limit])


class FakeScopeResolver:
    def __init__(self) -> None:
        self.seen: list[SearchScope] = []

    async def resolve(self, scope: SearchScope) -> SearchScope:
        self.seen.append(scope)
        return scope


class FakeReleaseResolver:
    def __init__(self, release: ReleaseInfo | None = None) -> None:
        self.release = release or ReleaseInfo(data_version="data_synthetic_v1")
        self.scopes: list[SearchScope] = []

    async def resolve_exact(self, scope: SearchScope) -> ReleaseInfo:
        self.scopes.append(scope)
        return self.release


def make_record(evidence_id: str, **overrides: object) -> AuthoritativeEvidenceRecord:
    record = AuthoritativeEvidenceRecord(
        evidence_id=evidence_id,
        verified_text="【合成数据，非原典】协作劳动会改变群体之间的关系，劳动也会塑造新的交往方式。",
        text_hash="hash_ok",
        verification_status="verified",
        release_status="published",
        content_type=ContentType.MAIN_TEXT.value,
        author_code=AuthorCode.MARX.value,
        author="马克思",
        work_title="[合成] 早期协作材料",
        corpus_id=CORPUS_ID,
        corpus_name="合成测试语料",
        edition_id="synthetic_edition_v1",
        edition_label="合成测试版",
        volume_id="syn_v01",
        volume_no=1,
        work_id="syn_work_early",
        work_date_start="1845",
        work_date_end="1845",
        date_precision="year",
        corpus_release_status="published",
        edition_release_status="published",
        volume_release_status="published",
        work_release_status="published",
        work_verification_status="verified",
        section_verification_status="verified",
        printed_pages=("1",),
        pdf_pages=(10,),
        page_mapping_statuses=("verified",),
        prev_evidence_id=None,
        next_evidence_id=None,
        prev_is_released=False,
        next_is_released=False,
    )
    return replace(record, **overrides)  # type: ignore[arg-type]


def make_pipeline(
    *,
    records: Mapping[str, AuthoritativeEvidenceRecord],
    candidates: Sequence[Candidate],
) -> tuple[ExactPipeline, FakeExactIndex]:
    index = FakeExactIndex(candidates)
    pipeline = ExactPipeline(
        scope_resolver=FakeScopeResolver(),
        exact_index=index,
        evidence_service=EvidenceService(FakeEvidenceRepository(records)),
        release_resolver=FakeReleaseResolver(),
    )
    return pipeline, index


def execute(pipeline: ExactPipeline, request: SearchRequest) -> object:
    return asyncio.run(pipeline.execute(request, "req_test"))


def test_keeps_user_query_and_normalizes_match_value_once() -> None:
    records = {
        "ev_a": make_record("ev_a"),
        "ev_b": make_record(
            "ev_b",
            verified_text="【合成数据，非原典】不能把所有社会变化都简单归因于协作劳动。",
            work_id="syn_work_mid",
            volume_id="syn_v01",
            printed_pages=("4",),
            pdf_pages=(13,),
        ),
    }
    pipeline, index = make_pipeline(
        records=records,
        candidates=[
            Candidate(evidence_id="ev_a", channels=["exact"]),
            Candidate(evidence_id="ev_b", channels=["exact"]),
        ],
    )
    request = SearchRequest(
        query=" 劳动",
        mode=SearchMode.EXACT,
        scope=SearchScope(corpus_ids=[CORPUS_ID]),
        page_size=20,
    )
    response = execute(pipeline, request)
    assert response.query == " 劳动"
    assert index.queries == [("劳动", request.scope, 20)]
    assert [item.evidence_id for item in response.evidence] == ["ev_a", "ev_b"]
    assert response.evidence[0].exact_match_count == 2
    assert response.evidence[1].exact_match_count == 1
    assert response.next_cursor is None
    assert response.overview.work_count == 2
    assert response.overview.volume_count == 1
    assert response.release.index_version is None


def test_document_order_is_volume_page_and_id() -> None:
    records = {
        "ev_late": make_record(
            "ev_late",
            verified_text="【合成数据，非原典】劳动出现较晚。",
            volume_id="syn_v02",
            volume_no=2,
            work_id="syn_work_late",
            printed_pages=("101",),
            pdf_pages=(10,),
        ),
        "ev_early": make_record(
            "ev_early",
            verified_text="【合成数据，非原典】劳动出现较早。",
            volume_id="syn_v01",
            volume_no=1,
            work_id="syn_work_early",
            printed_pages=("10",),
            pdf_pages=(19,),
        ),
    }
    pipeline, _index = make_pipeline(
        records=records,
        candidates=[
            Candidate(evidence_id="ev_late", channels=["exact"]),
            Candidate(evidence_id="ev_early", channels=["exact"]),
        ],
    )
    scope = SearchScope(corpus_ids=[CORPUS_ID])
    relevance = execute(
        pipeline,
        SearchRequest(query="劳动", mode=SearchMode.EXACT, scope=scope),
    )
    document_order = execute(
        pipeline,
        SearchRequest(
            query="劳动",
            mode=SearchMode.EXACT,
            scope=scope,
            sort="document_order",
        ),
    )
    assert [item.evidence_id for item in relevance.evidence] == ["ev_late", "ev_early"]
    assert [item.evidence_id for item in document_order.evidence] == ["ev_early", "ev_late"]


def test_empty_result_is_a_legal_search_response() -> None:
    pipeline, _index = make_pipeline(records={}, candidates=[])
    response = execute(
        pipeline,
        SearchRequest(
            query="不存在词组",
            mode=SearchMode.EXACT,
            scope=SearchScope(corpus_ids=[CORPUS_ID]),
        ),
    )
    assert response.evidence == []
    assert response.overview.evidence_count == 0
    assert response.overview.work_count == 0
    assert response.overview.volume_count == 0
    assert response.next_cursor is None
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_EXACT_MATCH"


def test_rejects_non_exact_mode() -> None:
    pipeline, _index = make_pipeline(records={}, candidates=[])
    try:
        execute(
            pipeline,
            SearchRequest(
                query="劳动",
                mode=SearchMode.CLAIM,
                scope=SearchScope(corpus_ids=[CORPUS_ID]),
            ),
        )
    except DomainError as error:
        assert error.code == "INVALID_REQUEST"
    else:
        raise AssertionError("non-exact mode was accepted")


def test_binds_release_after_scope_resolution() -> None:
    order: list[str] = []

    class RecordingScope(FakeScopeResolver):
        async def resolve(self, scope: SearchScope) -> SearchScope:
            order.append("scope")
            return await super().resolve(scope)

    class RecordingRelease(FakeReleaseResolver):
        async def resolve_exact(self, scope: SearchScope) -> ReleaseInfo:
            order.append("release")
            return await super().resolve_exact(scope)

    pipeline = ExactPipeline(
        scope_resolver=RecordingScope(),
        exact_index=FakeExactIndex([]),
        evidence_service=EvidenceService(FakeEvidenceRepository({})),
        release_resolver=RecordingRelease(),
    )
    execute(
        pipeline,
        SearchRequest(
            query="劳动",
            mode=SearchMode.EXACT,
            scope=SearchScope(corpus_ids=[CORPUS_ID]),
        ),
    )
    assert order == ["scope", "release"]
