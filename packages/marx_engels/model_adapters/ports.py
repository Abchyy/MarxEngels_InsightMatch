"""Provider-neutral model boundaries."""

from collections.abc import Sequence
from typing import Protocol

from marx_engels.contracts import Candidate


class EmbeddingProvider(Protocol):
    @property
    def model_version(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    @property
    def model_version(self) -> str: ...

    async def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]: ...


class LanguageModel(Protocol):
    @property
    def model_version(self) -> str: ...

    async def generate_structured(
        self, task: str, payload: dict[str, object]
    ) -> dict[str, object]: ...
