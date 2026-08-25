from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from marx_engels.contracts import (
    AuthorCode,
    Candidate,
    ContentType,
    ReleaseInfo,
    SearchMode,
    SearchOptions,
    SearchRequest,
    SearchResponse,
    SearchScope,
    SupportLabel,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceHydrationResult, EvidenceService, ExactMatchQuery
from marx_engels.pipelines.thematic import (
    CountOverviewProvider,
    FixedReleaseProvider,
    ThematicPipeline,
)
from marx_engels.pipelines.thematic_grouping import (
    assign_exclusively,
    cited_evidence_ids_are_valid,
    fallback_theme_label,
)
from marx_engels.pipelines.thematic_types import (
    CLASSIFICATION_NOTICE,
    ClusterAssignment,
    ThematicPipelineConfig,
    ThemeLabel,
)
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord

CORPUS_ID = "synthetic_thematic_corpus"


class FakeEvidenceRepository:
    def __init__(self, records: Mapping[str, AuthoritativeEvidenceRecord]) -> None:
        self.records = dict(records)

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        return {
            evidence_id: self.records[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.records
        }


class RecordingEvidenceService(EvidenceService):
    def __init__(
        self,
        repository: FakeEvidenceRepository,
        events: list[str] | None = None,
    ) -> None:
        super().__init__(repository)
        self.hydrate_calls = 0
        self.last_allowed: frozenset[str] | None = None
        self.last_candidate_ids: tuple[str, ...] = ()
        self.events = events

    async def hydrate(
        self,
        candidates: Sequence[Candidate],
        scope: SearchScope,
        *,
        exact_query: ExactMatchQuery | None = None,
        allowed_evidence_ids: Iterable[str] | None = None,
    ) -> EvidenceHydrationResult:
        self.hydrate_calls += 1
        self.last_candidate_ids = tuple(candidate.evidence_id for candidate in candidates)
        self.last_allowed = (
            None if allowed_evidence_ids is None else frozenset(allowed_evidence_ids)
        )
        if self.events is not None:
            self.events.append("hydrate")
        return await super().hydrate(
            candidates,
            scope,
            exact_query=exact_query,
            allowed_evidence_ids=allowed_evidence_ids,
        )


class FakeScopeResolver:
    async def resolve(self, scope: SearchScope) -> SearchScope:
        return scope


class FakeLexicalIndex:
    def __init__(
        self,
        candidates: Sequence[Candidate] | Exception = (),
        events: list[str] | None = None,
    ) -> None:
        self.candidates = candidates
        self.events = events

    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del query, scope, limit
        if self.events is not None:
            self.events.append("lexical")
        if isinstance(self.candidates, Exception):
            raise self.candidates
        return list(self.candidates)


class FakeVectorIndex:
    def __init__(
        self,
        candidates: Sequence[Candidate] | Exception = (),
        events: list[str] | None = None,
    ) -> None:
        self.candidates = candidates
        self.events = events

    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del vector, scope, limit
        if self.events is not None:
            self.events.append("vector")
        if isinstance(self.candidates, Exception):
            raise self.candidates
        return list(self.candidates)


class FakeEmbedding:
    model_version = "fake-embed-v1"
    dimension = 4

    def __init__(
        self,
        query_vector: Sequence[float] | Exception = (1.0, 0.0, 0.0, 0.0),
        *,
        document_error: Exception | None = None,
    ) -> None:
        self.query_vector = query_vector
        self.document_error = document_error
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 1:
            if isinstance(self.query_vector, Exception):
                raise self.query_vector
            return [list(self.query_vector)]
        if self.document_error is not None:
            raise self.document_error
        return [[float(index + 1), 0.0, 0.0, 0.0] for index, _text in enumerate(texts)]


class ScriptedClusterer:
    def __init__(self, assignments: Sequence[ClusterAssignment] | Exception) -> None:
        self.assignments = assignments
        self.calls = 0
        self.last_ids: tuple[str, ...] = ()

    async def cluster(
        self,
        evidence_ids: Sequence[str],
        vectors: Mapping[str, Sequence[float]],
    ) -> Sequence[ClusterAssignment]:
        self.calls += 1
        self.last_ids = tuple(evidence_ids)
        del vectors
        if isinstance(self.assignments, Exception):
            raise self.assignments
        return list(self.assignments)


class ScriptedLabeler:
    def __init__(self, labels: Mapping[str, ThemeLabel] | Exception) -> None:
        self.labels = labels

    async def label(
        self, *, cluster_id: str, query: str, evidence_ids: Sequence[str]
    ) -> ThemeLabel:
        del query, evidence_ids
        if isinstance(self.labels, Exception):
            raise self.labels
        return self.labels[cluster_id]


class ScriptedRelevanceStage:
    def __init__(
        self,
        *,
        labels: Mapping[str, SupportLabel | None] | None = None,
        scores: Mapping[str, float | None] | None = None,
        extras: Sequence[Candidate] = (),
        error: Exception | None = None,
        passthrough: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.labels = dict(labels or {})
        self.scores = dict(scores or {})
        self.extras = list(extras)
        self.error = error
        self.passthrough = passthrough
        self.events = events
        self.calls = 0
        self.last_query: str | None = None
        self.last_ids: tuple[str, ...] = ()

    async def score(
        self, query: str, candidates: Sequence[Candidate]
    ) -> list[Candidate]:
        self.calls += 1
        self.last_query = query
        self.last_ids = tuple(candidate.evidence_id for candidate in candidates)
        if self.events is not None:
            self.events.append("relevance")
        if self.error is not None:
            raise self.error
        if self.passthrough:
            return list(candidates)
        judged: list[Candidate] = []
        for candidate in candidates:
            judged.append(
                candidate.model_copy(
                    update={
                        "support_label": self.labels.get(
                            candidate.evidence_id, SupportLabel.DIRECT
                        ),
                        "rerank_score": self.scores.get(candidate.evidence_id, 0.9),
                    }
                )
            )
        judged.extend(self.extras)
        return judged


class RecordingReleaseProvider:
    def __init__(
        self,
        release: ReleaseInfo,
        events: list[str] | None = None,
    ) -> None:
        self.release = release
        self.events = events
        self.calls = 0
        self.scopes: list[SearchScope] = []

    async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo:
        self.calls += 1
        self.scopes.append(scope)
        if self.events is not None:
            self.events.append("snapshot_for")
        return self.release


class TrackingScopeResolver:
    def __init__(self, events: list[str], resolved: SearchScope) -> None:
        self.events = events
        self.resolved = resolved

    async def resolve(self, scope: SearchScope) -> SearchScope:
        del scope
        self.events.append("resolve")
        return self.resolved


SYNTHETIC_RELEASE = ReleaseInfo(
    data_version="data_synthetic_v1",
    index_version="idx_synthetic_v1",
    embedding_model="fake-embed-v1",
)


def make_record(evidence_id: str, text: str, **overrides: object) -> AuthoritativeEvidenceRecord:
    record = AuthoritativeEvidenceRecord(
        evidence_id=evidence_id,
        verified_text=text,
        text_hash=f"hash_{evidence_id}",
        verification_status="verified",
        release_status="published",
        content_type=ContentType.MAIN_TEXT.value,
        author_code=AuthorCode.MARX.value,
        author="synthetic-author",
        work_title=f"synthetic-work-{evidence_id}",
        corpus_id=CORPUS_ID,
        corpus_name="synthetic corpus",
        edition_id="synthetic_edition",
        edition_label="synthetic edition",
        volume_id="synthetic_vol_1",
        volume_no=1,
        work_id=f"work_{evidence_id}",
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
        pdf_pages=(1,),
        page_mapping_statuses=("verified",),
        prev_evidence_id=None,
        next_evidence_id=None,
        prev_is_released=False,
        next_is_released=False,
    )
    return replace(record, **overrides)  # type: ignore[arg-type]


def make_candidate(evidence_id: str, channel: str = "lexical", **overrides: object) -> Candidate:
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "channels": [channel],
        "text_hash": f"hash_{evidence_id}",
    }
    payload.update(overrides)
    return Candidate.model_validate(payload)


def make_request(**overrides: object) -> SearchRequest:
    payload: dict[str, object] = {
        "query": "SYNTHETIC_THEMATIC_QUERY",
        "mode": SearchMode.THEMATIC,
        "scope": {"corpus_ids": [CORPUS_ID]},
    }
    payload.update(overrides)
    return SearchRequest.model_validate(payload)


def build_pipeline(
    *,
    records: Mapping[str, AuthoritativeEvidenceRecord],
    lexical: Sequence[Candidate] | Exception = (),
    vector: Sequence[Candidate] | Exception = (),
    assignments: Sequence[ClusterAssignment] | Exception = (),
    labels: Mapping[str, ThemeLabel] | Exception | None = None,
    embedding: FakeEmbedding | None = None,
    evidence_service: EvidenceService | None = None,
    clusterer: ScriptedClusterer | None = None,
    relevance_stage: ScriptedRelevanceStage | None = None,
    release_provider: FixedReleaseProvider | RecordingReleaseProvider | None = None,
    scope_resolver: FakeScopeResolver | TrackingScopeResolver | None = None,
    config: ThematicPipelineConfig | None = None,
) -> ThematicPipeline:
    repository = FakeEvidenceRepository(records)
    return ThematicPipeline(
        scope_resolver=scope_resolver or FakeScopeResolver(),
        lexical_index=FakeLexicalIndex(lexical),
        vector_index=FakeVectorIndex(vector),
        embedding=embedding or FakeEmbedding(),
        evidence_service=evidence_service or EvidenceService(repository),
        relevance_stage=relevance_stage or ScriptedRelevanceStage(),
        clusterer=clusterer or ScriptedClusterer(assignments),
        labeler=None if labels is None else ScriptedLabeler(labels),
        release_provider=release_provider
        or FixedReleaseProvider(SYNTHETIC_RELEASE),
        overview_provider=CountOverviewProvider(repository),
        config=config,
    )


def execute(pipeline: ThematicPipeline, request: SearchRequest | None = None) -> SearchResponse:
    return asyncio.run(pipeline.execute(request or make_request(), "req_thematic_test"))


def grouped_ids(response: SearchResponse) -> list[str]:
    return [evidence_id for group in response.groups for evidence_id in group.evidence_ids]


def test_assign_exclusively_drops_duplicates_and_unauthorized_ids() -> None:
    grouping = assign_exclusively(
        [
            ClusterAssignment("theme_a", ("ev_a", "ev_b", "ev_injected")),
            ClusterAssignment("theme_b", ("ev_b", "ev_c")),
        ],
        ["ev_a", "ev_b", "ev_c"],
    )
    assert grouping.themes[0].evidence_ids == ("ev_a", "ev_b")
    assert grouping.themes[1].evidence_ids == ("ev_c",)
    assert grouping.other_related_ids == ()


def test_fallback_theme_labels_are_deterministic() -> None:
    assert fallback_theme_label(1) == "主题 1"
    assert fallback_theme_label(2) == "主题 2"


def test_pipeline_rejects_non_thematic_mode() -> None:
    pipeline = build_pipeline(records={})
    try:
        execute(pipeline, make_request(mode=SearchMode.CLAIM))
    except DomainError as exc:
        assert exc.code == "INVALID_REQUEST"
    else:
        raise AssertionError("non-thematic mode was accepted")


def test_exclusive_groups_and_classification_notice() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_c": make_record("ev_c", "SYNTHETIC_TEXT_C"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b"), make_candidate("ev_c")],
        assignments=[
            ClusterAssignment("cluster_institutions", ("ev_a", "ev_b")),
            ClusterAssignment("cluster_relations", ("ev_c",)),
        ],
        labels={
            "cluster_institutions": ThemeLabel(
                cluster_id="cluster_institutions",
                label="institutions",
                summary="SYNTHETIC_SUMMARY_INSTITUTIONS",
                evidence_ids=("ev_a", "ev_b"),
                confidence=0.8,
            ),
            "cluster_relations": ThemeLabel(
                cluster_id="cluster_relations",
                label="relations",
                summary="SYNTHETIC_SUMMARY_RELATIONS",
                evidence_ids=("ev_c",),
                confidence=0.7,
            ),
        },
    )
    response = execute(pipeline)
    SearchResponse.model_validate(response.model_dump())
    assert response.classification_notice == CLASSIFICATION_NOTICE
    assert [group.group_id for group in response.groups] == [
        "cluster_institutions",
        "cluster_relations",
    ]
    assert response.groups[0].evidence_ids == ["ev_a", "ev_b"]
    assert response.groups[1].evidence_ids == ["ev_c"]
    assert grouped_ids(response) == ["ev_a", "ev_b", "ev_c"]
    assert [item.evidence_id for item in response.evidence] == ["ev_a", "ev_b", "ev_c"]
    assert len(set(grouped_ids(response))) == 3
    assert response.overview.evidence_count == 3
    assert response.insufficiency is None


def test_duplicate_and_unauthorized_cluster_ids_are_dropped() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[
            ClusterAssignment("cluster_a", ("ev_a", "ev_b", "ev_model_injected")),
            ClusterAssignment("cluster_b", ("ev_b", "ev_outside")),
        ],
    )
    response = execute(pipeline)
    assert grouped_ids(response) == ["ev_a", "ev_b"]
    assert "ev_model_injected" not in grouped_ids(response)
    assert all(group.evidence_ids.count("ev_b") == 1 for group in response.groups)
    assert sum(group.evidence_ids.count("ev_b") for group in response.groups) == 1


def test_unassigned_evidence_enters_other_related() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_outlier": make_record("ev_outlier", "SYNTHETIC_TEXT_OUTLIER"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_b"),
            make_candidate("ev_outlier"),
        ],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
    )
    response = execute(pipeline)
    assert response.groups[-1].group_id == "other_related"
    assert response.groups[-1].evidence_ids == ["ev_outlier"]
    assert "ev_outlier" in {item.evidence_id for item in response.evidence}


def test_label_failure_falls_back_to_numbered_themes() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[
            ClusterAssignment("cluster_a", ("ev_a",)),
            ClusterAssignment("cluster_b", ("ev_b",)),
        ],
        labels=RuntimeError("labeler down"),
    )
    response = execute(pipeline)
    assert [group.label for group in response.groups] == ["主题 1", "主题 2"]
    assert all(group.summary is None for group in response.groups)
    assert any(warning.code == "LABELING_UNAVAILABLE" for warning in response.warnings)


def test_machine_labels_can_be_disabled() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[
            ClusterAssignment("cluster_a", ("ev_a",)),
            ClusterAssignment("cluster_b", ("ev_b",)),
        ],
        labels={
            "cluster_a": ThemeLabel("cluster_a", "should-not-appear", evidence_ids=("ev_a",)),
            "cluster_b": ThemeLabel("cluster_b", "also-hidden", evidence_ids=("ev_b",)),
        },
    )
    response = execute(
        pipeline,
        make_request(options=SearchOptions(include_generated_summaries=False)),
    )
    assert [group.label for group in response.groups] == ["主题 1", "主题 2"]
    assert all(group.summary is None for group in response.groups)
    assert grouped_ids(response) == ["ev_a", "ev_b"]


def test_clusterer_failure_keeps_evidence_in_other_related() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=RuntimeError("clusterer down"),
    )
    response = execute(pipeline)
    assert [group.group_id for group in response.groups] == ["other_related"]
    assert grouped_ids(response) == ["ev_a", "ev_b"]
    assert {item.evidence_id for item in response.evidence} == {"ev_a", "ev_b"}
    assert any(warning.code == "CLUSTERING_UNAVAILABLE" for warning in response.warnings)
    assert response.classification_notice == CLASSIFICATION_NOTICE


def test_empty_result_is_not_a_pass_and_keeps_notice() -> None:
    pipeline = build_pipeline(records={})
    response = execute(pipeline)
    SearchResponse.model_validate(response.model_dump())
    assert response.evidence == []
    assert response.groups == []
    assert response.overview.evidence_count == 0
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_RELEVANT_EVIDENCE"
    assert response.classification_notice == CLASSIFICATION_NOTICE


def test_partial_gate_exclusions_keep_remaining_evidence() -> None:
    records = {"ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A")}
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_missing"),
        ],
        assignments=[ClusterAssignment("cluster_a", ("ev_a",))],
    )
    response = execute(pipeline)
    assert [item.evidence_id for item in response.evidence] == ["ev_a"]
    assert any(warning.code == "EVIDENCE_GATE_PARTIAL" for warning in response.warnings)
    assert response.insufficiency is None
    assert response.classification_notice == CLASSIFICATION_NOTICE


def test_labeler_cannot_inject_summary_without_in_group_ids() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        labels={
            "cluster_a": ThemeLabel(
                cluster_id="cluster_a",
                label="institutions",
                summary="cannot trace this summary",
                evidence_ids=("ev_injected",),
            )
        },
    )
    response = execute(pipeline)
    assert response.groups[0].label == "主题 1"
    assert response.groups[0].summary is None
    assert response.groups[0].evidence_ids == ["ev_a", "ev_b"]
    assert any(warning.code == "LABELING_UNAVAILABLE" for warning in response.warnings)


def test_irrelevant_candidates_do_not_enter_theme_groups() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_irrelevant": make_record("ev_irrelevant", "SYNTHETIC_TEXT_IRRELEVANT"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_irrelevant"),
        ],
        assignments=[
            ClusterAssignment("cluster_a", ("ev_a", "ev_irrelevant")),
        ],
        relevance_stage=ScriptedRelevanceStage(
            labels={
                "ev_a": SupportLabel.DIRECT,
                "ev_irrelevant": SupportLabel.IRRELEVANT,
            }
        ),
    )
    response = execute(pipeline)
    assert grouped_ids(response) == ["ev_a"]
    assert "ev_irrelevant" not in grouped_ids(response)
    assert "ev_irrelevant" not in {item.evidence_id for item in response.evidence}
    assert all(group.group_id != "other_related" for group in response.groups)
    assert any(warning.code == "IRRELEVANT_FILTERED" for warning in response.warnings)


def test_sqlite_and_vector_failure_is_not_an_empty_success() -> None:
    pipeline = build_pipeline(
        records={"ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A")},
        lexical=RuntimeError("sqlite lexical down"),
        vector=RuntimeError("vector index down"),
        assignments=[ClusterAssignment("cluster_a", ("ev_a",))],
    )
    try:
        execute(pipeline)
    except DomainError as exc:
        assert exc.code == "VECTOR_INDEX_UNAVAILABLE"
        assert exc.retryable is True
        assert "both failed" in exc.message
    else:
        raise AssertionError("dual recall failure returned a search response")


def test_embedding_failure_does_not_call_clusterer_or_emit_themes() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    clusterer = ScriptedClusterer([ClusterAssignment("cluster_a", ("ev_a", "ev_b"))])
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        embedding=FakeEmbedding(document_error=RuntimeError("evidence embed down")),
        clusterer=clusterer,
        labels={
            "cluster_a": ThemeLabel(
                "cluster_a",
                "should-not-appear",
                evidence_ids=("ev_a", "ev_b"),
            )
        },
    )
    response = execute(pipeline)
    assert clusterer.calls == 0
    assert response.groups == []
    assert [item.evidence_id for item in response.evidence] == ["ev_a", "ev_b"]
    assert any(warning.code == "EMBEDDING_UNAVAILABLE" for warning in response.warnings)
    assert response.insufficiency is not None
    assert response.insufficiency.code == "THEMATIC_CLUSTERING_UNAVAILABLE"
    assert all(group.group_type != "theme" for group in response.groups)


def test_low_rerank_score_is_excluded_before_evidence_and_clustering() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_weak": make_record("ev_weak", "SYNTHETIC_TEXT_WEAK"),
    }
    clusterer = ScriptedClusterer(
        [ClusterAssignment("cluster_a", ("ev_a", "ev_weak"))]
    )
    service = RecordingEvidenceService(FakeEvidenceRepository(records))
    relevance = ScriptedRelevanceStage(scores={"ev_a": 0.9, "ev_weak": 0.01})
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_weak"),
        ],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_weak"))],
        evidence_service=service,
        clusterer=clusterer,
        relevance_stage=relevance,
    )
    response = execute(pipeline)
    assert relevance.calls == 1
    assert service.hydrate_calls == 1
    assert service.last_allowed == frozenset({"ev_a"})
    assert "ev_weak" not in service.last_candidate_ids
    assert "ev_weak" not in {item.evidence_id for item in response.evidence}
    assert "ev_weak" not in grouped_ids(response)
    assert all(group.group_id != "other_related" for group in response.groups)
    assert any(warning.code == "IRRELEVANT_FILTERED" for warning in response.warnings)


def test_sqlite_domain_error_is_not_converted_to_warning() -> None:
    pipeline = build_pipeline(
        records={
            "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
            "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        },
        lexical=DomainError("SQLITE_UNAVAILABLE", "sqlite down", retryable=True),
        vector=[make_candidate("ev_a"), make_candidate("ev_b")],
    )
    try:
        execute(pipeline)
    except DomainError as exc:
        assert exc.code == "SQLITE_UNAVAILABLE"
        assert exc.retryable is True
    else:
        raise AssertionError("SQLite DomainError was swallowed")


def test_release_mismatch_is_not_converted_to_warning() -> None:
    pipeline = build_pipeline(
        records={"ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A")},
        lexical=DomainError("RELEASE_MISMATCH", "index/data mismatch"),
        vector=[make_candidate("ev_a")],
    )
    try:
        execute(pipeline)
    except DomainError as exc:
        assert exc.code == "RELEASE_MISMATCH"
    else:
        raise AssertionError("RELEASE_MISMATCH was swallowed")


def test_single_channel_failure_degrades_with_warning() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=RuntimeError("fts down"),
        vector=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
    )
    response = execute(pipeline)
    assert {item.evidence_id for item in response.evidence} == {"ev_a", "ev_b"}
    assert any(warning.code == "LEXICAL_UNAVAILABLE" for warning in response.warnings)
    assert response.insufficiency is None


def test_genuine_zero_hits_is_no_relevant_evidence() -> None:
    relevance = ScriptedRelevanceStage()
    pipeline = build_pipeline(
        records={}, lexical=[], vector=[], relevance_stage=relevance
    )
    response = execute(pipeline)
    assert relevance.calls == 0
    assert response.evidence == []
    assert response.groups == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_RELEVANT_EVIDENCE"
    assert all(
        warning.code not in {"LEXICAL_UNAVAILABLE", "VECTOR_UNAVAILABLE"}
        for warning in response.warnings
    )


def test_cited_evidence_ids_reject_unknown_duplicate_and_illegal() -> None:
    cluster = {"ev_a", "ev_b"}
    assert cited_evidence_ids_are_valid(("ev_a", "ev_b"), cluster)
    assert not cited_evidence_ids_are_valid((), cluster)
    assert not cited_evidence_ids_are_valid(("ev_a", "ev_injected"), cluster)
    assert not cited_evidence_ids_are_valid(("ev_a", "ev_a"), cluster)
    assert not cited_evidence_ids_are_valid(("",), cluster)
    assert not cited_evidence_ids_are_valid((" ev_a",), cluster)


def test_labeler_out_of_group_ids_fall_back_and_do_not_expand_pool() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_outside": make_record("ev_outside", "SYNTHETIC_TEXT_OUTSIDE"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        labels={
            "cluster_a": ThemeLabel(
                cluster_id="cluster_a",
                label="unsafe-injected-label",
                summary="summary citing an out-of-group id",
                evidence_ids=("ev_a", "ev_outside"),
            )
        },
    )
    response = execute(pipeline)
    assert response.groups[0].label == "主题 1"
    assert response.groups[0].summary is None
    assert response.groups[0].evidence_ids == ["ev_a", "ev_b"]
    assert "ev_outside" not in grouped_ids(response)
    assert "ev_outside" not in {item.evidence_id for item in response.evidence}
    assert any(warning.code == "LABELING_UNAVAILABLE" for warning in response.warnings)


def test_labeler_duplicate_or_blank_ids_fall_back() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    duplicate_pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        labels={
            "cluster_a": ThemeLabel(
                cluster_id="cluster_a",
                label="duplicate-citation",
                summary="should not appear",
                evidence_ids=("ev_a", "ev_a"),
            )
        },
    )
    duplicate_response = execute(duplicate_pipeline)
    assert duplicate_response.groups[0].label == "主题 1"
    assert duplicate_response.groups[0].summary is None

    blank_pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        labels={
            "cluster_a": ThemeLabel(
                cluster_id="cluster_a",
                label="blank-citation",
                summary="should not appear",
                evidence_ids=("ev_a", ""),
            )
        },
    )
    blank_response = execute(blank_pipeline)
    assert blank_response.groups[0].label == "主题 1"
    assert blank_response.groups[0].summary is None


def test_overview_counts_distinct_work_and_volume_ids_not_display_fields() -> None:
    records = {
        "ev_a": make_record(
            "ev_a",
            "SYNTHETIC_TEXT_A",
            work_title="Same Title",
            work_id="work_one",
            volume_id="vol_one",
            volume_no=1,
        ),
        "ev_b": make_record(
            "ev_b",
            "SYNTHETIC_TEXT_B",
            work_title="Same Title",
            work_id="work_two",
            volume_id="vol_two",
            volume_no=1,
        ),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
    )
    response = execute(pipeline)
    assert response.overview.evidence_count == 2
    assert response.overview.work_count == 2
    assert response.overview.volume_count == 2


def test_hydrate_locks_allowed_evidence_ids_to_gated_pool() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_irrelevant": make_record("ev_irrelevant", "SYNTHETIC_TEXT_IRRELEVANT"),
        "ev_injected": make_record("ev_injected", "SYNTHETIC_TEXT_INJECTED"),
    }
    service = RecordingEvidenceService(FakeEvidenceRepository(records))
    clusterer = ScriptedClusterer(
        [ClusterAssignment("cluster_a", ("ev_a", "ev_b", "ev_injected", "ev_irrelevant"))]
    )
    relevance = ScriptedRelevanceStage(
        labels={
            "ev_a": SupportLabel.DIRECT,
            "ev_b": SupportLabel.DIRECT,
            "ev_irrelevant": SupportLabel.IRRELEVANT,
        },
        extras=[make_candidate("ev_injected")],
    )
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_b"),
            make_candidate("ev_irrelevant"),
        ],
        evidence_service=service,
        clusterer=clusterer,
        relevance_stage=relevance,
        labels={
            "cluster_a": ThemeLabel(
                cluster_id="cluster_a",
                label="should-not-expand",
                evidence_ids=("ev_a", "ev_injected"),
            )
        },
    )
    response = execute(pipeline)
    assert service.hydrate_calls == 1
    assert service.last_allowed == frozenset({"ev_a", "ev_b"})
    assert set(service.last_candidate_ids) == {"ev_a", "ev_b"}
    assert {item.evidence_id for item in response.evidence} == {"ev_a", "ev_b"}
    assert "ev_injected" not in grouped_ids(response)
    assert "ev_irrelevant" not in grouped_ids(response)


def test_relevance_stage_is_called_for_unlabeled_index_candidates() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    relevance = ScriptedRelevanceStage()
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        relevance_stage=relevance,
    )
    response = execute(pipeline)
    assert relevance.calls == 1
    assert relevance.last_query == "SYNTHETIC_THEMATIC_QUERY"
    assert set(relevance.last_ids) == {"ev_a", "ev_b"}
    assert {item.evidence_id for item in response.evidence} == {"ev_a", "ev_b"}
    assert all("rerank" in item.rank_reasons for item in response.evidence)


def test_unlabeled_candidates_do_not_silently_pass_relevance() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    relevance = ScriptedRelevanceStage(passthrough=True)
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        relevance_stage=relevance,
    )
    response = execute(pipeline)
    assert relevance.calls == 1
    assert response.evidence == []
    assert response.groups == []
    assert response.insufficiency is not None
    assert response.insufficiency.code == "NO_RELEVANT_EVIDENCE"
    assert any(warning.code == "IRRELEVANT_FILTERED" for warning in response.warnings)


def test_relevance_unavailable_degrades_with_warning() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    relevance = ScriptedRelevanceStage(error=RuntimeError("reranker down"))
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        relevance_stage=relevance,
    )
    response = execute(pipeline)
    assert relevance.calls == 1
    assert {item.evidence_id for item in response.evidence} == {"ev_a", "ev_b"}
    assert any(warning.code == "RERANKER_UNAVAILABLE" for warning in response.warnings)
    assert all("rerank" not in item.rank_reasons for item in response.evidence)


def test_relevance_output_cannot_inject_unknown_or_duplicate_ids() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_injected": make_record("ev_injected", "SYNTHETIC_TEXT_INJECTED"),
    }
    service = RecordingEvidenceService(FakeEvidenceRepository(records))
    relevance = ScriptedRelevanceStage(
        extras=[make_candidate("ev_injected"), make_candidate("ev_a")]
    )
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        evidence_service=service,
        relevance_stage=relevance,
    )
    response = execute(pipeline)
    assert relevance.calls == 1
    assert service.last_allowed == frozenset({"ev_a", "ev_b"})
    assert "ev_injected" not in set(service.last_candidate_ids)
    assert "ev_injected" not in {item.evidence_id for item in response.evidence}


def test_invalid_high_rank_candidate_is_backfilled() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_c": make_record("ev_c", "SYNTHETIC_TEXT_C"),
    }
    service = RecordingEvidenceService(FakeEvidenceRepository(records))
    clusterer = ScriptedClusterer([ClusterAssignment("cluster_a", ("ev_a", "ev_b"))])
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_missing"),
            make_candidate("ev_a"),
            make_candidate("ev_b"),
            make_candidate("ev_c"),
        ],
        evidence_service=service,
        clusterer=clusterer,
        config=ThematicPipelineConfig(fusion_top_k=10, final_top_k=2),
    )
    response = execute(pipeline, make_request(page_size=2))
    assert service.last_candidate_ids == ("ev_missing", "ev_a", "ev_b", "ev_c")
    assert clusterer.last_ids == ("ev_a", "ev_b")
    assert [item.evidence_id for item in response.evidence] == ["ev_a", "ev_b"]
    assert grouped_ids(response) == ["ev_a", "ev_b"]
    assert response.overview.evidence_count == 2
    assert any(warning.code == "EVIDENCE_GATE_PARTIAL" for warning in response.warnings)


def test_page_size_caps_groups_evidence_and_overview() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_c": make_record("ev_c", "SYNTHETIC_TEXT_C"),
        "ev_d": make_record("ev_d", "SYNTHETIC_TEXT_D"),
    }
    clusterer = ScriptedClusterer(
        [ClusterAssignment("cluster_a", ("ev_a", "ev_b", "ev_c", "ev_d"))]
    )
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_b"),
            make_candidate("ev_c"),
            make_candidate("ev_d"),
        ],
        clusterer=clusterer,
        config=ThematicPipelineConfig(fusion_top_k=10, final_top_k=20),
    )
    response = execute(pipeline, make_request(page_size=2))
    assert len(clusterer.last_ids) == 2
    assert [item.evidence_id for item in response.evidence] == list(clusterer.last_ids)
    assert grouped_ids(response) == [item.evidence_id for item in response.evidence]
    assert response.overview.evidence_count == 2
    assert len(response.evidence) == 2


def test_final_top_k_caps_cluster_input_below_page_size() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
        "ev_c": make_record("ev_c", "SYNTHETIC_TEXT_C"),
    }
    clusterer = ScriptedClusterer(
        [ClusterAssignment("cluster_a", ("ev_a", "ev_b", "ev_c"))]
    )
    pipeline = build_pipeline(
        records=records,
        lexical=[
            make_candidate("ev_a"),
            make_candidate("ev_b"),
            make_candidate("ev_c"),
        ],
        clusterer=clusterer,
        config=ThematicPipelineConfig(
            fusion_top_k=10, final_top_k=1, min_cluster_input=1
        ),
    )
    response = execute(pipeline, make_request(page_size=10))
    assert clusterer.last_ids == ("ev_a",)
    assert [item.evidence_id for item in response.evidence] == ["ev_a"]
    assert grouped_ids(response) == ["ev_a"]
    assert response.overview.evidence_count == 1


def test_release_snapshot_uses_resolved_scope_once_before_recall() -> None:
    events: list[str] = []
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    request_scope = SearchScope.model_validate({"corpus_ids": [CORPUS_ID]})
    resolved = request_scope.model_copy(update={"edition_ids": ["edition_resolved"]})
    repository = FakeEvidenceRepository(records)
    service = RecordingEvidenceService(repository, events=events)
    relevance = ScriptedRelevanceStage(events=events)
    release_provider = RecordingReleaseProvider(SYNTHETIC_RELEASE, events=events)
    pipeline = ThematicPipeline(
        scope_resolver=TrackingScopeResolver(events, resolved),
        lexical_index=FakeLexicalIndex(
            [make_candidate("ev_a"), make_candidate("ev_b")], events=events
        ),
        vector_index=FakeVectorIndex((), events=events),
        embedding=FakeEmbedding(),
        evidence_service=service,
        relevance_stage=relevance,
        clusterer=ScriptedClusterer(
            [ClusterAssignment("cluster_a", ("ev_a", "ev_b"))]
        ),
        release_provider=release_provider,
        overview_provider=CountOverviewProvider(repository),
    )
    execute(pipeline)
    assert events == [
        "resolve",
        "snapshot_for",
        "lexical",
        "vector",
        "relevance",
        "hydrate",
    ]
    assert release_provider.calls == 1
    assert release_provider.scopes[0].edition_ids == ["edition_resolved"]
    assert release_provider.scopes[0].corpus_ids == [CORPUS_ID]
    assert not hasattr(FixedReleaseProvider, "current")


def test_empty_model_label_evidence_ids_are_untraceable() -> None:
    records = {
        "ev_a": make_record("ev_a", "SYNTHETIC_TEXT_A"),
        "ev_b": make_record("ev_b", "SYNTHETIC_TEXT_B"),
    }
    pipeline = build_pipeline(
        records=records,
        lexical=[make_candidate("ev_a"), make_candidate("ev_b")],
        assignments=[ClusterAssignment("cluster_a", ("ev_a", "ev_b"))],
        labels={
            "cluster_a": ThemeLabel(
                cluster_id="cluster_a",
                label="untraceable-theme",
                summary="cannot keep this summary",
                evidence_ids=(),
            )
        },
    )
    response = execute(pipeline)
    assert response.groups[0].label == "主题 1"
    assert response.groups[0].summary is None
    assert any(warning.code == "LABELING_UNAVAILABLE" for warning in response.warnings)