"""Ports that keep pipelines independent of storage implementations."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from marx_engels.contracts import Candidate, SearchRequest, SearchResponse, SearchScope
from marx_engels.retrieval_core.records import AuthoritativeEvidenceRecord


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


class EvidenceRepository(Protocol):
    """Batch reader for SQLite-authoritative passage records.

    Implementations must not return public Evidence and must not read or
    return LanceDB ``search_text``. Missing IDs are omitted from the mapping.
    """

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> Mapping[str, AuthoritativeEvidenceRecord]: ...


class SearchPipeline(Protocol):
    async def execute(self, request: SearchRequest, request_id: str) -> SearchResponse: ...
