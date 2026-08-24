"""Independent exact-search pipeline. Does not share control flow with other modes."""

from __future__ import annotations

from typing import Protocol

from marx_engels.contracts import (
    Evidence,
    Insufficiency,
    ReleaseInfo,
    SearchMode,
    SearchOverview,
    SearchRequest,
    SearchResponse,
    SearchScope,
)
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceService, ExactMatchQuery
from marx_engels.retrieval_core import (
    AuthoritativeEvidenceRecord,
    ExactSearchIndex,
    ScopeResolver,
)

_NO_EXACT_MATCH = Insufficiency(
    code="NO_EXACT_MATCH",
    message="在当前范围内未发现该词语的逐字命中。",
)


class ExactReleaseResolver(Protocol):
    async def resolve_exact(self, scope: SearchScope) -> ReleaseInfo: ...


class ExactPipeline:
    def __init__(
        self,
        *,
        scope_resolver: ScopeResolver,
        exact_index: ExactSearchIndex,
        evidence_service: EvidenceService,
        release_resolver: ExactReleaseResolver,
    ) -> None:
        self._scope_resolver = scope_resolver
        self._exact_index = exact_index
        self._evidence_service = evidence_service
        self._release_resolver = release_resolver

    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse:
        if request.mode is not SearchMode.EXACT:
            raise DomainError(
                "INVALID_REQUEST",
                "ExactPipeline only accepts exact mode.",
                details={"mode": request.mode.value},
            )

        scope_snapshot = await self._scope_resolver.resolve(request.scope)
        release = await self._release_resolver.resolve_exact(scope_snapshot)
        match_query = request.query.strip()
        candidates = await self._exact_index.search_exact(
            match_query, scope_snapshot, request.page_size
        )
        hydration = await self._evidence_service.hydrate(
            candidates,
            scope_snapshot,
            exact_query=ExactMatchQuery(query=match_query),
        )
        evidence = list(hydration.evidence)
        records = list(hydration.accepted_records)
        if request.sort == "document_order":
            evidence, records = _sort_document_order(evidence, records)

        overview = SearchOverview(
            evidence_count=len(evidence),
            work_count=len({record.work_id for record in records}),
            volume_count=len({record.volume_id for record in records}),
        )
        return SearchResponse(
            request_id=request_id,
            mode=SearchMode.EXACT,
            query=request.query,
            scope_snapshot=scope_snapshot,
            release=release,
            overview=overview,
            groups=[],
            evidence=evidence,
            next_cursor=None,
            insufficiency=None if evidence else _NO_EXACT_MATCH,
            warnings=[],
        )


def _sort_document_order(
    evidence: list[Evidence], records: list[AuthoritativeEvidenceRecord]
) -> tuple[list[Evidence], list[AuthoritativeEvidenceRecord]]:
    paired = sorted(
        zip(evidence, records, strict=True),
        key=lambda item: _document_order_key(item[1]),
    )
    if not paired:
        return [], []
    sorted_evidence, sorted_records = zip(*paired, strict=True)
    return list(sorted_evidence), list(sorted_records)


def _document_order_key(
    record: AuthoritativeEvidenceRecord,
) -> tuple[int, int, str, str]:
    first_label = record.printed_pages[0] if record.printed_pages else ""
    try:
        page_number = int(first_label)
    except ValueError:
        page_number = 10**9
    return (record.volume_no, page_number, first_label, record.evidence_id)
