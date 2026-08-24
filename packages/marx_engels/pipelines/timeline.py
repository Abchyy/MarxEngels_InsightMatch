"""Independent timeline search pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from marx_engels.contracts import (
    Candidate,
    Evidence,
    Insufficiency,
    ReleaseInfo,
    ResultGroup,
    SearchMode,
    SearchRequest,
    SearchResponse,
    SearchScope,
    SupportLabel,
    Warning,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceService
from marx_engels.model_adapters import EmbeddingProvider, Reranker
from marx_engels.pipelines.timeline_grouping import organize_timeline
from marx_engels.pipelines.timeline_ports import (
    TimelineOverviewProvider,
    TimelineReleaseProvider,
    TimelineSummaryProvider,
)
from marx_engels.retrieval_core import LexicalIndex, ScopeResolver, VectorIndex
from marx_engels.retrieval_core.rrf import reciprocal_rank_fusion, stable_score_order

_EMPTY_MESSAGE = "在当前范围内未找到可用于时间序列组织的相关证据。"
_BOTH_CHANNELS_MESSAGE = (
    "Lexical and vector recall are unavailable; timeline cannot degrade safely."
)
_AUTHORITATIVE_ERROR_CODES = frozenset(
    {
        "SQLITE_UNAVAILABLE",
        "RELEASE_MISMATCH",
        "INVALID_SCOPE",
        "CORPUS_NOT_FOUND",
        "STORAGE_NOT_CONFIGURED",
    }
)
_RERANK_FALLBACK_WARNING = Warning(
    code="RERANKER_UNAVAILABLE",
    message=(
        "Relevance reranker is unavailable; using reciprocal-rank fusion as the relevance gate."
    ),
    stage="rerank",
)


class TimelinePipeline:
    """Hybrid-recall timeline organizer that only accepts timeline requests."""

    def __init__(
        self,
        *,
        scope_resolver: ScopeResolver,
        lexical_index: LexicalIndex,
        vector_index: VectorIndex,
        embedding_provider: EmbeddingProvider,
        evidence_service: EvidenceService,
        release_provider: TimelineReleaseProvider,
        overview_provider: TimelineOverviewProvider,
        reranker: Reranker | None = None,
        summary_provider: TimelineSummaryProvider | None = None,
        lexical_top_k: int = 100,
        vector_top_k: int = 100,
        fusion_top_k: int = 80,
        rerank_top_k: int = 50,
        final_top_k: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self._scope_resolver = scope_resolver
        self._lexical_index = lexical_index
        self._vector_index = vector_index
        self._embedding_provider = embedding_provider
        self._evidence_service = evidence_service
        self._release_provider = release_provider
        self._overview_provider = overview_provider
        self._reranker = reranker
        self._summary_provider = summary_provider
        self._lexical_top_k = lexical_top_k
        self._vector_top_k = vector_top_k
        self._fusion_top_k = fusion_top_k
        self._rerank_top_k = rerank_top_k
        self._final_top_k = final_top_k
        self._rrf_k = rrf_k

    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse:
        if request.mode is not SearchMode.TIMELINE:
            raise DomainError(
                "INVALID_REQUEST",
                "TimelinePipeline only accepts timeline requests.",
                details={"mode": request.mode.value},
            )
        scope = await self._scope_resolver.resolve(request.scope)
        release = self._release_provider.release_for(scope)
        warnings: list[Warning] = []
        candidates, warnings = await self._recall(request.query, scope, warnings)
        allowed_ids = frozenset(candidate.evidence_id for candidate in candidates)
        candidates, warnings = await self._maybe_rerank(request.query, candidates, warnings)
        candidates = [
            candidate
            for candidate in candidates
            if candidate.support_label is not SupportLabel.IRRELEVANT
            and candidate.evidence_id in allowed_ids
        ]
        hydration = await self._evidence_service.hydrate(
            candidates,
            scope,
            allowed_evidence_ids=allowed_ids,
        )
        groups, evidence = organize_timeline(hydration.evidence)
        page_size = min(self._final_top_k, request.page_size)
        evidence = evidence[:page_size]
        groups, evidence = organize_timeline(evidence)
        if request.options.include_generated_summaries:
            groups, warnings = await self._maybe_summarize(
                request.query, groups, evidence, warnings
            )
        return self._response(
            request=request,
            request_id=request_id,
            scope=scope,
            release=release,
            evidence=evidence,
            groups=groups,
            warnings=warnings,
        )

    async def _recall(
        self, query: str, scope: SearchScope, warnings: list[Warning]
    ) -> tuple[list[Candidate], list[Warning]]:
        lexical_result, semantic_result = await asyncio.gather(
            self._search_lexical(query, scope),
            self._search_semantic(query, scope),
            return_exceptions=True,
        )
        _reraise_authoritative(lexical_result)
        _reraise_authoritative(semantic_result)
        lexical = _recover_channel(
            lexical_result, warnings, "LEXICAL_INDEX_UNAVAILABLE", "lexical recall"
        )
        vector = _recover_channel(
            semantic_result, warnings, "VECTOR_INDEX_UNAVAILABLE", "vector recall"
        )
        lexical_failed = _is_channel_failure(lexical_result)
        vector_failed = _is_channel_failure(semantic_result)
        if lexical_failed and vector_failed:
            raise DomainError(
                "VECTOR_INDEX_UNAVAILABLE",
                _BOTH_CHANNELS_MESSAGE,
                retryable=True,
            )
        if not lexical and not vector:
            return [], warnings
        fused = _fuse_candidates(lexical, vector, rank_constant=self._rrf_k)
        return fused[: self._fusion_top_k], warnings

    async def _search_lexical(self, query: str, scope: SearchScope) -> list[Candidate]:
        return await self._lexical_index.search_lexical(query, scope, self._lexical_top_k)

    async def _search_semantic(self, query: str, scope: SearchScope) -> list[Candidate]:
        vectors = await self._embedding_provider.embed([query])
        if not vectors:
            raise RuntimeError("embedding provider returned no query vector")
        return await self._vector_index.search_vector(vectors[0], scope, self._vector_top_k)

    async def _maybe_rerank(
        self, query: str, candidates: list[Candidate], warnings: list[Warning]
    ) -> tuple[list[Candidate], list[Warning]]:
        pool_ids = frozenset(candidate.evidence_id for candidate in candidates)
        if not candidates:
            return candidates, warnings
        if self._reranker is None:
            warnings.append(_RERANK_FALLBACK_WARNING)
            return candidates, warnings
        try:
            reranked = await self._reranker.rerank(query, candidates)
        except Exception as exc:
            warnings.append(
                Warning(
                    code="RERANKER_UNAVAILABLE",
                    message=str(exc) or "Reranker failed; using fusion order.",
                    stage="rerank",
                )
            )
            return candidates, warnings
        sanitized = _sanitize_reranked(reranked, candidates, pool_ids)
        if not sanitized:
            warnings.append(_RERANK_FALLBACK_WARNING)
            return candidates, warnings
        return sanitized[: self._rerank_top_k], warnings

    async def _maybe_summarize(
        self,
        query: str,
        groups: list[ResultGroup],
        evidence: Sequence[Evidence],
        warnings: list[Warning],
    ) -> tuple[list[ResultGroup], list[Warning]]:
        if self._summary_provider is None:
            return groups, warnings
        by_id = {item.evidence_id: item for item in evidence}
        summarized: list[ResultGroup] = []
        for group in groups:
            members = [
                by_id[evidence_id]
                for evidence_id in group.evidence_ids
                if evidence_id in by_id
            ]
            try:
                summary = await self._summary_provider.summarize_group(
                    query, group.group_id, members
                )
            except Exception as exc:
                warnings.append(
                    Warning(
                        code="LLM_UNAVAILABLE",
                        message=str(exc) or "Stage summary unavailable.",
                        stage="summarize",
                    )
                )
                summarized.append(group)
                continue
            summarized.append(group.model_copy(update={"summary": summary}))
        return summarized, warnings

    def _response(
        self,
        *,
        request: SearchRequest,
        request_id: str,
        scope: SearchScope,
        release: ReleaseInfo,
        evidence: Sequence[Evidence],
        groups: Sequence[ResultGroup],
        warnings: Sequence[Warning],
    ) -> SearchResponse:
        insufficiency = None
        if not evidence:
            insufficiency = Insufficiency(code="NO_TIMELINE_EVIDENCE", message=_EMPTY_MESSAGE)
        return SearchResponse(
            request_id=request_id,
            mode=SearchMode.TIMELINE,
            query=request.query,
            scope_snapshot=scope,
            release=release,
            overview=self._overview_provider.overview(evidence),
            groups=list(groups),
            evidence=list(evidence),
            next_cursor=None,
            insufficiency=insufficiency,
            warnings=list(warnings),
        )


def _reraise_authoritative(result: object) -> None:
    if isinstance(result, DomainError) and result.code in _AUTHORITATIVE_ERROR_CODES:
        raise result


def _is_channel_failure(result: object) -> bool:
    return isinstance(result, BaseException)


def _recover_channel(
    result: object,
    warnings: list[Warning],
    code: str,
    stage: str,
) -> list[Candidate]:
    if isinstance(result, BaseException):
        warnings.append(Warning(code=code, message=str(result) or code, stage=stage))
        return []
    if isinstance(result, list):
        return result
    warnings.append(Warning(code=code, message="unexpected recall payload", stage=stage))
    return []


def _sanitize_reranked(
    reranked: Sequence[Candidate],
    original: Sequence[Candidate],
    pool_ids: frozenset[str],
) -> list[Candidate]:
    by_id = {candidate.evidence_id: candidate for candidate in original}
    seen: set[str] = set()
    sanitized: list[Candidate] = []
    for item in reranked:
        evidence_id = item.evidence_id
        if not evidence_id or evidence_id not in pool_ids or evidence_id in seen:
            continue
        seen.add(evidence_id)
        source = by_id[evidence_id]
        sanitized.append(
            source.model_copy(
                update={
                    "support_label": item.support_label or source.support_label,
                    "rerank_score": item.rerank_score,
                    "rank_reasons": list(
                        dict.fromkeys([*source.rank_reasons, *item.rank_reasons])
                    ),
                }
            )
        )
    return sanitized


def _fuse_candidates(
    lexical: Sequence[Candidate],
    vector: Sequence[Candidate],
    *,
    rank_constant: int,
) -> list[Candidate]:
    lexical_ids = [candidate.evidence_id for candidate in lexical]
    vector_ids = [candidate.evidence_id for candidate in vector]
    rankings = [ranking for ranking in (lexical_ids, vector_ids) if ranking]
    scores = reciprocal_rank_fusion(rankings, rank_constant=rank_constant) if rankings else {}
    merged: dict[str, Candidate] = {}
    for candidate in [*lexical, *vector]:
        existing = merged.get(candidate.evidence_id)
        merged[candidate.evidence_id] = (
            candidate if existing is None else _merge_candidate(existing, candidate)
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


def _merge_candidate(existing: Candidate, incoming: Candidate) -> Candidate:
    return existing.model_copy(
        update={
            "channels": list(dict.fromkeys([*existing.channels, *incoming.channels])),
            "retrieval_unit_ids": list(
                dict.fromkeys([*existing.retrieval_unit_ids, *incoming.retrieval_unit_ids])
            ),
            "lexical_rank": _first_value(existing.lexical_rank, incoming.lexical_rank),
            "lexical_score": _first_value(existing.lexical_score, incoming.lexical_score),
            "vector_rank": _first_value(existing.vector_rank, incoming.vector_rank),
            "vector_score": _first_value(existing.vector_score, incoming.vector_score),
            "text_hash": existing.text_hash or incoming.text_hash,
            "support_label": existing.support_label or incoming.support_label,
            "rank_reasons": list(dict.fromkeys([*existing.rank_reasons, *incoming.rank_reasons])),
        }
    )


def _first_value[T](left: T | None, right: T | None) -> T | None:
    return left if left is not None else right
