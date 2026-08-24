"""Ports that keep pipelines independent of storage implementations."""

from collections.abc import Sequence
from typing import Protocol

from marx_engels.contracts import Candidate, Evidence, SearchRequest, SearchResponse, SearchScope


class ScopeResolver(Protocol):
    async def resolve(self, scope: SearchScope) -> SearchScope: ...


class ExactSearchIndex(Protocol):
    async def search_exact(self, query: str, scope: SearchScope, limit: int) -> list[Candidate]: ...


class LexicalIndex(Protocol):
    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]: ...


class VectorIndex(Protocol):
    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]: ...


class EvidenceHydrator(Protocol):
    async def hydrate(
        self, candidates: Sequence[Candidate], scope: SearchScope
    ) -> list[Evidence]: ...


class SearchPipeline(Protocol):
    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse: ...
