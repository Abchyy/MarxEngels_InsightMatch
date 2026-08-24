"""Independent thematic search pipeline with fail-closed clustering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from marx_engels.contracts import (
    Candidate,
    Evidence,
    Insufficiency,
    ReleaseInfo,
    ResultGroup,
    SearchMode,
    SearchOverview,
    SearchRequest,
    SearchResponse,
    SearchScope,
    Warning,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceService
from marx_engels.model_adapters.ports import EmbeddingProvider
from marx_engels.pipelines.thematic_grouping import (
    apply_relevance_judgments,
    assign_exclusively,
    fails_relevance_gate,
    fallback_theme_label,
    is_irrelevant,
    other_related_group,
    resolve_theme_presentation,
    sort_theme_clusters,
    theme_result_group,
)
from marx_engels.pipelines.thematic_types import (
    CLASSIFICATION_NOTICE,
    ClusterAssignment,
    OverviewProvider,
    ReleaseSnapshotProvider,
    SanitizedGrouping,
    ThematicPipelineConfig,
    ThemeClusterer,
    ThemeLabeler,
    ThemeRelevanceStage,
)
from marx_engels.retrieval_core import EvidenceRepository, LexicalIndex, ScopeResolver, VectorIndex
from marx_engels.retrieval_core.rrf import reciprocal_rank_fusion, stable_score_order

_EMPTY_INSUFFICIENCY = Insufficiency(
    code="NO_RELEVANT_EVIDENCE",
    message="在当前范围内未找到可组织的思想结构证据。",
)
_CLUSTERING_INSUFFICIENCY = Insufficiency(
    code="THEMATIC_CLUSTERING_UNAVAILABLE",
    message="证据向量不可用，无法组织主题结构。",
)
_HARD_INFRA_CODES = frozenset(
    {
        "SQLITE_UNAVAILABLE",
        "RELEASE_MISMATCH",
        "STORAGE_NOT_CONFIGURED",
    }
)


@dataclass(frozen=True)
class _RecallOutcome:
    candidates: tuple[Candidate, ...]
    scores: dict[str, float]
    lexical_failed: bool
    vector_failed: bool


@dataclass(frozen=True)
class _ClusterOutcome:
    grouping: SanitizedGrouping | None
    embeddings_unavailable: bool


@dataclass(frozen=True)
class FixedReleaseProvider:
    release: ReleaseInfo

    async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo:
        del scope
        return self.release


class CountOverviewProvider:
    """Count works and volumes from authoritative IDs, never from display fields."""

    def __init__(self, repository: EvidenceRepository) -> None:
        self._repository = repository

    async def build(self, evidence: Sequence[Evidence]) -> SearchOverview:
        if not evidence:
            return SearchOverview(evidence_count=0, work_count=0, volume_count=0)
        records = await self._repository.get_by_ids([item.evidence_id for item in evidence])
        work_ids = {
            records[item.evidence_id].work_id
            for item in evidence
            if item.evidence_id in records
        }
        volume_ids = {
            records[item.evidence_id].volume_id
            for item in evidence
            if item.evidence_id in records
        }
        return SearchOverview(
            evidence_count=len(evidence),
            work_count=len(work_ids),
            volume_count=len(volume_ids),
        )


class ThematicPipeline:
    """SearchPipeline that organizes hydrated evidence into exclusive theme groups."""

    def __init__(
        self,
        *,
        scope_resolver: ScopeResolver,
        lexical_index: LexicalIndex,
        vector_index: VectorIndex,
        embedding: EmbeddingProvider,
        evidence_service: EvidenceService,
        relevance_stage: ThemeRelevanceStage,
        clusterer: ThemeClusterer,
        release_provider: ReleaseSnapshotProvider,
        overview_provider: OverviewProvider,
        labeler: ThemeLabeler | None = None,
        config: ThematicPipelineConfig | None = None,
    ) -> None:
        self._scope_resolver = scope_resolver
        self._lexical_index = lexical_index
        self._vector_index = vector_index
        self._embedding = embedding
        self._evidence_service = evidence_service
        self._relevance_stage = relevance_stage
        self._clusterer = clusterer
        self._release_provider = release_provider
        self._overview_provider = overview_provider
        self._labeler = labeler
        self._config = config or ThematicPipelineConfig()

    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse:
        if request.mode is not SearchMode.THEMATIC:
            raise DomainError(
                "INVALID_REQUEST",
                "ThematicPipeline only accepts thematic mode.",
                details={"mode": request.mode.value},
            )

        resolved_scope = await self._scope_resolver.resolve(request.scope)
        release = await self._release_provider.snapshot_for(resolved_scope)
        warnings: list[Warning] = []
        recall = await self._recall(request.query, resolved_scope, warnings)
        if recall.lexical_failed and recall.vector_failed:
            raise DomainError(
                "VECTOR_INDEX_UNAVAILABLE",
                "Lexical recall and vector search both failed.",
                details={"lexical": "failed", "vector": "failed"},
                retryable=True,
            )
        if not recall.candidates:
            return await self._response(
                request=request,
                request_id=request_id,
                scope=resolved_scope,
                release=release,
                evidence=(),
                groups=(),
                warnings=warnings,
                insufficiency=_EMPTY_INSUFFICIENCY,
            )

        scored, judged = await self._relevance(request.query, recall.candidates, warnings)
        candidates = _apply_relevance_gate(
            scored,
            warnings,
            min_rerank_score=self._config.min_rerank_score,
            require_judgment=judged,
        )
        if not candidates:
            return await self._response(
                request=request,
                request_id=request_id,
                scope=resolved_scope,
                release=release,
                evidence=(),
                groups=(),
                warnings=warnings,
                insufficiency=_EMPTY_INSUFFICIENCY,
            )

        allowed_ids = [candidate.evidence_id for candidate in candidates]
        hydration = await self._evidence_service.hydrate(
            candidates,
            resolved_scope,
            allowed_evidence_ids=allowed_ids,
        )
        if hydration.exclusions:
            warnings.append(
                _warning(
                    "EVIDENCE_GATE_PARTIAL",
                    "Some recalled candidates were excluded by the evidence gate.",
                    "evidence_gate",
                )
            )
        surviving = [
            item for item in hydration.evidence if not is_irrelevant(item.support_label)
        ]
        if len(surviving) != len(hydration.evidence):
            _warn_irrelevant(warnings, len(hydration.evidence) - len(surviving))
        by_id = {item.evidence_id: item for item in surviving}
        ordered_evidence = [
            by_id[candidate.evidence_id]
            for candidate in candidates
            if candidate.evidence_id in by_id
        ]
        page_limit = min(self._config.final_top_k, request.page_size)
        evidence = ordered_evidence[:page_limit]
        if not evidence:
            return await self._response(
                request=request,
                request_id=request_id,
                scope=resolved_scope,
                release=release,
                evidence=(),
                groups=(),
                warnings=warnings,
                insufficiency=_EMPTY_INSUFFICIENCY,
            )

        hydrated_ids = [item.evidence_id for item in evidence]
        cluster_outcome = await self._cluster(hydrated_ids, evidence, warnings)
        if cluster_outcome.embeddings_unavailable:
            return await self._response(
                request=request,
                request_id=request_id,
                scope=resolved_scope,
                release=release,
                evidence=tuple(evidence),
                groups=(),
                warnings=warnings,
                insufficiency=_CLUSTERING_INSUFFICIENCY,
            )
        grouping = cluster_outcome.grouping
        if grouping is None:
            return await self._response(
                request=request,
                request_id=request_id,
                scope=resolved_scope,
                release=release,
                evidence=tuple(evidence),
                groups=(),
                warnings=warnings,
                insufficiency=_CLUSTERING_INSUFFICIENCY,
            )
        groups = await self._build_groups(
            grouping.themes,
            grouping.other_related_ids,
            request=request,
            scores=recall.scores,
            warnings=warnings,
        )
        ordered_ids = [evidence_id for group in groups for evidence_id in group.evidence_ids]
        by_id = {item.evidence_id: item for item in evidence}
        ordered_evidence = [
            by_id[evidence_id] for evidence_id in ordered_ids if evidence_id in by_id
        ]
        return await self._response(
            request=request,
            request_id=request_id,
            scope=resolved_scope,
            release=release,
            evidence=tuple(ordered_evidence),
            groups=tuple(groups),
            warnings=warnings,
        )

    async def _recall(
        self,
        query: str,
        scope: SearchScope,
        warnings: list[Warning],
    ) -> _RecallOutcome:
        lexical, lexical_failed = await self._lexical_recall(query, scope, warnings)
        vector, vector_failed = await self._vector_recall(query, scope, warnings)
        rankings = (
            [candidate.evidence_id for candidate in lexical],
            [candidate.evidence_id for candidate in vector],
        )
        scores = reciprocal_rank_fusion(rankings, rank_constant=self._config.rrf_k)
        merged = _merge_candidates(lexical, vector, scores)
        limited = merged[: self._config.fusion_top_k]
        limited_scores = {
            candidate.evidence_id: scores[candidate.evidence_id] for candidate in limited
        }
        return _RecallOutcome(
            candidates=tuple(limited),
            scores=limited_scores,
            lexical_failed=lexical_failed,
            vector_failed=vector_failed,
        )

    async def _lexical_recall(
        self, query: str, scope: SearchScope, warnings: list[Warning]
    ) -> tuple[list[Candidate], bool]:
        try:
            return (
                await self._lexical_index.search_lexical(
                    query, scope, self._config.lexical_top_k
                ),
                False,
            )
        except DomainError as exc:
            if exc.code in _HARD_INFRA_CODES:
                raise
            warnings.append(
                _warning(
                    "LEXICAL_UNAVAILABLE",
                    "Lexical recall failed; continuing without it.",
                    "recall",
                )
            )
            return [], True
        except Exception:
            warnings.append(
                _warning(
                    "LEXICAL_UNAVAILABLE",
                    "Lexical recall failed; continuing without it.",
                    "recall",
                )
            )
            return [], True

    async def _vector_recall(
        self, query: str, scope: SearchScope, warnings: list[Warning]
    ) -> tuple[list[Candidate], bool]:
        try:
            embeddings = await self._embedding.embed([query])
            if not embeddings:
                raise RuntimeError("embedding provider returned no query vector")
            return (
                await self._vector_index.search_vector(
                    embeddings[0], scope, self._config.vector_top_k
                ),
                False,
            )
        except DomainError as exc:
            if exc.code in _HARD_INFRA_CODES:
                raise
            warnings.append(
                _warning(
                    "VECTOR_UNAVAILABLE",
                    "Vector recall failed; continuing without it.",
                    "recall",
                )
            )
            return [], True
        except Exception:
            warnings.append(
                _warning(
                    "VECTOR_UNAVAILABLE",
                    "Vector recall failed; continuing without it.",
                    "recall",
                )
            )
            return [], True

    async def _relevance(
        self,
        query: str,
        candidates: Sequence[Candidate],
        warnings: list[Warning],
    ) -> tuple[list[Candidate], bool]:
        try:
            scored = await self._relevance_stage.score(query, candidates)
        except DomainError as exc:
            if exc.code in _HARD_INFRA_CODES:
                raise
            warnings.append(
                _warning(
                    "RERANKER_UNAVAILABLE",
                    "Relevance reranking failed; returning fusion ranking.",
                    "relevance",
                )
            )
            return list(candidates), False
        except Exception:
            warnings.append(
                _warning(
                    "RERANKER_UNAVAILABLE",
                    "Relevance reranking failed; returning fusion ranking.",
                    "relevance",
                )
            )
            return list(candidates), False
        return apply_relevance_judgments(candidates, scored), True

    async def _cluster(
        self,
        allowed_ids: Sequence[str],
        evidence: Sequence[Evidence],
        warnings: list[Warning],
    ) -> _ClusterOutcome:
        if len(allowed_ids) < self._config.min_cluster_input:
            return _ClusterOutcome(
                grouping=assign_exclusively(
                    [ClusterAssignment(cluster_id="cluster_01", evidence_ids=tuple(allowed_ids))],
                    allowed_ids,
                ),
                embeddings_unavailable=False,
            )
        vectors = await self._evidence_vectors(evidence, warnings)
        if any(evidence_id not in vectors for evidence_id in allowed_ids):
            return _ClusterOutcome(grouping=None, embeddings_unavailable=True)
        try:
            assignments = await self._clusterer.cluster(allowed_ids, vectors)
        except Exception:
            warnings.append(
                _warning(
                    "CLUSTERING_UNAVAILABLE",
                    "Clustering failed; evidence is kept in other_related.",
                    "clustering",
                )
            )
            assignments = ()
        return _ClusterOutcome(
            grouping=assign_exclusively(assignments, allowed_ids),
            embeddings_unavailable=False,
        )

    async def _evidence_vectors(
        self, evidence: Sequence[Evidence], warnings: list[Warning]
    ) -> dict[str, Sequence[float]]:
        try:
            vectors = await self._embedding.embed([item.verified_text for item in evidence])
            if len(vectors) != len(evidence):
                raise RuntimeError("embedding count does not match evidence count")
            return {
                item.evidence_id: vector for item, vector in zip(evidence, vectors, strict=True)
            }
        except Exception:
            warnings.append(
                _warning(
                    "EMBEDDING_UNAVAILABLE",
                    "Evidence embeddings were unavailable for clustering.",
                    "clustering",
                )
            )
            return {}

    async def _build_groups(
        self,
        themes: Sequence[ClusterAssignment],
        other_related_ids: Sequence[str],
        *,
        request: SearchRequest,
        scores: Mapping[str, float],
        warnings: list[Warning],
    ) -> list[ResultGroup]:
        ordered_themes = sort_theme_clusters(themes, scores)
        groups = []
        include_summaries = request.options.include_generated_summaries
        for index, cluster in enumerate(ordered_themes, start=1):
            fallback = fallback_theme_label(index)
            model_label = None
            if include_summaries and self._labeler is not None:
                try:
                    model_label = await self._labeler.label(
                        cluster_id=cluster.cluster_id,
                        query=request.query,
                        evidence_ids=cluster.evidence_ids,
                    )
                except Exception:
                    if all(item.code != "LABELING_UNAVAILABLE" for item in warnings):
                        warnings.append(
                            _warning(
                                "LABELING_UNAVAILABLE",
                                "Theme labeling failed; deterministic labels were used.",
                                "labeling",
                            )
                        )
            label, summary, confidence, used_fallback = resolve_theme_presentation(
                model_label,
                cluster,
                include_generated_summaries=include_summaries,
                fallback_label=fallback,
            )
            if (
                used_fallback
                and model_label is not None
                and all(item.code != "LABELING_UNAVAILABLE" for item in warnings)
            ):
                warnings.append(
                    _warning(
                        "LABELING_UNAVAILABLE",
                        "Theme labeling failed; deterministic labels were used.",
                        "labeling",
                    )
                )
            groups.append(
                theme_result_group(
                    cluster,
                    label=label,
                    summary=summary,
                    confidence=confidence,
                    scores=scores,
                )
            )
        leftover = other_related_group(other_related_ids, scores)
        if leftover is not None:
            groups.append(leftover)
        return groups

    async def _response(
        self,
        *,
        request: SearchRequest,
        request_id: str,
        scope: SearchScope,
        release: ReleaseInfo,
        evidence: Sequence[Evidence],
        groups: Sequence[ResultGroup],
        warnings: Sequence[Warning],
        insufficiency: Insufficiency | None = None,
    ) -> SearchResponse:
        return SearchResponse(
            request_id=request_id,
            mode=SearchMode.THEMATIC,
            query=request.query,
            scope_snapshot=scope,
            release=release,
            overview=await self._overview_provider.build(evidence),
            groups=list(groups),
            evidence=list(evidence),
            insufficiency=insufficiency,
            warnings=list(warnings),
            classification_notice=CLASSIFICATION_NOTICE,
        )


def _merge_candidates(
    lexical: Sequence[Candidate],
    vector: Sequence[Candidate],
    scores: Mapping[str, float],
) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for rank, candidate in enumerate(lexical, start=1):
        merged[candidate.evidence_id] = candidate.model_copy(
            update={
                "lexical_rank": rank,
                "channels": _append_channel(candidate.channels, "lexical"),
            }
        )
    for rank, candidate in enumerate(vector, start=1):
        existing = merged.get(candidate.evidence_id)
        if existing is None:
            merged[candidate.evidence_id] = candidate.model_copy(
                update={
                    "vector_rank": rank,
                    "channels": _append_channel(candidate.channels, "vector"),
                }
            )
            continue
        merged[candidate.evidence_id] = existing.model_copy(
            update={
                "vector_rank": rank,
                "vector_score": candidate.vector_score,
                "text_hash": candidate.text_hash or existing.text_hash,
                "channels": _append_channel(existing.channels, "vector"),
            }
        )
    ordered: list[Candidate] = []
    for evidence_id in stable_score_order(scores):
        candidate = merged[evidence_id]
        ordered.append(
            candidate.model_copy(
                update={
                    "fusion_score": scores[evidence_id],
                    "rank_reasons": list(dict.fromkeys([*candidate.rank_reasons, "rrf"])),
                }
            )
        )
    return ordered


def _apply_relevance_gate(
    candidates: Sequence[Candidate],
    warnings: list[Warning],
    *,
    min_rerank_score: float,
    require_judgment: bool,
) -> list[Candidate]:
    relevant = [
        candidate
        for candidate in candidates
        if not fails_relevance_gate(
            candidate.support_label,
            candidate.rerank_score,
            min_rerank_score=min_rerank_score,
            require_judgment=require_judgment,
        )
    ]
    dropped = len(candidates) - len(relevant)
    if dropped:
        _warn_irrelevant(warnings, dropped)
    return relevant


def _warn_irrelevant(warnings: list[Warning], dropped: int) -> None:
    if dropped <= 0 or any(item.code == "IRRELEVANT_FILTERED" for item in warnings):
        return
    warnings.append(
        _warning(
            "IRRELEVANT_FILTERED",
            f"{dropped} irrelevant candidate(s) were excluded from thematic grouping.",
            "relevance",
        )
    )


def _append_channel(channels: Sequence[str], channel: str) -> list[str]:
    return list(dict.fromkeys([*channels, channel]))


def _warning(code: str, message: str, stage: str) -> Warning:
    return Warning(code=code, message=message, stage=stage)
