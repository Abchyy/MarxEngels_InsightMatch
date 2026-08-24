"""Index build and publication ports."""

from typing import Protocol


class IndexBuilder(Protocol):
    async def build(self, data_version: str) -> str: ...


class IndexVerifier(Protocol):
    async def verify(self, data_version: str, index_version: str) -> list[str]: ...
