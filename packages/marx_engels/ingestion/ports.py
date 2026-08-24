"""Stable hand-off between corpus processing and publication."""

from pathlib import Path
from typing import Protocol

from marx_engels.corpus_registry import CorpusManifest


class CorpusVerifier(Protocol):
    def verify(self, manifest: CorpusManifest, corpus_root: Path) -> list[str]: ...


class CorpusPublisher(Protocol):
    def publish(self, manifest: CorpusManifest, corpus_root: Path) -> str: ...
