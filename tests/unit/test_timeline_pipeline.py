import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from marx_engels.api.error_handlers import STATUS_BY_CODE
from marx_engels.contracts import (
    AuthorCode,
    Candidate,
    ContentType,
    DatePrecision,
    Evidence,
    ReleaseInfo,
    SearchMode,
    SearchOptions,
    SearchOverview,
    SearchRequest,
    SearchResponse,
    SearchScope,
    SupportLabel,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceHydrationResult, EvidenceService, ExactMatchQuery
from marx_engels.pipelines.timeline import TimelinePipeline
from marx_engels.pipelines.timeline_grouping import organize_timeline
from marx_engels.pipelines.timeline_ports import TimelineReleaseProvider
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord

CORPUS_ID = "synthetic_mecw_test"


class FakeScopeResolver:
    def __init__(self) -> None:
        self.calls: list[SearchScope] = []

    async def resolve(self, scope: SearchScope) -> SearchScope:
        self.calls.append(scope)
        return scope


class FakeLexicalIndex:
    def __init__(self, by_query: Mapping[str, list[Candidate]] | None = None) -> None:
        self.by_query = dict(by_query or {})
        self.fail = False
        self.error: BaseException | None = None
        self.calls = 0

    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del scope, limit
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.fail:
            raise RuntimeError("lexical unavailable")
        return list(self.by_query.get(query, []))


class FakeVectorIndex:
    def __init__(self, by_query: Mapping[str, list[Candidate]] | None = None) -> None:
        self.by_query = dict(by_query or {})
        self.fail = False
        self.error: BaseException | None = None
        self.calls = 0
        self.last_vector: Sequence[float] | None = None

    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del scope, limit
        self.calls += 1
        self.last_vector = vector
        if self.error is not None:
            raise self.error
        if self.fail:
            raise RuntimeError("vector unavailable")
        return list(self.by_query.get("default", []))


class FakeEmbedding:
    def __init__(self) -> None:
        self.model_version = "deterministic-4d-v1"
        self.dimension = 4
        self.fail = False

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [[0.1, 0.9, 0.0, 0.0] for _ in texts]


class FakeReranker:
    def __init__(self) -> None:
        self.model_version = "test-rerank"
        self.fail = False
        self.calls = 0
        self.irrelevant_ids: set[str] = set()
        self.extra_candidates: list[Candidate] = []
        self.duplicate_first: bool = False

    async def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        del query
        self.calls += 1
        if self.fail:
            raise RuntimeError("reranker unavailable")
        reranked: list[Candidate] = []
        if self.duplicate_first and candidates:
            reranked.append(candidates[0])
        for candidate in candidates:
            if candidate.evidence_id in self.irrelevant_ids:
                reranked.append(
                    candidate.model_copy(update={"support_label": SupportLabel.IRRELEVANT})
                )
            else:
                reranked.append(candidate)
        reranked.extend(self.extra_candidates)
        return reranked


class FakeSummary:
    def __init__(self) -> None:
        self.fail = False
        self.calls: list[str] = []

    async def summarize_group(
        self, query: str, group_id: str, evidence: Sequence[Evidence]
    ) -> str | None:
        del query, evidence
        self.calls.append(group_id)
        if self.fail:
            raise RuntimeError("llm unavailable")
        return f"摘要:{group_id}"


class FakeReleaseProvider:
    def __init__(self) -> None:
        self.calls: list[SearchScope] = []

    def release_for(self, scope: SearchScope) -> ReleaseInfo:
        self.calls.append(scope)
        return ReleaseInfo(
            data_version="data_synthetic_v1",
            index_version="idx_synthetic_v1",
            embedding_model="deterministic-4d-v1",
        )


@dataclass
class FakeOverviewProvider:
    work_ids: dict[str, str]
    volume_ids: dict[str, str]

    def overview(self, evidence: Sequence[Evidence]) -> SearchOverview:
        return SearchOverview(
            evidence_count=len(evidence),
            work_count=len({self.work_ids[item.evidence_id] for item in evidence}),
            volume_count=len({self.volume_ids[item.evidence_id] for item in evidence}),
        )


class FakeEvidenceRepository:
    def __init__(self, records: Mapping[str, AuthoritativeEvidenceRecord]) -> None:
        self.records = dict(records)
        self.error: BaseException | None = None
        self.calls: list[tuple[str, ...]] = []

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        self.calls.append(tuple(evidence_ids))
        if self.error is not None:
            raise self.error
        return {
            evidence_id: self.records[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.records
        }


class SpyEvidenceService(EvidenceService):
    def __init__(self, repository: FakeEvidenceRepository) -> None:
        super().__init__(repository)
        self.last_candidate_ids: list[str] = []
        self.last_allowed: Iterable[str] | None = None

    async def hydrate(
        self,
        candidates: Sequence[Candidate],
        scope: SearchScope,
        *,
        exact_query: ExactMatchQuery | None = None,
        allowed_evidence_ids: Iterable[str] | None = None,
    ) -> EvidenceHydrationResult:
        self.last_candidate_ids = [candidate.evidence_id for candidate in candidates]
        self.last_allowed = allowed_evidence_ids
        return await super().hydrate(
            candidates,
            scope,
            exact_query=exact_query,
            allowed_evidence_ids=allowed_evidence_ids,
        )


def make_record(evidence_id: str, **overrides: object) -> AuthoritativeEvidenceRecord:
    record = AuthoritativeEvidenceRecord(
        evidence_id=evidence_id,
        verified_text="【合成数据，非原典】公共讨论材料。",
        text_hash=f"hash_{evidence_id}",
        verification_status="verified",
        release_status="published",
        content_type=ContentType.MAIN_TEXT.value,
        author_code=AuthorCode.MARX.value,
        author="马克思",
        work_title="合成著作",
        corpus_id=CORPUS_ID,
        corpus_name="合成测试语料",
        edition_id="synthetic_edition_v1",
        edition_label="合成测试版",
        volume_id="syn_v01",
        volume_no=1,
        work_id="syn_work_early",
        work_date_start="1845",
        work_date_end="1845",
        date_precision=DatePrecision.YEAR.value,
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


def make_candidate(evidence_id: str, channel: str, rank: int = 1) -> Candidate:
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "channels": [channel],
        "text_hash": f"hash_{evidence_id}",
        "rank_reasons": [channel],
    }
    if channel == "lexical":
        payload["lexical_rank"] = rank
        payload["lexical_score"] = 1.0 / rank
    else:
        payload["vector_rank"] = rank
        payload["vector_score"] = 1.0 / rank
    return Candidate.model_validate(payload)


def timeline_request(**overrides: object) -> SearchRequest:
    payload: dict[str, object] = {
        "query": "公共讨论如何变化",
        "mode": SearchMode.TIMELINE,
        "scope": {"corpus_ids": [CORPUS_ID]},
    }
    payload.update(overrides)
    return SearchRequest.model_validate(payload)


def build_pipeline(
    records: Mapping[str, AuthoritativeEvidenceRecord],
    lexical: Mapping[str, list[Candidate]],
    vector: Mapping[str, list[Candidate]],
    *,
    work_ids: dict[str, str] | None = None,
    volume_ids: dict[str, str] | None = None,
    reranker: FakeReranker | None = None,
    summary: FakeSummary | None = None,
    repository: FakeEvidenceRepository | None = None,
    release_provider: TimelineReleaseProvider | None = None,
) -> tuple[TimelinePipeline, FakeLexicalIndex, FakeVectorIndex, FakeEmbedding, FakeScopeResolver]:
    identities_work = work_ids or {
        evidence_id: record.work_id for evidence_id, record in records.items()
    }
    identities_volume = volume_ids or {
        evidence_id: record.volume_id for evidence_id, record in records.items()
    }
    lexical_index = FakeLexicalIndex(lexical)
    vector_index = FakeVectorIndex(vector)
    embedding = FakeEmbedding()
    resolver = FakeScopeResolver()
    resolved_repository = repository or FakeEvidenceRepository(records)
    service = SpyEvidenceService(resolved_repository)
    resolved_release = release_provider or FakeReleaseProvider()
    pipeline = TimelinePipeline(
        scope_resolver=resolver,
        lexical_index=lexical_index,
        vector_index=vector_index,
        embedding_provider=embedding,
        evidence_service=service,
        release_provider=resolved_release,
        overview_provider=FakeOverviewProvider(identities_work, identities_volume),
        reranker=reranker,
        summary_provider=summary,
        lexical_top_k=20,
        vector_top_k=20,
        fusion_top_k=20,
        rerank_top_k=20,
        final_top_k=20,
        rrf_k=60,
    )
    return pipeline, lexical_index, vector_index, embedding, resolver


def execute(pipeline: TimelinePipeline, request: SearchRequest | None = None) -> SearchResponse:
    return asyncio.run(pipeline.execute(request or timeline_request(), "req_timeline"))


def dated_records() -> dict[str, AuthoritativeEvidenceRecord]:
    return {
        "ev_year": make_record("ev_year", work_id="work_year"),
        "ev_range": make_record(
            "ev_range",
            work_id="work_range",
            work_date_start="1852-01",
            work_date_end="1852-12",
            date_precision=DatePrecision.RANGE.value,
        ),
        "ev_approx": make_record(
            "ev_approx",
            work_id="work_approx",
            volume_id="syn_v02",
            volume_no=2,
            work_date_start="1878",
            work_date_end=None,
            date_precision=DatePrecision.APPROXIMATE.value,
        ),
        "ev_disputed": make_record(
            "ev_disputed",
            work_id="work_disputed",
            work_date_start=None,
            work_date_end=None,
            date_precision=DatePrecision.DISPUTED.value,
        ),
        "ev_unknown": make_record(
            "ev_unknown",
            work_id="work_unknown",
            volume_id="syn_v02",
            volume_no=2,
            work_date_start=None,
            work_date_end=None,
            date_precision=DatePrecision.UNKNOWN.value,
        ),
        "ev_day": make_record(
            "ev_day",
            work_id="work_day",
            work_date_start="1848-03-15",
            work_date_end="1848-03-15",
            date_precision=DatePrecision.DAY.value,
        ),
    }


def test_rejects_non_timeline_mode() -> None:
    pipeline, *_ = build_pipeline({}, {}, {})
    try:
        execute(
            pipeline,
            timeline_request(mode=SearchMode.CLAIM, query="这是一个完整观点表述"),
        )
    except DomainError as exc:
        assert exc.code == "INVALID_REQUEST"
        assert STATUS_BY_CODE[exc.code] == 400
    else:
        raise AssertionError("non-timeline mode was accepted")


def test_organizes_year_range_approximate_disputed_and_unknown() -> None:
    records = dated_records()
    ids = ["ev_unknown", "ev_approx", "ev_disputed", "ev_year", "ev_range", "ev_day"]
    lexical = {
        "公共讨论如何变化": [
            make_candidate(evidence_id, "lexical", rank)
            for rank, evidence_id in enumerate(ids, start=1)
        ]
    }
    pipeline, resolver, *_rest = _unpack(records, lexical)
    response = execute(pipeline)
    assert resolver.calls and resolver.calls[0].corpus_ids == [CORPUS_ID]
    assert [item.evidence_id for item in response.evidence] == [
        "ev_year",
        "ev_day",
        "ev_range",
        "ev_approx",
        "ev_disputed",
        "ev_unknown",
    ]
    assert [group.group_id for group in response.groups] == [
        "decade_1840",
        "decade_1850",
        "decade_1870",
        "disputed",
        "unknown",
    ]
    decade_1840, decade_1850, decade_1870, disputed, unknown = response.groups
    assert decade_1840.date_start == "1840"
    assert decade_1840.date_end == "1849"
    assert decade_1840.date_precision is DatePrecision.YEAR
    assert decade_1850.date_precision is DatePrecision.YEAR
    assert decade_1870.label == "约1870年代"
    assert decade_1870.date_precision is DatePrecision.APPROXIMATE
    assert disputed.date_start is None and disputed.date_end is None
    assert disputed.date_precision is DatePrecision.DISPUTED
    assert unknown.date_start is None and unknown.date_end is None
    assert unknown.date_precision is DatePrecision.UNKNOWN
    assert response.mode is SearchMode.TIMELINE
    assert response.release.data_version == "data_synthetic_v1"
    assert response.insufficiency is None


def _unpack(
    records: Mapping[str, AuthoritativeEvidenceRecord],
    lexical: Mapping[str, list[Candidate]],
    vector: Mapping[str, list[Candidate]] | None = None,
    **kwargs: object,
) -> tuple[TimelinePipeline, FakeScopeResolver]:
    pipeline, _lexical, _vector, _embedding, resolver = build_pipeline(
        records, lexical, vector or {"default": []}, **kwargs  # type: ignore[arg-type]
    )
    return pipeline, resolver


def test_disputed_and_unknown_are_not_given_invented_years() -> None:
    disputed = make_record(
        "ev_disputed",
        work_date_start="1845",
        work_date_end="1845",
        date_precision=DatePrecision.DISPUTED.value,
    )
    unknown = make_record(
        "ev_unknown",
        work_date_start="1878",
        work_date_end="1878",
        date_precision=DatePrecision.UNKNOWN.value,
    )
    groups, ordered = organize_timeline(
        [
            _evidence_from_record(unknown),
            _evidence_from_record(disputed),
        ]
    )
    assert [item.evidence_id for item in ordered] == ["ev_disputed", "ev_unknown"]
    assert groups[0].group_id == "disputed"
    assert groups[0].date_start is None
    assert groups[1].group_id == "unknown"
    assert groups[1].date_start is None


def _evidence_from_record(record: AuthoritativeEvidenceRecord) -> Evidence:
    repository = FakeEvidenceRepository({record.evidence_id: record})
    result = asyncio.run(
        EvidenceService(repository).hydrate(
            [make_candidate(record.evidence_id, "lexical")],
            SearchScope(corpus_ids=[CORPUS_ID]),
        )
    )
    return result.evidence[0]


def test_duplicate_evidence_ids_are_removed() -> None:
    records = {
        "ev_year": make_record("ev_year"),
        "ev_same": make_record("ev_same", work_id="work_year"),
    }
    query = "公共讨论如何变化"
    lexical = {
        query: [
            make_candidate("ev_year", "lexical", 1),
            make_candidate("ev_same", "lexical", 2),
        ]
    }
    vector = {"default": [make_candidate("ev_year", "vector", 1)]}
    pipeline, *_ = build_pipeline(records, lexical, vector)
    response = execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_same", "ev_year"]
    assert response.groups[0].evidence_ids == ["ev_same", "ev_year"]


def test_same_work_passages_share_a_group_without_duplicate_ids() -> None:
    records = {
        "ev_a": make_record("ev_a", work_id="work_year"),
        "ev_b": make_record("ev_b", work_id="work_year"),
    }
    lexical = {
        "公共讨论如何变化": [
            make_candidate("ev_b", "lexical", 1),
            make_candidate("ev_a", "lexical", 2),
        ]
    }
    pipeline, *_ = build_pipeline(records, lexical, {})
    response = execute(pipeline)
    assert response.groups[0].evidence_ids == ["ev_a", "ev_b"]
    assert len(response.evidence) == 2


def test_scope_and_release_gates_drop_decoy_and_unpublished() -> None:
    records = {
        "ev_year": make_record("ev_year"),
        "ev_decoy": make_record("ev_decoy", corpus_id="synthetic_scope_decoy", work_id="decoy"),
        "ev_draft": make_record("ev_draft", release_status="draft", work_id="draft"),
        "ev_pending": make_record(
            "ev_pending", verification_status="pending_review", work_id="pending"
        ),
    }
    lexical = {
        "公共讨论如何变化": [
            make_candidate("ev_year", "lexical", 1),
            make_candidate("ev_decoy", "lexical", 2),
            make_candidate("ev_draft", "lexical", 3),
            make_candidate("ev_pending", "lexical", 4),
        ]
    }
    pipeline, *_ = build_pipeline(records, lexical, {})
    response = execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_year"]


def test_lexical_only_degradation_returns_warning() -> None:
    records = dated_records()
    lexical = {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]}
    pipeline, lexical_index, vector_index, embedding, _resolver = build_pipeline(
        records, lexical, {"default": [make_candidate("ev_range", "vector")]}
    )
    vector_index.fail = True
    response = execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_year"]
    assert [item.code for item in response.warnings] == [
        "VECTOR_INDEX_UNAVAILABLE",
        "RERANKER_UNAVAILABLE",
    ]
    assert lexical_index.calls == 1
    assert embedding.fail is False
    assert response.insufficiency is None


def test_lexical_channel_failure_degrades_to_vector() -> None:
    records = dated_records()
    pipeline, lexical_index, vector_index, _embedding, _resolver = build_pipeline(
        records,
        {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]},
        {"default": [make_candidate("ev_range", "vector")]},
    )
    lexical_index.fail = True
    response = execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_range"]
    assert [item.code for item in response.warnings] == [
        "LEXICAL_INDEX_UNAVAILABLE",
        "RERANKER_UNAVAILABLE",
    ]
    assert vector_index.calls == 1
    assert response.insufficiency is None


def test_empty_result_sets_insufficiency() -> None:
    pipeline, *_ = build_pipeline({}, {"公共讨论如何变化": []}, {"default": []})
    response = execute(pipeline)
    assert response.evidence == []
    assert response.groups == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_TIMELINE_EVIDENCE"
    assert response.overview.evidence_count == 0


def test_both_channels_down_raises_mapped_503() -> None:
    records = {"ev_year": make_record("ev_year")}
    pipeline, lexical_index, vector_index, _embedding, _resolver = build_pipeline(
        records, {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]}, {}
    )
    lexical_index.fail = True
    vector_index.fail = True
    try:
        execute(pipeline)
    except DomainError as exc:
        assert exc.code == "VECTOR_INDEX_UNAVAILABLE"
        assert STATUS_BY_CODE[exc.code] == 503
        assert exc.retryable is True
    else:
        raise AssertionError("dual-channel failure returned an HTTP 200-style response")


def test_partial_keeps_evidence_and_warnings() -> None:
    records = dated_records()
    lexical = {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]}
    reranker = FakeReranker()
    reranker.fail = True
    pipeline, _lexical, vector_index, _embedding, _resolver = build_pipeline(
        records, lexical, {}, reranker=reranker
    )
    vector_index.fail = True
    response = execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_year"]
    assert {item.code for item in response.warnings} == {
        "VECTOR_INDEX_UNAVAILABLE",
        "RERANKER_UNAVAILABLE",
    }


def test_overview_uses_injected_identities_not_titles() -> None:
    records = {
        "ev_a": make_record("ev_a", work_id="work_a", volume_id="vol_a", work_title="同名"),
        "ev_b": make_record("ev_b", work_id="work_b", volume_id="vol_b", work_title="同名"),
    }
    lexical = {
        "公共讨论如何变化": [
            make_candidate("ev_a", "lexical", 1),
            make_candidate("ev_b", "lexical", 2),
        ]
    }
    pipeline, *_ = build_pipeline(records, lexical, {})
    response = execute(pipeline)
    assert response.overview.work_count == 2
    assert response.overview.volume_count == 2
    assert response.overview.evidence_count == 2


def test_summaries_default_off_without_provider_and_can_be_disabled() -> None:
    records = {"ev_year": make_record("ev_year")}
    lexical = {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]}
    pipeline, *_ = build_pipeline(records, lexical, {})
    response = execute(pipeline)
    assert response.groups[0].summary is None

    summary = FakeSummary()
    pipeline_with_summary, *_ = build_pipeline(records, lexical, {}, summary=summary)
    disabled = execute(
        pipeline_with_summary,
        timeline_request(options=SearchOptions(include_generated_summaries=False)),
    )
    assert summary.calls == []
    assert disabled.groups[0].summary is None


def test_search_response_contract_fields() -> None:
    records = {"ev_year": make_record("ev_year")}
    lexical = {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]}
    pipeline, *_ = build_pipeline(records, lexical, {})
    response = execute(pipeline)
    payload = response.model_dump()
    assert payload["mode"] == "timeline"
    assert payload["request_id"] == "req_timeline"
    assert payload["scope_snapshot"]["corpus_ids"] == [CORPUS_ID]
    assert payload["evidence"][0]["verified_text"].startswith("【合成数据，非原典】")
    assert "search_text" not in payload["evidence"][0]


def test_known_date_missing_start_does_not_invent_a_year() -> None:
    record = make_record(
        "ev_blank",
        work_date_start=None,
        work_date_end=None,
        date_precision=DatePrecision.YEAR.value,
    )
    groups, ordered = organize_timeline([_evidence_from_record(record)])
    assert ordered[0].evidence_id == "ev_blank"
    assert groups[0].group_id == "unknown"
    assert groups[0].date_start is None


def test_sqlite_unavailable_is_not_converted_to_empty_success() -> None:
    records = {"ev_year": make_record("ev_year")}
    repository = FakeEvidenceRepository(records)
    repository.error = DomainError(
        "SQLITE_UNAVAILABLE",
        "authoritative store is down",
        retryable=True,
    )
    pipeline, *_ = build_pipeline(
        records,
        {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]},
        {},
        repository=repository,
    )
    try:
        execute(pipeline)
    except DomainError as exc:
        assert exc.code == "SQLITE_UNAVAILABLE"
        assert STATUS_BY_CODE[exc.code] == 503
    else:
        raise AssertionError("SQLite failure returned a successful empty response")


def test_sqlite_domain_error_from_lexical_channel_is_reraised() -> None:
    records = {"ev_year": make_record("ev_year")}
    pipeline, lexical_index, vector_index, _embedding, _resolver = build_pipeline(
        records,
        {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]},
        {"default": [make_candidate("ev_year", "vector")]},
    )
    lexical_index.error = DomainError("SQLITE_UNAVAILABLE", "fts sqlite down", retryable=True)
    try:
        execute(pipeline)
    except DomainError as exc:
        assert exc.code == "SQLITE_UNAVAILABLE"
        assert vector_index.calls == 1
    else:
        raise AssertionError("authoritative lexical DomainError was swallowed")


def test_zero_hits_remain_a_normal_empty_response() -> None:
    pipeline, *_ = build_pipeline({}, {"公共讨论如何变化": []}, {"default": []})
    response = execute(pipeline)
    assert response.evidence == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_TIMELINE_EVIDENCE"
    assert all(item.code != "VECTOR_INDEX_UNAVAILABLE" for item in response.warnings)


def test_reranker_cannot_inject_unrecalled_evidence() -> None:
    records = {
        "ev_year": make_record("ev_year"),
        "ev_injected": make_record("ev_injected", work_id="work_injected"),
    }
    reranker = FakeReranker()
    reranker.duplicate_first = True
    reranker.extra_candidates = [make_candidate("ev_injected", "vector")]
    pipeline, *_ = build_pipeline(
        records,
        {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]},
        {},
        reranker=reranker,
    )
    response = execute(pipeline)
    service = pipeline._evidence_service
    assert isinstance(service, SpyEvidenceService)
    assert service.last_candidate_ids == ["ev_year"]
    assert service.last_allowed is not None
    assert set(service.last_allowed) == {"ev_year"}
    assert [item.evidence_id for item in response.evidence] == ["ev_year"]


def test_invalid_high_rank_candidates_do_not_crowd_out_valid_evidence() -> None:
    records = {
        "ev_draft": make_record("ev_draft", release_status="draft", work_id="draft"),
        "ev_valid": make_record(
            "ev_valid",
            work_id="work_valid",
            work_date_start="1852",
            work_date_end="1852",
        ),
    }
    lexical = {
        "公共讨论如何变化": [
            make_candidate("ev_draft", "lexical", 1),
            make_candidate("ev_valid", "lexical", 2),
        ]
    }
    pipeline, *_ = build_pipeline(records, lexical, {})
    response = execute(pipeline, timeline_request(page_size=1))
    service = pipeline._evidence_service
    assert isinstance(service, SpyEvidenceService)
    assert service.last_candidate_ids == ["ev_draft", "ev_valid"]
    assert [item.evidence_id for item in response.evidence] == ["ev_valid"]


def test_release_is_frozen_from_request_scope_before_recall() -> None:
    records = {"ev_year": make_record("ev_year")}

    class ShiftingRelease:
        def __init__(self) -> None:
            self.calls: list[SearchScope] = []

        def release_for(self, scope: SearchScope) -> ReleaseInfo:
            self.calls.append(scope)
            return ReleaseInfo(
                data_version=f"data_{len(self.calls)}",
                index_version="idx_synthetic_v1",
                embedding_model="deterministic-4d-v1",
            )

    provider = ShiftingRelease()
    pipeline, *_ = build_pipeline(
        records,
        {"公共讨论如何变化": [make_candidate("ev_year", "lexical")]},
        {},
        release_provider=provider,
    )
    response = execute(pipeline)
    assert provider.calls == [SearchScope(corpus_ids=[CORPUS_ID])]
    assert response.release.data_version == "data_1"
    assert len(provider.calls) == 1


def test_invalid_request_code_is_mapped_to_http_400() -> None:
    assert STATUS_BY_CODE["INVALID_REQUEST"] == 400
    assert STATUS_BY_CODE["VECTOR_INDEX_UNAVAILABLE"] == 503
    assert STATUS_BY_CODE["SQLITE_UNAVAILABLE"] == 503
    assert "INVALID_MODE" not in STATUS_BY_CODE
    assert "RETRIEVAL_UNAVAILABLE" not in STATUS_BY_CODE
