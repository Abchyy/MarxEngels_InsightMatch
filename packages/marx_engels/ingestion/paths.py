"""External CORPUS_DATA_ROOT layout. Derived data never writes to PDF_ASSET_ROOT."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CorpusLayout:
    root: Path

    @property
    def source_records(self) -> Path:
        return self.root / "source_records"

    @property
    def raw_chunks(self) -> Path:
        return self.root / "raw" / "chunks"

    @property
    def mineru_requests(self) -> Path:
        return self.root / "raw" / "mineru" / "requests"

    @property
    def mineru_results(self) -> Path:
        return self.root / "raw" / "mineru" / "results"

    @property
    def mineru_archives(self) -> Path:
        return self.root / "raw" / "mineru" / "archives"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def raw_pages(self) -> Path:
        return self.root / "raw" / "pages"

    @property
    def clean_pages(self) -> Path:
        return self.root / "clean" / "pages"

    @property
    def clean_transformations(self) -> Path:
        return self.root / "clean" / "transformations"

    @property
    def clean_structures(self) -> Path:
        return self.root / "clean" / "structures"

    @property
    def clean_passages(self) -> Path:
        return self.root / "clean" / "passages"

    @property
    def review_issues(self) -> Path:
        return self.root / "review" / "issues"

    @property
    def publication_reports(self) -> Path:
        return self.root / "reports" / "publication"

    def ensure(self) -> None:
        for path in (
            self.source_records,
            self.raw_chunks,
            self.mineru_requests,
            self.mineru_results,
            self.mineru_archives,
            self.raw_pages,
            self.clean_pages,
            self.clean_transformations,
            self.clean_structures,
            self.clean_passages,
            self.reports,
            self.state,
            self.review_issues,
            self.publication_reports,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def volume_chunk_dir(self, volume_number: int) -> Path:
        return self.raw_chunks / f"v{volume_number:02d}"

    def archive_path(self, run_id: str, chunk_id: str) -> Path:
        return self.mineru_archives / run_id / f"{chunk_id}.zip"

    def result_dir(self, run_id: str, volume_number: int, chunk_id: str) -> Path:
        return self.mineru_results / run_id / f"v{volume_number:02d}" / chunk_id

    def source_record_path(self, volume_id: str) -> Path:
        return self.source_records / f"{volume_id}.yaml"

    def preflight_report_path(self) -> Path:
        return self.reports / "preflight.json"

    def extraction_report_path(self, run_id: str) -> Path:
        return self.reports / "extraction" / f"{run_id}.json"

    def pipeline_state_path(self) -> Path:
        return self.state / "pipeline.json"

    def id_registry_path(self) -> Path:
        return self.state / "id_registry.json"

    def merge_dir(self, merge_run_id: str) -> Path:
        return self.raw_pages / merge_run_id

    def clean_page_dir(self, clean_run_id: str) -> Path:
        return self.clean_pages / clean_run_id

    def transformation_dir(self, clean_run_id: str) -> Path:
        return self.clean_transformations / clean_run_id

    def structure_dir(self, assemble_run_id: str) -> Path:
        return self.clean_structures / assemble_run_id

    def passage_dir(self, assemble_run_id: str) -> Path:
        return self.clean_passages / assemble_run_id

    def cleaning_report_path(self, clean_run_id: str) -> Path:
        return self.reports / "cleaning" / f"{clean_run_id}.json"

    def structure_report_path(self, assemble_run_id: str) -> Path:
        return self.reports / "structure" / f"{assemble_run_id}.json"

    def review_issue_path(self, assemble_run_id: str) -> Path:
        return self.review_issues / f"{assemble_run_id}.jsonl"

    def publication_report_path(self, data_version: str) -> Path:
        return self.publication_reports / f"{data_version}.json"

    def volume_page_file(self, root: Path, volume_id: str, pdf_page: int) -> Path:
        return root / volume_id / f"page_{pdf_page:04d}.json"
