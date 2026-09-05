"""Local adapters that implement the provider-neutral Retriever port."""

from __future__ import annotations

from marx_engels.contracts import Candidate, SearchScope
from marx_engels.retrieval_core import ExactSearchIndex


class ExactSearchRetriever:
    """Wraps ExactSearchIndex so future cloud retrievers share one call shape.

    Candidates never carry search_text. Final quotations stay in EvidenceService.
    """

    def __init__(self, index: ExactSearchIndex) -> None:
        self._index = index

    async def retrieve(self, query: str, scope: SearchScope, limit: int) -> list[Candidate]:
        return await self._index.search_exact(query, scope, limit)
