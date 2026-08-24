"""Claim-mode search pipeline. Independent of exact, timeline, and thematic."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Protocol

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
    SupportLabel,
    Warning,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceService
from marx_engels.model_adapters import EmbeddingProvider, LanguageModel, Reranker
from marx_engels.retrieval_core import (
    AuthoritativeEvidenceRecord,
    EvidenceRepository,
    LexicalIndex,
    ScopeResolver,
    VectorIndex,
)
from marx_engels.retrieval_core.rrf import reciprocal_rank_fusion, stable_score_order

_HYDRATABLE_LABELS = frozenset(
    {
        SupportLabel.DIRECT,
        SupportLabel.INDIRECT,
        SupportLabel.COUNTER,
        SupportLabel.CONTEXT_ONLY,
    }
)
_GROUP_SPECS: tuple[tuple[SupportLabel, str, str, str], ...] = (
    (SupportLabel.DIRECT, "direct", "直接支撑", "support"),
    (SupportLabel.INDIRECT, "indirect", "间接相关", "support"),
    (SupportLabel.CONTEXT_ONLY, "context_only", "相关背景", "context"),
    (SupportLabel.COUNTER, "counter", "相反或限制材料", "counter"),
)
_INSUFFICIENT_MESSAGE = "当前范围内没有足够的直接支撑材料，无法对该观点给出明确结论。"
_CLASSIFY_TASK = "classify_claim_support"
_DEFAULT_RRF_K = 60
_DEFAULT_LEXICAL_TOP_K = 100
_DEFAULT_VECTOR_TOP_K = 100
_AUTHORITATIVE_ERROR_CODES = frozenset(
    {
        "SQLITE_UNAVAILABLE",
        "RELEASE_MISMATCH",
        "INVALID_SCOPE",
        "CORPUS_NOT_FOUND",
        "EVIDENCE_NOT_AVAILABLE",
        "STORAGE_NOT_CONFIGURED",
    }
)


class ClaimReleaseProvider(Protocol):
    """Binds a release snapshot to the resolved scope before recall."""

    async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo: ...


class ClaimOverviewProvider(Protocol):
    """Must count distinct work/volume identifiers, never titles."""

    async def overview_for(self, evidence_ids: Sequence[str]) -> SearchOverview: ...


class ClaimPipeline:
    """SearchPipeline implementation that only accepts mode=claim."""

    def __init__(
        self,
        *,
        scope_resolver: ScopeResolver,
        lexical_index: LexicalIndex,
        vector_index: VectorIndex,
        embedding_provider: EmbeddingProvider,
        reranker: Reranker,
        language_model: LanguageModel,
        evidence_service: EvidenceService,
        evidence_repository: EvidenceRepository,
        release_provider: ClaimReleaseProvider,
        overview_provider: ClaimOverviewProvider,
        rank_constant: int = _DEFAULT_RRF_K,
        lexical_top_k: int = _DEFAULT_LEXICAL_TOP_K,
        vector_top_k: int = _DEFAULT_VECTOR_TOP_K,
    ) -> None:
        self._scope_resolver = scope_resolver
        self._lexical_index = lexical_index
        self._vector_index = vector_index
        self._embedding_provider = embedding_provider
        self._reranker = reranker
        self._language_model = language_model
        self._evidence_service = evidence_service
        self._evidence_repository = evidence_repository
        self._release_provider = release_provider
        self._overview_provider = overview_provider
        self._rank_constant = rank_constant
        self._lexical_top_k = lexical_top_k
        self._vector_top_k = vector_top_k

    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse:
        if request.mode is not SearchMode.CLAIM:
            raise DomainError(
                "INVALID_REQUEST",
                "ClaimPipeline only accepts mode=claim.",
                details={"mode": request.mode.value},
            )

        warnings: list[Warning] = []
        scope = await self._scope_resolver.resolve(request.scope)
        release = await _freeze_release(self._release_provider, scope)
        query = request.query
        lexical_hits, vector_hits = await self._recall(query, scope, warnings)
        fused = _fuse_candidates(lexical_hits, vector_hits, self._rank_constant)
        ranked = await self._rerank(query, fused, warnings)
        allowed_ids = tuple(candidate.evidence_id for candidate in ranked)
        labeled, classified = await self._classify(query, ranked, warnings)
        if classified:
            selected = _select_for_display(labeled, request.options.include_counter_evidence)
        else:
            selected = labeled
        hydration = await self._evidence_service.hydrate(
            selected,
            scope,
            allowed_evidence_ids=allowed_ids,
        )
        for exclusion in hydration.exclusions:
            warnings.append(
                Warning(
                    code=exclusion.reason.value,
                    message=f"Evidence {exclusion.evidence_id} was excluded by the evidence gate.",
                    stage="evidence_gate",
                )
            )

        surviving = {item.evidence_id: item for item in hydration.evidence}
        if classified:
            groups, ordered_evidence = _groups_from_evidence(selected, surviving)
        else:
            groups = []
            ordered_evidence = [
                surviving[candidate.evidence_id]
                for candidate in selected
                if candidate.evidence_id in surviving
            ]
        groups, ordered_evidence = _apply_page_size(groups, ordered_evidence, request.page_size)
        overview = await self._overview_provider.overview_for(
            [item.evidence_id for item in ordered_evidence]
        )
        direct_count = _count_label(ordered_evidence, SupportLabel.DIRECT)
        insufficiency = None
        if direct_count == 0:
            insufficiency = Insufficiency(
                code="INSUFFICIENT_SUPPORT",
                message=_INSUFFICIENT_MESSAGE,
                details={
                    "direct_count": 0,
                    "indirect_count": _count_label(ordered_evidence, SupportLabel.INDIRECT),
                    "counter_count": _count_label(ordered_evidence, SupportLabel.COUNTER),
                },
            )

        return SearchResponse(
            request_id=request_id,
            mode=SearchMode.CLAIM,
            query=query,
            scope_snapshot=scope,
            release=release,
            overview=overview,
            groups=groups,
            evidence=ordered_evidence,
            next_cursor=None,
            insufficiency=insufficiency,
            warnings=warnings,
            classification_notice=None,
        )

    async def _recall(
        self, query: str, scope: SearchScope, warnings: list[Warning]
    ) -> tuple[list[Candidate], list[Candidate]]:
        lexical_task = asyncio.create_task(
            self._lexical_index.search_lexical(query, scope, self._lexical_top_k)
        )
        vector_task = asyncio.create_task(self._vector_recall(query, scope))
        lexical_result, vector_result = await asyncio.gather(
            lexical_task, vector_task, return_exceptions=True
        )
        _raise_if_blocking(lexical_result)
        _raise_if_blocking(vector_result)
        lexical_hits, lexical_failed = _optional_channel(
            lexical_result, warnings, code="LEXICAL_UNAVAILABLE", stage="recall"
        )
        vector_hits, vector_failed = _optional_channel(
            vector_result, warnings, code="VECTOR_UNAVAILABLE", stage="recall"
        )
        if lexical_failed and vector_failed:
            raise DomainError(
                "VECTOR_INDEX_UNAVAILABLE",
                "Claim retrieval channels are unavailable.",
                details={"lexical": True, "vector": True},
                retryable=True,
            )
        return lexical_hits, vector_hits

    async def _vector_recall(self, query: str, scope: SearchScope) -> list[Candidate]:
        embeddings = await self._embedding_provider.embed([query])
        if not embeddings:
            return []
        return await self._vector_index.search_vector(embeddings[0], scope, self._vector_top_k)

    async def _rerank(
        self, query: str, fused: list[Candidate], warnings: list[Warning]
    ) -> list[Candidate]:
        if not fused:
            return []
        try:
            reranked = await self._reranker.rerank(query, fused)
        except asyncio.CancelledError:
            raise
        except DomainError as error:
            if error.code in _AUTHORITATIVE_ERROR_CODES:
                raise
            warnings.append(
                Warning(
                    code="RERANKER_UNAVAILABLE",
                    message="Reranker failed; returning reciprocal-rank fusion order.",
                    stage="rerank",
                )
            )
            return fused
        except Exception:
            warnings.append(
                Warning(
                    code="RERANKER_UNAVAILABLE",
                    message="Reranker failed; returning reciprocal-rank fusion order.",
                    stage="rerank",
                )
            )
            return fused
        return _restrict_rerank(fused, reranked, warnings)

    async def _classify(
        self, query: str, candidates: list[Candidate], warnings: list[Warning]
    ) -> tuple[list[Candidate], bool]:
        if not candidates:
            return [], True
        records = await _load_authority_records(
            self._evidence_repository,
            tuple(candidate.evidence_id for candidate in candidates),
        )
        classifiable = [candidate for candidate in candidates if candidate.evidence_id in records]
        if not classifiable:
            return candidates, False
        payload: dict[str, object] = {
            "query": query,
            "candidates": [
                {
                    "evidence_id": candidate.evidence_id,
                    "verified_text": records[candidate.evidence_id].verified_text,
                    "content_type": records[candidate.evidence_id].content_type,
                }
                for candidate in classifiable
            ],
        }
        try:
            raw = await self._language_model.generate_structured(_CLASSIFY_TASK, payload)
        except asyncio.CancelledError:
            raise
        except DomainError as error:
            if error.code in _AUTHORITATIVE_ERROR_CODES:
                raise
            warnings.append(_classifier_unavailable_warning())
            return candidates, False
        except Exception:
            warnings.append(_classifier_unavailable_warning())
            return candidates, False
        labels = _parse_classifications(
            raw, tuple(candidate.evidence_id for candidate in classifiable)
        )
        if labels is None:
            warnings.append(_classifier_unavailable_warning())
            return candidates, False
        return _apply_labels(candidates, labels), True


def _classifier_unavailable_warning() -> Warning:
    return Warning(
        code="CLASSIFIER_UNAVAILABLE",
        message="Support classifier failed; returning evidence without labels.",
        stage="classify",
    )


async def _freeze_release(provider: object, scope: SearchScope) -> ReleaseInfo:
    snapshot_for = getattr(provider, "snapshot_for", None)
    if callable(snapshot_for):
        snapshot = await snapshot_for(scope)
        if isinstance(snapshot, ReleaseInfo):
            return snapshot
        raise DomainError(
            "RELEASE_MISMATCH",
            "Claim release snapshot is not a ReleaseInfo object.",
        )
    current_release = getattr(provider, "current_release", None)
    if callable(current_release):
        snapshot = await current_release()
        if isinstance(snapshot, ReleaseInfo):
            return snapshot
        raise DomainError(
            "RELEASE_MISMATCH",
            "Claim release snapshot is not a ReleaseInfo object.",
        )
    raise DomainError(
        "STORAGE_NOT_CONFIGURED",
        "Claim release provider cannot freeze a scope-bound snapshot.",
    )


async def _load_authority_records(
    repository: EvidenceRepository, evidence_ids: tuple[str, ...]
) -> dict[str, AuthoritativeEvidenceRecord]:
    try:
        records = await repository.get_by_ids(evidence_ids)
    except asyncio.CancelledError:
        raise
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "SQLITE_UNAVAILABLE",
            "Authoritative evidence records are unavailable.",
            retryable=True,
        ) from exc
    return {
        evidence_id: records[evidence_id]
        for evidence_id in evidence_ids
        if evidence_id in records
    }


def _raise_if_blocking(result: object) -> None:
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, DomainError) and result.code in _AUTHORITATIVE_ERROR_CODES:
        raise result
    if isinstance(result, BaseException) and not isinstance(result, Exception):
        raise result


def _optional_channel(
    result: object, warnings: list[Warning], *, code: str, stage: str
) -> tuple[list[Candidate], bool]:
    if isinstance(result, Exception):
        warnings.append(
            Warning(
                code=code,
                message="A retrieval channel failed; continuing with remaining candidates.",
                stage=stage,
            )
        )
        return [], True
    if not isinstance(result, list):
        return [], False
    return [item for item in result if isinstance(item, Candidate)], False


def _fuse_candidates(
    lexical_hits: Sequence[Candidate],
    vector_hits: Sequence[Candidate],
    rank_constant: int,
) -> list[Candidate]:
    rankings = [
        [candidate.evidence_id for candidate in lexical_hits],
        [candidate.evidence_id for candidate in vector_hits],
    ]
    rankings = [ranking for ranking in rankings if ranking]
    if not rankings:
        return []
    scores = reciprocal_rank_fusion(rankings, rank_constant=rank_constant)
    merged = _merge_by_id(lexical_hits, vector_hits, scores)
    return [
        merged[evidence_id].model_copy(
            update={
                "fusion_score": scores[evidence_id],
                "rank_reasons": _unique(_extend(merged[evidence_id].rank_reasons, "rrf")),
            }
        )
        for evidence_id in stable_score_order(scores)
        if evidence_id in merged
    ]


def _merge_by_id(
    lexical_hits: Sequence[Candidate],
    vector_hits: Sequence[Candidate],
    scores: Mapping[str, float],
) -> dict[str, Candidate]:
    merged: dict[str, Candidate] = {}
    for rank, candidate in enumerate(lexical_hits, start=1):
        merged[candidate.evidence_id] = candidate.model_copy(
            update={
                "channels": _unique(_extend(candidate.channels, "lexical")),
                "lexical_rank": candidate.lexical_rank or rank,
                "fusion_score": scores[candidate.evidence_id],
            }
        )
    for rank, candidate in enumerate(vector_hits, start=1):
        existing = merged.get(candidate.evidence_id)
        if existing is None:
            merged[candidate.evidence_id] = candidate.model_copy(
                update={
                    "channels": _unique(_extend(candidate.channels, "vector")),
                    "vector_rank": candidate.vector_rank or rank,
                    "fusion_score": scores[candidate.evidence_id],
                }
            )
            continue
        merged[candidate.evidence_id] = existing.model_copy(
            update={
                "channels": _unique(_extend(existing.channels, *candidate.channels, "vector")),
                "retrieval_unit_ids": _unique(
                    _extend(existing.retrieval_unit_ids, *candidate.retrieval_unit_ids)
                ),
                "vector_rank": candidate.vector_rank or rank,
                "vector_score": candidate.vector_score,
                "text_hash": candidate.text_hash or existing.text_hash,
                "fusion_score": scores[candidate.evidence_id],
            }
        )
    return merged


def _restrict_rerank(
    original: Sequence[Candidate],
    reranked: Sequence[Candidate],
    warnings: list[Warning],
) -> list[Candidate]:
    pool = {candidate.evidence_id: candidate for candidate in original}
    ordered: list[Candidate] = []
    seen: set[str] = set()
    for item in reranked:
        if item.evidence_id not in pool:
            warnings.append(
                Warning(
                    code="MODEL_UNAUTHORIZED_ID",
                    message="Reranker returned an evidence_id outside the candidate pool.",
                    stage="rerank",
                )
            )
            continue
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        base = pool[item.evidence_id]
        ordered.append(
            base.model_copy(
                update={
                    "rerank_score": item.rerank_score,
                    "rank_reasons": _unique(
                        _extend(base.rank_reasons, *item.rank_reasons, "rerank")
                    ),
                }
            )
        )
    for candidate in original:
        if candidate.evidence_id not in seen:
            ordered.append(candidate)
    return ordered


def _parse_classifications(
    payload: Mapping[str, object], allowed_ids: tuple[str, ...]
) -> dict[str, SupportLabel] | None:
    raw_items = payload.get("classifications", payload.get("labels"))
    if not isinstance(raw_items, list):
        return None
    allowed = set(allowed_ids)
    labels: dict[str, SupportLabel] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            return None
        evidence_id = item.get("evidence_id")
        raw_label = item.get("support_label")
        if not isinstance(evidence_id, str) or not isinstance(raw_label, str):
            return None
        if evidence_id not in allowed:
            return None
        if evidence_id in labels:
            return None
        try:
            label = SupportLabel(raw_label)
        except ValueError:
            return None
        labels[evidence_id] = label
    if set(labels) != allowed:
        return None
    return labels


def _apply_labels(
    candidates: Sequence[Candidate], labels: Mapping[str, SupportLabel]
) -> list[Candidate]:
    labeled: list[Candidate] = []
    for candidate in candidates:
        assigned = labels.get(candidate.evidence_id)
        if assigned is None:
            labeled.append(candidate)
            continue
        labeled.append(candidate.model_copy(update={"support_label": assigned}))
    return labeled


def _select_for_display(
    candidates: Sequence[Candidate], include_counter_evidence: bool
) -> list[Candidate]:
    selected: list[Candidate] = []
    for candidate in sorted(candidates, key=_group_sort_key):
        label = candidate.support_label
        if label is SupportLabel.IRRELEVANT or label not in _HYDRATABLE_LABELS:
            continue
        if label is SupportLabel.COUNTER and not include_counter_evidence:
            continue
        selected.append(candidate)
    return selected


def _groups_from_evidence(
    selected: Sequence[Candidate],
    surviving: Mapping[str, Evidence],
) -> tuple[list[ResultGroup], list[Evidence]]:
    by_label: dict[SupportLabel, list[str]] = {label: [] for label, *_ in _GROUP_SPECS}
    for candidate in selected:
        label = candidate.support_label
        if label not in by_label:
            continue
        if candidate.evidence_id not in surviving:
            continue
        by_label[label].append(candidate.evidence_id)

    groups: list[ResultGroup] = []
    ordered: list[Evidence] = []
    for label, group_id, group_label, group_type in _GROUP_SPECS:
        evidence_ids = by_label[label]
        if not evidence_ids:
            continue
        groups.append(
            ResultGroup(
                group_id=group_id,
                label=group_label,
                group_type=group_type,
                evidence_ids=list(evidence_ids),
                summary=None,
            )
        )
        ordered.extend(surviving[evidence_id] for evidence_id in evidence_ids)
    return groups, ordered


def _apply_page_size(
    groups: list[ResultGroup],
    evidence: list[Evidence],
    page_size: int,
) -> tuple[list[ResultGroup], list[Evidence]]:
    paged = evidence[:page_size]
    allowed = {item.evidence_id for item in paged}
    trimmed: list[ResultGroup] = []
    for group in groups:
        evidence_ids = [item for item in group.evidence_ids if item in allowed]
        if not evidence_ids:
            continue
        trimmed.append(group.model_copy(update={"evidence_ids": evidence_ids}))
    return trimmed, paged


def _group_sort_key(candidate: Candidate) -> tuple[float, float, float, str]:
    return (
        -_present_score(candidate.rerank_score),
        -_present_score(candidate.fusion_score),
        -_present_score(candidate.vector_score),
        candidate.evidence_id,
    )


def _present_score(value: float | None) -> float:
    return float("-inf") if value is None else value


def _count_label(evidence: Sequence[Evidence], label: SupportLabel) -> int:
    return sum(1 for item in evidence if item.support_label is label)


def _extend(existing: Sequence[str], *values: str) -> list[str]:
    return [*existing, *values]


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
