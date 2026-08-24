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
    SearchOptions,
    SearchOverview,
    SearchRequest,
    SearchScope,
    SupportLabel,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines.claim import ClaimPipeline
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord
from marx_engels.retrieval_core.rrf import reciprocal_rank_fusion, stable_score_order

CORPUS_ID = "marx_engels_collected_works_cn"


class FakeEvidenceRepository:
    def __init__(self, records: Mapping[str, AuthoritativeEvidenceRecord] | None = None) -> None:
        self.records = dict(records or {})

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        return {
            evidence_id: self.records[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.records
        }


def make_record(evidence_id: str = "ev_ok", **overrides: object) -> AuthoritativeEvidenceRecord:
    record = AuthoritativeEvidenceRecord(
        evidence_id=evidence_id,
        verified_text="人人平等",
        text_hash="hash_ok",
        verification_status="verified",
        release_status="published",
        content_type=ContentType.MAIN_TEXT.value,
        author_code=AuthorCode.MARX.value,
        author="马克思",
        work_title="关于费尔巴哈的提纲",
        corpus_id=CORPUS_ID,
        corpus_name="马克思恩格斯文集",
        edition_id="people_press_2009_cn",
        edition_label="人民出版社2009年版",
        volume_id="vol_1",
        volume_no=1,
        work_id="work_1",
        work_date_start="1845",
        work_date_end="1845",
        date_precision="year",
        corpus_release_status="published",
        edition_release_status="published",
        volume_release_status="published",
        work_release_status="published",
        work_verification_status="verified",
        section_verification_status="verified",
        printed_pages=("123",),
        pdf_pages=(145,),
        page_mapping_statuses=("verified",),
        prev_evidence_id="ev_prev",
        next_evidence_id="ev_next",
        prev_is_released=True,
        next_is_released=True,
    )
    return replace(record, **overrides)  # type: ignore[arg-type]


def make_candidate(evidence_id: str = "ev_ok", **overrides: object) -> Candidate:
    payload: dict[str, object] = {"evidence_id": evidence_id, "channels": ["lexical"]}
    payload.update(overrides)
    return Candidate.model_validate(payload)


def make_scope(**overrides: object) -> SearchScope:
    payload: dict[str, object] = {"corpus_ids": [CORPUS_ID]}
    payload.update(overrides)
    return SearchScope.model_validate(payload)


class FakeScopeResolver:
    def __init__(self, resolved: SearchScope | None = None) -> None:
        self.resolved = resolved
        self.calls: list[SearchScope] = []

    async def resolve(self, scope: SearchScope) -> SearchScope:
        self.calls.append(scope)
        return self.resolved if self.resolved is not None else scope


class FakeLexicalIndex:
    def __init__(self, hits: Sequence[Candidate] | Exception = ()) -> None:
        self.hits = hits
        self.calls: list[tuple[str, SearchScope, int]] = []

    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        self.calls.append((query, scope, limit))
        if isinstance(self.hits, Exception):
            raise self.hits
        return list(self.hits)


class FakeVectorIndex:
    def __init__(self, hits: Sequence[Candidate] | Exception = ()) -> None:
        self.hits = hits
        self.calls: list[tuple[tuple[float, ...], SearchScope, int]] = []

    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]:
        self.calls.append((tuple(vector), scope, limit))
        if isinstance(self.hits, Exception):
            raise self.hits
        return list(self.hits)


class FakeEmbeddingProvider:
    def __init__(
        self, vectors: Sequence[Sequence[float]] | Exception = ((0.1, 0.2),)
    ) -> None:
        self.vectors = vectors
        self.calls: list[tuple[str, ...]] = []

    @property
    def model_version(self) -> str:
        return "fake-embed-v1"

    @property
    def dimension(self) -> int:
        return 2

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(tuple(texts))
        if isinstance(self.vectors, Exception):
            raise self.vectors
        return [list(vector) for vector in self.vectors]


class FakeReranker:
    def __init__(self, hits: Sequence[Candidate] | Exception | None = None) -> None:
        self.hits = hits
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    @property
    def model_version(self) -> str:
        return "fake-rerank-v1"

    async def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        self.calls.append((query, tuple(item.evidence_id for item in candidates)))
        if isinstance(self.hits, Exception):
            raise self.hits
        if self.hits is None:
            return [
                item.model_copy(update={"rerank_score": 1.0 - index * 0.1})
                for index, item in enumerate(candidates)
            ]
        return list(self.hits)


class FakeLanguageModel:
    def __init__(self, payload: Mapping[str, object] | Exception | None = None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    @property
    def model_version(self) -> str:
        return "fake-llm-v1"

    async def generate_structured(
        self, task: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append((task, payload))
        if isinstance(self.payload, Exception):
            raise self.payload
        if self.payload is not None:
            return dict(self.payload)
        return {"classifications": _direct_labels_from_payload(payload)}


class FakeReleaseProvider:
    def __init__(
        self,
        release: ReleaseInfo | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.release = release or ReleaseInfo(
            data_version="data_test_v1",
            index_version="idx_test_v1",
            embedding_model="fake-embed-v1",
            released_at="2026-08-24T00:00:00Z",
        )
        self.error = error
        self.calls: list[SearchScope] = []

    async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo:
        self.calls.append(scope)
        if self.error is not None:
            raise self.error
        return self.release


class FakeOverviewProvider:
    def __init__(self, work_ids: Mapping[str, str], volume_ids: Mapping[str, str]) -> None:
        self.work_ids = dict(work_ids)
        self.volume_ids = dict(volume_ids)
        self.calls: list[tuple[str, ...]] = []

    async def overview_for(self, evidence_ids: Sequence[str]) -> SearchOverview:
        self.calls.append(tuple(evidence_ids))
        works = {self.work_ids[item] for item in evidence_ids if item in self.work_ids}
        volumes = {self.volume_ids[item] for item in evidence_ids if item in self.volume_ids}
        return SearchOverview(
            evidence_count=len(tuple(evidence_ids)),
            work_count=len(works),
            volume_count=len(volumes),
        )


def _direct_labels_from_payload(payload: Mapping[str, object]) -> list[dict[str, str]]:
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return []
    labels: list[dict[str, str]] = []
    for item in raw_candidates:
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str):
            labels.append({"evidence_id": str(item["evidence_id"]), "support_label": "direct"})
    return labels


def _request(
    query: str = "社会存在决定社会意识",
    *,
    include_counter_evidence: bool = True,
    scope: SearchScope | None = None,
    mode: SearchMode = SearchMode.CLAIM,
    page_size: int = 20,
) -> SearchRequest:
    return SearchRequest(
        query=query,
        mode=mode,
        scope=scope or make_scope(),
        page_size=page_size,
        options=SearchOptions(include_counter_evidence=include_counter_evidence),
    )


def _pipeline(**overrides: object) -> ClaimPipeline:
    repository = overrides.pop(
        "repository",
        FakeEvidenceRepository({"ev_a": make_record("ev_a"), "ev_b": make_record("ev_b")}),
    )
    kwargs: dict[str, object] = {
        "scope_resolver": FakeScopeResolver(),
        "lexical_index": FakeLexicalIndex([make_candidate("ev_a", channels=["lexical"])]),
        "vector_index": FakeVectorIndex(
            [make_candidate("ev_b", channels=["vector"], vector_rank=1, text_hash="hash_ok")]
        ),
        "embedding_provider": FakeEmbeddingProvider(),
        "reranker": FakeReranker(),
        "language_model": FakeLanguageModel(),
        "evidence_service": EvidenceService(repository),  # type: ignore[arg-type]
        "evidence_repository": repository,
        "release_provider": FakeReleaseProvider(),
        "overview_provider": FakeOverviewProvider(
            {"ev_a": "work_1", "ev_b": "work_1"},
            {"ev_a": "vol_1", "ev_b": "vol_1"},
        ),
    }
    kwargs.update(overrides)
    return ClaimPipeline(**kwargs)  # type: ignore[arg-type]


def _execute(pipeline: ClaimPipeline, request: SearchRequest | None = None) -> object:
    return asyncio.run(pipeline.execute(request or _request(), "req_claim_1"))


def test_rejects_non_claim_mode() -> None:
    pipeline = _pipeline()
    try:
        _execute(pipeline, _request(mode=SearchMode.EXACT))
    except DomainError as exc:
        assert exc.code == "INVALID_REQUEST"
    else:
        raise AssertionError("non-claim mode was accepted")


def test_lexical_vector_fusion_uses_stable_rrf_order() -> None:
    lexical = [
        make_candidate("ev_p", channels=["lexical"]),
        make_candidate("ev_q", channels=["lexical"]),
    ]
    vector = [
        make_candidate("ev_q", channels=["vector"], vector_rank=1, text_hash="hash_ok"),
        make_candidate("ev_p", channels=["vector"], vector_rank=2, text_hash="hash_ok"),
    ]
    scores = reciprocal_rank_fusion(
        [["ev_p", "ev_q"], ["ev_q", "ev_p"]], rank_constant=60
    )
    assert scores["ev_p"] == scores["ev_q"]
    assert stable_score_order(scores) == ["ev_p", "ev_q"]

    repository = FakeEvidenceRepository(
        {"ev_p": make_record("ev_p"), "ev_q": make_record("ev_q")}
    )
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(lexical),
        vector_index=FakeVectorIndex(vector),
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": "ev_p", "support_label": "direct"},
                    {"evidence_id": "ev_q", "support_label": "direct"},
                ]
            }
        ),
        overview_provider=FakeOverviewProvider(
            {"ev_p": "work_1", "ev_q": "work_2"},
            {"ev_p": "vol_1", "ev_q": "vol_1"},
        ),
    )
    response = _execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_p", "ev_q"]
    assert {item.match_type for item in response.evidence} == {"hybrid"}


def test_reranker_unauthorized_ids_are_dropped_and_recorded() -> None:
    original = [
        make_candidate("ev_a", channels=["lexical"]),
        make_candidate("ev_b", channels=["vector"], vector_rank=1, text_hash="hash_ok"),
    ]
    reranked = [
        make_candidate("ev_injected", channels=["vector"]),
        make_candidate("ev_b", channels=["vector"], rerank_score=0.9, text_hash="hash_ok"),
        make_candidate("ev_a", channels=["lexical"], rerank_score=0.5),
    ]
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex(original[:1]),
        vector_index=FakeVectorIndex(original[1:]),
        reranker=FakeReranker(reranked),
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": "ev_a", "support_label": "direct"},
                    {"evidence_id": "ev_b", "support_label": "indirect"},
                ]
            }
        ),
    )
    response = _execute(pipeline)
    ids = [item.evidence_id for item in response.evidence]
    assert "ev_injected" not in ids
    assert set(ids) == {"ev_a", "ev_b"}
    assert any(
        item.code == "MODEL_UNAUTHORIZED_ID" and item.stage == "rerank"
        for item in response.warnings
    )


def test_direct_indirect_counter_groups_and_counter_switch() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_a": make_record("ev_a"),
            "ev_b": make_record("ev_b"),
            "ev_c": make_record("ev_c"),
        }
    )
    lexical = [
        make_candidate("ev_a", channels=["lexical"]),
        make_candidate("ev_b", channels=["lexical"]),
        make_candidate("ev_c", channels=["lexical"]),
    ]
    labels = {
        "classifications": [
            {"evidence_id": "ev_a", "support_label": "direct"},
            {"evidence_id": "ev_b", "support_label": "indirect"},
            {"evidence_id": "ev_c", "support_label": "counter"},
        ]
    }
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(lexical),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(labels),
        overview_provider=FakeOverviewProvider(
            {"ev_a": "work_1", "ev_b": "work_2", "ev_c": "work_3"},
            {"ev_a": "vol_1", "ev_b": "vol_1", "ev_c": "vol_2"},
        ),
    )
    included = _execute(pipeline)
    assert [group.group_id for group in included.groups] == ["direct", "indirect", "counter"]
    assert included.groups[0].evidence_ids == ["ev_a"]
    assert included.groups[1].evidence_ids == ["ev_b"]
    assert included.groups[2].evidence_ids == ["ev_c"]
    assert all(group.summary is None for group in included.groups)
    assert [item.support_label for item in included.evidence] == [
        SupportLabel.DIRECT,
        SupportLabel.INDIRECT,
        SupportLabel.COUNTER,
    ]
    assert included.insufficiency is None

    hidden = _execute(pipeline, _request(include_counter_evidence=False))
    assert [group.group_id for group in hidden.groups] == ["direct", "indirect"]
    assert "ev_c" not in [item.evidence_id for item in hidden.evidence]
    assert all(item.support_label is not SupportLabel.COUNTER for item in hidden.evidence)


def test_evidence_service_exclusion_removes_ids_from_groups() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_ok": make_record("ev_ok"),
            "ev_draft": make_record("ev_draft", release_status="draft"),
        }
    )
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(
            [
                make_candidate("ev_ok", channels=["lexical"]),
                make_candidate("ev_draft", channels=["lexical"]),
            ]
        ),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": "ev_ok", "support_label": "direct"},
                    {"evidence_id": "ev_draft", "support_label": "direct"},
                ]
            }
        ),
        overview_provider=FakeOverviewProvider(
            {"ev_ok": "work_1", "ev_draft": "work_1"},
            {"ev_ok": "vol_1", "ev_draft": "vol_1"},
        ),
    )
    response = _execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_ok"]
    assert response.groups[0].evidence_ids == ["ev_ok"]
    assert "ev_draft" not in response.groups[0].evidence_ids
    assert any(item.code == "NOT_PUBLISHED" for item in response.warnings)


def test_missing_direct_evidence_returns_insufficiency_without_fabricated_summary() -> None:
    repository = FakeEvidenceRepository({"ev_b": make_record("ev_b")})
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex([make_candidate("ev_b", channels=["lexical"])]),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(
            {"classifications": [{"evidence_id": "ev_b", "support_label": "indirect"}]}
        ),
        overview_provider=FakeOverviewProvider({"ev_b": "work_1"}, {"ev_b": "vol_1"}),
    )
    response = _execute(pipeline)
    assert response.insufficiency is not None
    assert response.insufficiency.code == "INSUFFICIENT_SUPPORT"
    assert response.groups[0].group_id == "indirect"
    assert all(group.summary is None for group in response.groups)
    dumped = str(response.model_dump())
    assert "该观点得到原著明确支持" not in dumped


def test_scope_snapshot_uses_resolver_output_unmodified() -> None:
    original = make_scope()
    resolved = make_scope(edition_ids=["people_press_2009_cn"], volume_ids=["vol_1"])
    resolver = FakeScopeResolver(resolved)
    pipeline = _pipeline(scope_resolver=resolver)
    request = _request(scope=original)
    response = _execute(pipeline, request)
    assert resolver.calls == [original]
    assert response.scope_snapshot == resolved
    assert response.scope_snapshot != request.scope


def test_model_failures_degrade_deterministically_with_warnings() -> None:
    pipeline = _pipeline(
        embedding_provider=FakeEmbeddingProvider(RuntimeError("embed down")),
        reranker=FakeReranker(TimeoutError("rerank timeout")),
        language_model=FakeLanguageModel(TimeoutError("llm timeout")),
        lexical_index=FakeLexicalIndex([make_candidate("ev_a", channels=["lexical"])]),
        vector_index=FakeVectorIndex(
            [make_candidate("ev_b", channels=["vector"], text_hash="hash_ok")]
        ),
    )
    response = _execute(pipeline)
    codes = {item.code for item in response.warnings}
    assert "VECTOR_UNAVAILABLE" in codes
    assert "RERANKER_UNAVAILABLE" in codes
    assert "CLASSIFIER_UNAVAILABLE" in codes
    assert [item.evidence_id for item in response.evidence] == ["ev_a"]
    assert all(item.support_label is None for item in response.evidence)
    assert response.groups == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "INSUFFICIENT_SUPPORT"
    assert all("rerank" not in item.rank_reasons for item in response.evidence)


def test_search_response_matches_frozen_contract_and_overview_ignores_titles() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_a": make_record("ev_a", work_title="标题甲"),
            "ev_b": make_record("ev_b", work_title="标题乙"),
        }
    )
    overview = FakeOverviewProvider(
        {"ev_a": "work_shared", "ev_b": "work_shared"},
        {"ev_a": "vol_1", "ev_b": "vol_1"},
    )
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(
            [
                make_candidate("ev_a", channels=["lexical"]),
                make_candidate("ev_b", channels=["lexical"]),
            ]
        ),
        vector_index=FakeVectorIndex([]),
        overview_provider=overview,
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": "ev_a", "support_label": "direct"},
                    {"evidence_id": "ev_b", "support_label": "direct"},
                ]
            }
        ),
    )
    response = _execute(pipeline)
    round_trip = type(response).model_validate(response.model_dump())
    assert round_trip == response
    assert response.mode is SearchMode.CLAIM
    assert response.request_id == "req_claim_1"
    assert response.release.data_version == "data_test_v1"
    assert response.overview.evidence_count == 2
    assert response.overview.work_count == 1
    assert response.overview.volume_count == 1
    assert response.overview.work_count != len({item.work_title for item in response.evidence})
    assert response.classification_notice is None
    assert overview.calls == [("ev_a", "ev_b")]
    assert "verified_text" not in Candidate.model_fields
    for item in response.evidence:
        assert item.verified_text
        assert item.support_label is SupportLabel.DIRECT


def _domain_error(code: str) -> DomainError:
    return DomainError(
        code, f"{code} raised by test double.", retryable=code.endswith("UNAVAILABLE")
    )


def test_sqlite_domain_error_is_not_converted_to_warning() -> None:
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex(_domain_error("SQLITE_UNAVAILABLE")),
        vector_index=FakeVectorIndex(
            [make_candidate("ev_b", channels=["vector"], text_hash="hash_ok")]
        ),
    )
    try:
        _execute(pipeline)
    except DomainError as exc:
        assert exc.code == "SQLITE_UNAVAILABLE"
    else:
        raise AssertionError("SQLITE_UNAVAILABLE was swallowed")


def test_authority_repository_failure_is_sqlite_unavailable() -> None:
    class FailingRepository(FakeEvidenceRepository):
        async def get_by_ids(
            self, evidence_ids: Sequence[str]
        ) -> dict[str, AuthoritativeEvidenceRecord]:
            raise _domain_error("SQLITE_UNAVAILABLE")

    pipeline = _pipeline(repository=FailingRepository())
    try:
        _execute(pipeline)
    except DomainError as exc:
        assert exc.code == "SQLITE_UNAVAILABLE"
    else:
        raise AssertionError("repository SQLITE_UNAVAILABLE was swallowed")


def test_both_recall_channels_unavailable_raise_service_error() -> None:
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex(RuntimeError("lexical down")),
        embedding_provider=FakeEmbeddingProvider(RuntimeError("embed down")),
    )
    try:
        _execute(pipeline)
    except DomainError as exc:
        assert exc.code == "VECTOR_INDEX_UNAVAILABLE"
        assert exc.retryable is True
    else:
        raise AssertionError("dual channel failure returned a search response")


def test_single_channel_failure_degrades_when_the_other_can_serve() -> None:
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex([make_candidate("ev_a", channels=["lexical"])]),
        embedding_provider=FakeEmbeddingProvider(RuntimeError("embed down")),
        language_model=FakeLanguageModel(
            {"classifications": [{"evidence_id": "ev_a", "support_label": "direct"}]}
        ),
    )
    response = _execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_a"]
    assert any(item.code == "VECTOR_UNAVAILABLE" for item in response.warnings)
    assert response.insufficiency is None


def test_true_zero_hits_return_empty_result_not_service_error() -> None:
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex([]),
        vector_index=FakeVectorIndex([]),
    )
    response = _execute(pipeline)
    assert response.evidence == []
    assert response.groups == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "INSUFFICIENT_SUPPORT"


def test_release_snapshot_is_frozen_to_resolved_scope_before_recall() -> None:
    order: list[str] = []
    resolved = make_scope(edition_ids=["people_press_2009_cn"])
    original_release = FakeReleaseProvider()

    class OrderedRelease(FakeReleaseProvider):
        async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo:
            order.append("release")
            result = await original_release.snapshot_for(scope)
            return result

    class OrderedLexical(FakeLexicalIndex):
        async def search_lexical(
            self, query: str, scope: SearchScope, limit: int
        ) -> list[Candidate]:
            order.append("lexical")
            return await super().search_lexical(query, scope, limit)

    release = OrderedRelease()
    pipeline = _pipeline(
        scope_resolver=FakeScopeResolver(resolved),
        release_provider=release,
        lexical_index=OrderedLexical([make_candidate("ev_a", channels=["lexical"])]),
    )
    response = _execute(pipeline)
    assert order[0] == "release"
    assert "lexical" in order
    assert original_release.calls == [resolved]
    assert response.release.data_version == "data_test_v1"
    assert len(original_release.calls) == 1


def test_page_size_limits_surviving_evidence_and_keeps_groups_aligned() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_a": make_record("ev_a"),
            "ev_b": make_record("ev_b"),
            "ev_c": make_record("ev_c"),
        }
    )
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(
            [
                make_candidate("ev_a", channels=["lexical"]),
                make_candidate("ev_b", channels=["lexical"]),
                make_candidate("ev_c", channels=["lexical"]),
            ]
        ),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": "ev_a", "support_label": "direct"},
                    {"evidence_id": "ev_b", "support_label": "direct"},
                    {"evidence_id": "ev_c", "support_label": "indirect"},
                ]
            }
        ),
        overview_provider=FakeOverviewProvider(
            {"ev_a": "work_1", "ev_b": "work_2", "ev_c": "work_3"},
            {"ev_a": "vol_1", "ev_b": "vol_1", "ev_c": "vol_2"},
        ),
    )
    response = _execute(pipeline, _request(page_size=2))
    ids = [item.evidence_id for item in response.evidence]
    assert len(ids) == 2
    assert ids == ["ev_a", "ev_b"]
    grouped = [item for group in response.groups for item in group.evidence_ids]
    assert grouped == ids
    assert response.overview.evidence_count == 2
    assert "ev_c" not in grouped


def test_page_size_backfills_after_invalid_high_ranking_candidates() -> None:
    repository = FakeEvidenceRepository(
        {
            "ev_top": make_record("ev_top", release_status="draft"),
            "ev_keep": make_record("ev_keep"),
        }
    )
    pipeline = _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(
            [
                make_candidate("ev_top", channels=["lexical"]),
                make_candidate("ev_keep", channels=["lexical"]),
            ]
        ),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": "ev_top", "support_label": "direct"},
                    {"evidence_id": "ev_keep", "support_label": "direct"},
                ]
            }
        ),
        overview_provider=FakeOverviewProvider(
            {"ev_top": "work_1", "ev_keep": "work_2"},
            {"ev_top": "vol_1", "ev_keep": "vol_1"},
        ),
    )
    response = _execute(pipeline, _request(page_size=1))
    assert [item.evidence_id for item in response.evidence] == ["ev_keep"]
    assert response.groups[0].evidence_ids == ["ev_keep"]
    assert response.overview.evidence_count == 1


def test_classifier_receives_authoritative_verified_text_not_search_text() -> None:
    language_model = FakeLanguageModel(
        {"classifications": [{"evidence_id": "ev_a", "support_label": "direct"}]}
    )
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex([make_candidate("ev_a", channels=["lexical"])]),
        vector_index=FakeVectorIndex([]),
        language_model=language_model,
    )
    _execute(pipeline)
    task, payload = language_model.calls[0]
    assert task == "classify_claim_support"
    assert "evidence_ids" not in payload or payload.get("candidates")
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["evidence_id"] == "ev_a"
    assert candidates[0]["verified_text"] == "人人平等"
    assert "search_text" not in candidates[0]
    assert "LanceDB" not in str(payload)
    assert "search_text" not in str(payload)


def _assert_classifier_rejects(payload: Mapping[str, object]) -> None:
    pipeline = _pipeline(
        lexical_index=FakeLexicalIndex(
            [
                make_candidate("ev_a", channels=["lexical"]),
                make_candidate("ev_b", channels=["lexical"]),
            ]
        ),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(payload),
        repository=FakeEvidenceRepository(
            {"ev_a": make_record("ev_a"), "ev_b": make_record("ev_b")}
        ),
        overview_provider=FakeOverviewProvider(
            {"ev_a": "work_1", "ev_b": "work_1"},
            {"ev_a": "vol_1", "ev_b": "vol_1"},
        ),
    )
    response = _execute(pipeline)
    assert any(item.code == "CLASSIFIER_UNAVAILABLE" for item in response.warnings)
    assert all(item.support_label is None for item in response.evidence)
    assert response.groups == []
    assert {item.evidence_id for item in response.evidence} == {"ev_a", "ev_b"}
    assert "ev_ghost" not in {item.evidence_id for item in response.evidence}


def test_classifier_rejects_injected_ids() -> None:
    _assert_classifier_rejects(
        {
            "classifications": [
                {"evidence_id": "ev_a", "support_label": "direct"},
                {"evidence_id": "ev_b", "support_label": "direct"},
                {"evidence_id": "ev_ghost", "support_label": "direct"},
            ]
        }
    )


def test_classifier_rejects_missing_classifications() -> None:
    _assert_classifier_rejects(
        {"classifications": [{"evidence_id": "ev_a", "support_label": "direct"}]}
    )


def test_classifier_rejects_illegal_labels() -> None:
    _assert_classifier_rejects(
        {
            "classifications": [
                {"evidence_id": "ev_a", "support_label": "direct"},
                {"evidence_id": "ev_b", "support_label": "not_a_support_label"},
            ]
        }
    )


def test_classifier_rejects_malformed_payload() -> None:
    _assert_classifier_rejects({"classifications": "not-a-list"})


def _labeled_pipeline(labels: list[tuple[str, str]]) -> ClaimPipeline:
    ids = [evidence_id for evidence_id, _ in labels]
    repository = FakeEvidenceRepository(
        {evidence_id: make_record(evidence_id) for evidence_id in ids}
    )
    return _pipeline(
        repository=repository,
        lexical_index=FakeLexicalIndex(
            [make_candidate(evidence_id, channels=["lexical"]) for evidence_id in ids]
        ),
        vector_index=FakeVectorIndex([]),
        language_model=FakeLanguageModel(
            {
                "classifications": [
                    {"evidence_id": evidence_id, "support_label": support_label}
                    for evidence_id, support_label in labels
                ]
            }
        ),
        overview_provider=FakeOverviewProvider(
            {evidence_id: f"work_{evidence_id}" for evidence_id in ids},
            {evidence_id: "vol_1" for evidence_id in ids},
        ),
    )


def test_irrelevant_candidates_are_filtered_before_evidence() -> None:
    pipeline = _labeled_pipeline(
        [("ev_keep", "direct"), ("ev_noise", "irrelevant")],
    )
    response = _execute(pipeline)
    ids = [item.evidence_id for item in response.evidence]
    assert ids == ["ev_keep"]
    assert all(item.support_label is SupportLabel.DIRECT for item in response.evidence)
    grouped = [item for group in response.groups for item in group.evidence_ids]
    assert grouped == ["ev_keep"]
    assert "ev_noise" not in ids
    assert not any(item.code == "CLASSIFIER_UNAVAILABLE" for item in response.warnings)


def test_context_only_is_retained_and_grouped_separately() -> None:
    pipeline = _labeled_pipeline(
        [("ev_direct", "direct"), ("ev_context", "context_only")],
    )
    response = _execute(pipeline)
    assert [group.group_id for group in response.groups] == ["direct", "context_only"]
    assert response.groups[0].evidence_ids == ["ev_direct"]
    assert response.groups[1].evidence_ids == ["ev_context"]
    assert response.groups[1].group_type == "context"
    assert response.groups[1].label == "相关背景"
    assert [item.support_label for item in response.evidence] == [
        SupportLabel.DIRECT,
        SupportLabel.CONTEXT_ONLY,
    ]
    hidden = _execute(pipeline, _request(include_counter_evidence=False))
    assert [item.evidence_id for item in hidden.evidence] == ["ev_direct", "ev_context"]
    assert not any(item.code == "CLASSIFIER_UNAVAILABLE" for item in response.warnings)


def test_context_only_alone_returns_insufficient_support() -> None:
    pipeline = _labeled_pipeline([("ev_context", "context_only")])
    response = _execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_context"]
    assert response.evidence[0].support_label is SupportLabel.CONTEXT_ONLY
    assert [group.group_id for group in response.groups] == ["context_only"]
    assert response.insufficiency is not None
    assert response.insufficiency.code == "INSUFFICIENT_SUPPORT"
    assert response.insufficiency.details["direct_count"] == 0
    assert response.insufficiency.details["indirect_count"] == 0
    assert not any(item.code == "CLASSIFIER_UNAVAILABLE" for item in response.warnings)


def test_all_five_support_labels_are_accepted_without_degrading() -> None:
    pipeline = _labeled_pipeline(
        [
            ("ev_direct", "direct"),
            ("ev_indirect", "indirect"),
            ("ev_context", "context_only"),
            ("ev_counter", "counter"),
            ("ev_noise", "irrelevant"),
        ]
    )
    response = _execute(pipeline)
    assert not any(item.code == "CLASSIFIER_UNAVAILABLE" for item in response.warnings)
    assert [group.group_id for group in response.groups] == [
        "direct",
        "indirect",
        "context_only",
        "counter",
    ]
    assert [item.evidence_id for item in response.evidence] == [
        "ev_direct",
        "ev_indirect",
        "ev_context",
        "ev_counter",
    ]
    assert [item.support_label for item in response.evidence] == [
        SupportLabel.DIRECT,
        SupportLabel.INDIRECT,
        SupportLabel.CONTEXT_ONLY,
        SupportLabel.COUNTER,
    ]
    assert "ev_noise" not in {item.evidence_id for item in response.evidence}
    assert response.insufficiency is None
    grouped = [item for group in response.groups for item in group.evidence_ids]
    assert grouped == [item.evidence_id for item in response.evidence]
