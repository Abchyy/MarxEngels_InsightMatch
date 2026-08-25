"""Provider-agnostic extraction port. MinerU is an adapter, not the generic workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from marx_engels.corpus_registry import CorpusManifest
from marx_engels.ingestion.cancel import CancellationToken
from marx_engels.ingestion.models import ExtractOptions, ProviderTask


class CorpusVerifier(Protocol):
    def verify(self, manifest: CorpusManifest, corpus_root: Path) -> list[str]: ...


class CorpusPublisher(Protocol):
    def publish(self, manifest: CorpusManifest, corpus_root: Path) -> str: ...


class ExtractionProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def submit_file(
        self,
        file_path: Path,
        *,
        data_id: str,
        file_name: str,
        options: ExtractOptions,
        cancel: CancellationToken,
    ) -> str: ...

    def poll_batch(
        self,
        batch_id: str,
        *,
        data_id: str,
        cancel: CancellationToken,
        deadline_monotonic: float,
    ) -> ProviderTask: ...

    def download_archive(
        self,
        url: str,
        dest: Path,
        *,
        cancel: CancellationToken,
    ) -> Path: ...
