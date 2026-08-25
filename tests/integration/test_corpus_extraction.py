from pathlib import Path

import pytest
from tests.helpers import build_result_zip, write_pdf

from marx_engels.corpus_registry.ids import expected_filename
from marx_engels.ingestion.cancel import CancellationToken
from marx_engels.ingestion.config import CorpusSettings
from marx_engels.ingestion.mapping import (
    PageMappingError,
    assert_complete_coverage,
    mapping_from_range,
)
from marx_engels.ingestion.models import ExtractOptions, ProviderTask, RunMode
from marx_engels.ingestion.pipeline import ExtractionPipeline


class FakeProvider:
    name = "fake"
    version = "1.0.0"

    def __init__(self, archive: bytes) -> None:
        self.archive = archive
        self.submitted: list[str] = []

    def submit_file(
        self,
        file_path: Path,
        *,
        data_id: str,
        file_name: str,
        options: ExtractOptions,
        cancel: CancellationToken,
    ) -> str:
        self.submitted.append(data_id)
        cancel.raise_if_cancelled()
        assert file_path.is_file()
        assert file_name.endswith(".pdf")
        return f"batch-{data_id}"

    def poll_batch(
        self, batch_id: str, *, data_id: str, cancel: CancellationToken, deadline_monotonic: float
    ) -> ProviderTask:
        return ProviderTask(
            batch_id=batch_id,
            data_id=data_id,
            file_name=f"{data_id}.pdf",
            state="done",
            full_zip_url="https://example.test/result.zip",
        )

    def download_archive(self, url: str, dest: Path, *, cancel: CancellationToken) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.archive)
        return dest


def test_mapping_offset_and_coverage() -> None:
    first = mapping_from_range(
        chunk_id="a",
        volume_number=1,
        source_sha256="a" * 64,
        chunk_sha256="b" * 64,
        start_page=1,
        end_page=4,
    )
    second = mapping_from_range(
        chunk_id="b",
        volume_number=1,
        source_sha256="a" * 64,
        chunk_sha256="c" * 64,
        start_page=5,
        end_page=6,
    )
    assert_complete_coverage(6, [first, second])
    with pytest.raises(PageMappingError):
        assert_complete_coverage(7, [first, second])


@pytest.mark.integration
def test_pilot_extract_with_fake_provider(tmp_path: Path) -> None:
    assets = tmp_path / "pdf"
    data = tmp_path / "corpus"
    assets.mkdir()
    for number in range(1, 11):
        write_pdf(
            assets / expected_filename(number), [f"v{number} p{page}" for page in range(1, 31)]
        )
    settings = CorpusSettings(pdf_asset_root=assets, corpus_data_root=data)
    provider = FakeProvider(build_result_zip(markdown="# raw volume 1\n"))
    pipeline = ExtractionPipeline(
        settings, provider, monotonic=lambda: 0.0, sleeper=lambda _delay: None
    )
    run = pipeline.extract(RunMode.PILOT, max_wait_seconds=30)
    assert run.status.value == "completed"
    assert len(run.chunks) == 1
    chunk = run.chunks[0]
    assert chunk.original_start_page == 21
    assert chunk.original_end_page == 30
    result_dir = pipeline.layout.result_dir(run.run_id, 1, chunk.chunk_id)
    assert (result_dir / "full.md").read_text(encoding="utf-8").startswith("# raw")
    assert (result_dir / "page_mapping.json").is_file()
    assert (result_dir / "artifacts.json").is_file()
    assert provider.submitted

    second = pipeline.extract(RunMode.PILOT, max_wait_seconds=30)
    assert second.chunks[0].status.value in {"skipped", "completed"}
