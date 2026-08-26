from pathlib import Path

from tests.helpers import build_result_zip, write_pdf

from marx_engels.corpus_registry.ids import expected_filename
from marx_engels.ingestion.cancel import CancellationToken
from marx_engels.ingestion.config import CorpusSettings
from marx_engels.ingestion.models import ExtractOptions, ProviderTask, RunMode
from marx_engels.ingestion.pipeline import ExtractionPipeline
from marx_engels.ingestion.providers.errors import PermanentProviderError


class StaleThenFreshProvider:
    name = "fake"
    version = "1.0.0"

    def __init__(self, archive: bytes) -> None:
        self.archive = archive
        self.submitted: list[str] = []
        self._submits = 0

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
        self._submits += 1
        cancel.raise_if_cancelled()
        assert file_path.is_file()
        if self._submits == 1:
            return "stale-batch"
        return "fresh-batch"

    def poll_batch(
        self, batch_id: str, *, data_id: str, cancel: CancellationToken, deadline_monotonic: float
    ) -> ProviderTask:
        if batch_id == "stale-batch":
            raise PermanentProviderError("parsing failed, please try again later")
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


def _ten_volumes(root: Path) -> None:
    for number in range(1, 11):
        write_pdf(
            root / expected_filename(number), [f"v{number} p{page}" for page in range(1, 31)]
        )


def test_resume_resubmits_failed_chunk_instead_of_polling_stale_batch(tmp_path: Path) -> None:
    assets = tmp_path / "pdf"
    data = tmp_path / "corpus"
    assets.mkdir()
    _ten_volumes(assets)
    settings = CorpusSettings(pdf_asset_root=assets, corpus_data_root=data)
    provider = StaleThenFreshProvider(build_result_zip(markdown="# raw retry\n"))
    pipeline = ExtractionPipeline(
        settings, provider, monotonic=lambda: 0.0, sleeper=lambda _delay: None
    )

    first = pipeline.extract(RunMode.PILOT, max_wait_seconds=30)
    assert first.chunks[0].status.value == "failed"
    assert first.chunks[0].batch_id == "stale-batch"
    assert provider.submitted == [first.chunks[0].data_id]

    second = pipeline.extract(RunMode.PILOT, max_wait_seconds=30, resume_run_id=first.run_id)
    assert second.chunks[0].status.value == "completed"
    assert second.chunks[0].batch_id == "fresh-batch"
    assert provider.submitted == [first.chunks[0].data_id, second.chunks[0].data_id]
    result_dir = pipeline.layout.result_dir(second.run_id, 1, second.chunks[0].chunk_id)
    assert (result_dir / "full.md").read_text(encoding="utf-8").startswith("# raw retry")
