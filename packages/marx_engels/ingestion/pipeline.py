"""Orchestrate inventory, preflight, split, provider extract, and resume."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from marx_engels.corpus_registry.ids import (
    CORPUS_ID,
    EDITION_ID,
    EXPECTED_VOLUME_COUNT,
    source_record_id,
    source_uri,
    volume_id,
)
from marx_engels.corpus_registry.inventory import InventoryError, discover_volumes, register_sources
from marx_engels.corpus_registry.models import InventoryIssue, SourceRecord, SourceStatus
from marx_engels.ingestion.atomic import atomic_write_json, atomic_write_yaml
from marx_engels.ingestion.cancel import CancellationToken, ExtractionCancelled
from marx_engels.ingestion.config import CorpusSettings
from marx_engels.ingestion.constants import (
    ALL_MAX_WAIT_SECONDS,
    CHUNK_POLL_DEADLINE_SECONDS,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL_VERSION,
    PILOT_MAX_WAIT_SECONDS,
    PILOT_PAGE_COUNT,
    PILOT_START_PAGE,
    PROVIDER_CONCURRENCY,
    SPLIT_MAX_PAGES,
)
from marx_engels.ingestion.fingerprint import extraction_fingerprint
from marx_engels.ingestion.hashing import sha256_file
from marx_engels.ingestion.mapping import assert_complete_coverage
from marx_engels.ingestion.models import (
    ChunkStatus,
    ExtractionChunk,
    ExtractionRun,
    ExtractOptions,
    PageRangeMapping,
    RunMode,
    RunStatus,
    TextLayer,
)
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.ports import ExtractionProvider
from marx_engels.ingestion.preflight import (
    PdfPreflightError,
    PreflightReport,
    preflight_volume,
    report_to_dict,
)
from marx_engels.ingestion.providers.errors import (
    AuthenticationError,
    PollTimeoutError,
    ProviderError,
    QuotaExceededError,
)
from marx_engels.ingestion.results import extract_and_register
from marx_engels.ingestion.secrets import redact_secrets
from marx_engels.ingestion.splitting import (
    MaterializedChunk,
    materialize_chunks,
    materialize_page_window,
)
from marx_engels.ingestion.state import (
    load_pipeline_state,
    mark_chunk,
    save_pipeline_state,
    upsert_run,
    utcnow,
)

LOGGER = logging.getLogger(__name__)


class PipelineStop(Exception):
    def __init__(self, message: str, *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex}"


def write_source_record(layout: CorpusLayout, record: SourceRecord) -> None:
    atomic_write_yaml(
        layout.source_record_path(record.volume_id), json.loads(record.model_dump_json())
    )


def load_source_records(layout: CorpusLayout) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    if not layout.source_records.exists():
        return records
    for path in sorted(layout.source_records.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        records.append(SourceRecord.model_validate(payload))
    return records


def resolve_source_pdf(asset_root: Path, file_name: str) -> Path:
    path = asset_root / file_name
    if not path.is_file():
        raise FileNotFoundError(f"source PDF {file_name} is not under the configured asset root")
    return path


def inventory_volumes(settings: CorpusSettings) -> list[SourceRecord]:
    layout = CorpusLayout(settings.corpus_data_root)
    layout.ensure()
    records = register_sources(settings.pdf_asset_root)
    for record in records:
        write_source_record(layout, record)
    state = load_pipeline_state(layout)
    state["volumes"] = {
        str(record.volume_number): {
            "volume_id": record.volume_id,
            "file_name": record.file_name,
            "sha256": record.sha256,
            "file_size_bytes": record.file_size_bytes,
            "status": record.status.value,
        }
        for record in records
    }
    save_pipeline_state(layout, state)
    return records


def preflight_all(settings: CorpusSettings) -> list[PreflightReport]:
    layout = CorpusLayout(settings.corpus_data_root)
    layout.ensure()
    discovered, issues = discover_volumes(settings.pdf_asset_root)
    if issues:
        raise InventoryError(issues)
    reports: list[PreflightReport] = []
    records: list[SourceRecord] = []
    registered_at = utcnow()
    for item in discovered:
        try:
            report = preflight_volume(
                volume_number=item.volume_number,
                path=item.path,
                file_name=item.file_name,
                file_size_bytes=item.file_size_bytes,
                sha256=item.sha256,
            )
        except PdfPreflightError as exc:
            raise InventoryError(
                [
                    InventoryIssue(
                        code="preflight_failed",
                        message=str(exc),
                        file_name=item.file_name,
                        volume_number=item.volume_number,
                    )
                ]
            ) from exc
        reports.append(report)
        status = SourceStatus.SPLIT_REQUIRED if report.requires_split else SourceStatus.READY
        record = SourceRecord(
            source_record_id=source_record_id(volume_id(item.volume_number), item.sha256),
            corpus_id=CORPUS_ID,
            edition_id=EDITION_ID,
            volume_id=volume_id(item.volume_number),
            volume_number=item.volume_number,
            file_name=item.file_name,
            source_uri=source_uri(item.volume_number),
            file_size_bytes=item.file_size_bytes,
            sha256=item.sha256,
            pdf_page_count=report.page_count,
            registered_at=registered_at,
            status=status,
        )
        write_source_record(layout, record)
        records.append(record)
    atomic_write_json(
        layout.preflight_report_path(),
        {
            "generated_at": utcnow().isoformat(),
            "corpus_id": CORPUS_ID,
            "volume_count": len(reports),
            "raw_layer_only": True,
            "volumes": [report_to_dict(report) for report in reports],
        },
    )
    state = load_pipeline_state(layout)
    state["volumes"] = {
        str(record.volume_number): {
            "volume_id": record.volume_id,
            "file_name": record.file_name,
            "sha256": record.sha256,
            "file_size_bytes": record.file_size_bytes,
            "pdf_page_count": record.pdf_page_count,
            "status": record.status.value,
            "needs_ocr": next(
                report.needs_ocr
                for report in reports
                if report.volume_number == record.volume_number
            ),
        }
        for record in records
    }
    save_pipeline_state(layout, state)
    return reports


def pilot_window(
    page_count: int, *, start: int = PILOT_START_PAGE, count: int = PILOT_PAGE_COUNT
) -> tuple[int, int]:
    if page_count <= count:
        return 1, page_count
    if start + count - 1 <= page_count:
        return start, start + count - 1
    return page_count - count + 1, page_count


def default_options(*, is_ocr: bool) -> ExtractOptions:
    return ExtractOptions(
        model_version=DEFAULT_MODEL_VERSION,
        language=DEFAULT_LANGUAGE,
        enable_table=True,
        enable_formula=True,
        is_ocr=is_ocr,
    )


class ExtractionPipeline:
    def __init__(
        self,
        settings: CorpusSettings,
        provider: ExtractionProvider,
        *,
        sleeper: Any = None,
        monotonic: Any = None,
        concurrency: int = PROVIDER_CONCURRENCY,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.layout = CorpusLayout(settings.corpus_data_root)
        self.layout.ensure()
        self._lock = threading.Lock()
        self._sleeper = sleeper or __import__("time").sleep
        self._monotonic = monotonic or __import__("time").monotonic
        self.concurrency = min(2, max(1, concurrency))

    def extract(
        self,
        mode: RunMode,
        *,
        cancel: CancellationToken | None = None,
        max_wait_seconds: float | None = None,
        resume_run_id: str | None = None,
    ) -> ExtractionRun:
        token = cancel or CancellationToken()
        reports = preflight_all(self.settings)
        report_by_volume = {report.volume_number: report for report in reports}
        state = load_pipeline_state(self.layout)
        run = self._prepare_run(state, mode, report_by_volume, resume_run_id=resume_run_id)
        run.status = RunStatus.RUNNING
        self._save_run(run)
        wait = max_wait_seconds
        if wait is None:
            wait = PILOT_MAX_WAIT_SECONDS if mode is RunMode.PILOT else ALL_MAX_WAIT_SECONDS
        deadline = self._monotonic() + wait
        try:
            self._run_chunks(run, report_by_volume, token, deadline)
        except ExtractionCancelled:
            run.status = RunStatus.CANCELLED
            self._save_run(run)
            raise
        except PipelineStop as exc:
            run.status = RunStatus.PAUSED if exc.exit_code in {3, 4} else RunStatus.FAILED
            self._save_run(run)
            raise
        except (AuthenticationError, QuotaExceededError, PollTimeoutError) as exc:
            run.status = (
                RunStatus.PAUSED
                if isinstance(exc, PollTimeoutError | QuotaExceededError)
                else RunStatus.FAILED
            )
            self._save_run(run)
            raise
        if run.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            if all(
                chunk.status in {ChunkStatus.COMPLETED, ChunkStatus.SKIPPED} for chunk in run.chunks
            ):
                run.status = RunStatus.COMPLETED
            elif any(chunk.status == ChunkStatus.FAILED for chunk in run.chunks):
                run.status = RunStatus.FAILED
            else:
                run.status = RunStatus.PAUSED
        self._save_run(run)
        self._write_extraction_report(run)
        return run

    def _prepare_run(
        self,
        state: dict[str, Any],
        mode: RunMode,
        reports: dict[int, PreflightReport],
        *,
        resume_run_id: str | None,
    ) -> ExtractionRun:
        if resume_run_id:
            payload = state.get("runs", {}).get(resume_run_id)
            if not payload:
                raise PipelineStop(f"run {resume_run_id} was not found in state")
            return ExtractionRun.model_validate(payload)
        if mode is RunMode.ALL:
            active = state.get("active_run_id")
            if active:
                payload = state.get("runs", {}).get(active)
                if payload:
                    existing = ExtractionRun.model_validate(payload)
                    if existing.mode is RunMode.ALL and existing.status in {
                        RunStatus.RUNNING,
                        RunStatus.PAUSED,
                        RunStatus.CREATED,
                        RunStatus.FAILED,
                    }:
                        stale_plan = any(
                            chunk.chunk_page_count > SPLIT_MAX_PAGES for chunk in existing.chunks
                        )
                        if not stale_plan:
                            return existing
        chunks = self._materialize_for_mode(mode, reports)
        now = utcnow()
        return ExtractionRun(
            run_id=new_run_id(),
            mode=mode,
            status=RunStatus.CREATED,
            created_at=now,
            updated_at=now,
            provider=self.provider.name,
            provider_version=self.provider.version,
            options=default_options(is_ocr=any(report.needs_ocr for report in reports.values())),
            chunks=chunks,
        )

    def _materialize_for_mode(
        self, mode: RunMode, reports: dict[int, PreflightReport]
    ) -> list[ExtractionChunk]:
        discovered, issues = discover_volumes(self.settings.pdf_asset_root)
        if issues:
            raise InventoryError(issues)
        by_volume = {item.volume_number: item for item in discovered}
        chunks: list[ExtractionChunk] = []
        if mode is RunMode.PILOT:
            item = by_volume[1]
            report = reports[1]
            start, end = pilot_window(report.page_count)
            materialized = materialize_page_window(
                item.path,
                volume_number=1,
                source_sha256=item.sha256,
                start_page=start,
                end_page=end,
                output_dir=self.layout.volume_chunk_dir(1),
            )
            self._write_mapping(materialized.mapping)
            chunks.append(self._chunk_from_materialized(materialized, report.needs_ocr))
            return chunks
        for volume_number in range(1, EXPECTED_VOLUME_COUNT + 1):
            item = by_volume[volume_number]
            report = reports[volume_number]
            materialized_list = materialize_chunks(
                item.path,
                volume_number=volume_number,
                source_sha256=item.sha256,
                page_count=report.page_count,
                output_dir=self.layout.volume_chunk_dir(volume_number),
            )
            mappings = [item.mapping for item in materialized_list]
            assert_complete_coverage(report.page_count, mappings)
            for materialized in materialized_list:
                self._write_mapping(materialized.mapping)
                chunks.append(self._chunk_from_materialized(materialized, report.needs_ocr))
        return chunks

    def _chunk_from_materialized(
        self, materialized: MaterializedChunk, needs_ocr: bool
    ) -> ExtractionChunk:
        mapping = materialized.mapping
        options = default_options(is_ocr=needs_ocr)
        fingerprint = extraction_fingerprint(
            source_sha256=mapping.source_sha256,
            chunk_sha256=mapping.chunk_sha256,
            provider=self.provider.name,
            provider_version=self.provider.version,
            options=options,
        )
        return ExtractionChunk(
            chunk_id=mapping.chunk_id,
            volume_number=mapping.volume_number,
            source_sha256=mapping.source_sha256,
            chunk_sha256=mapping.chunk_sha256,
            original_start_page=mapping.original_start_page,
            original_end_page=mapping.original_end_page,
            chunk_page_count=mapping.chunk_page_count,
            offset=mapping.offset,
            file_name=materialized.path.name,
            status=ChunkStatus.MATERIALIZED,
            fingerprint=fingerprint,
            data_id=mapping.chunk_id,
        )

    def _run_chunks(
        self,
        run: ExtractionRun,
        reports: dict[int, PreflightReport],
        cancel: CancellationToken,
        deadline: float,
    ) -> None:
        pending = [
            chunk
            for chunk in run.chunks
            if chunk.status not in {ChunkStatus.COMPLETED, ChunkStatus.SKIPPED}
        ]
        if not pending:
            return
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [
                pool.submit(
                    self._process_chunk, run, chunk, reports[chunk.volume_number], cancel, deadline
                )
                for chunk in pending
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except ExtractionCancelled:
                    cancel.cancel()
                    raise
                except (AuthenticationError, QuotaExceededError) as exc:
                    cancel.cancel()
                    code = 2 if isinstance(exc, AuthenticationError) else 3
                    raise PipelineStop(str(exc), exit_code=code) from exc
                except PollTimeoutError as exc:
                    cancel.cancel()
                    raise PipelineStop(str(exc), exit_code=4) from exc
                except ProviderError as exc:
                    LOGGER.error("provider error: %s", redact_secrets(str(exc)))

    def _process_chunk(
        self,
        run: ExtractionRun,
        chunk: ExtractionChunk,
        report: PreflightReport,
        cancel: CancellationToken,
        deadline: float,
    ) -> None:
        try:
            cancel.raise_if_cancelled()
            if self._monotonic() >= deadline:
                raise PollTimeoutError("overall extract wait limit reached")
            if (
                chunk.fingerprint
                and self._fingerprint_completed(chunk.fingerprint)
                and chunk.status != ChunkStatus.POLLING
            ):
                self._update_chunk(
                    run, chunk.chunk_id, ChunkStatus.SKIPPED, error="duplicate fingerprint"
                )
                return
            pdf_path = self.layout.volume_chunk_dir(chunk.volume_number) / chunk.file_name
            options = default_options(is_ocr=report.needs_ocr)
            if chunk.status == ChunkStatus.FAILED:
                LOGGER.info("re-submitting failed chunk %s", chunk.chunk_id)
                chunk.batch_id = None
                self._update_chunk(
                    run, chunk.chunk_id, ChunkStatus.MATERIALIZED, batch_id=None, error=None
                )
            if not chunk.batch_id:
                self._update_chunk(run, chunk.chunk_id, ChunkStatus.UPLOADING)
                request_path = self.layout.mineru_requests / run.run_id / f"{chunk.chunk_id}.json"
                atomic_write_json(
                    request_path,
                    {
                        "chunk_id": chunk.chunk_id,
                        "file_name": chunk.file_name,
                        "data_id": chunk.data_id,
                        "options": json.loads(options.model_dump_json()),
                        "provider": self.provider.name,
                        "provider_version": self.provider.version,
                    },
                )
                batch_id = self.provider.submit_file(
                    pdf_path,
                    data_id=chunk.data_id or chunk.chunk_id,
                    file_name=chunk.file_name,
                    options=options,
                    cancel=cancel,
                )
                self._update_chunk(run, chunk.chunk_id, ChunkStatus.POLLING, batch_id=batch_id)
                chunk.batch_id = batch_id
            else:
                self._update_chunk(run, chunk.chunk_id, ChunkStatus.POLLING)
            poll_deadline = min(deadline, self._monotonic() + CHUNK_POLL_DEADLINE_SECONDS)
            task = self.provider.poll_batch(
                chunk.batch_id or "",
                data_id=chunk.data_id or chunk.chunk_id,
                cancel=cancel,
                deadline_monotonic=poll_deadline,
            )
            self._update_chunk(run, chunk.chunk_id, ChunkStatus.DOWNLOADING)
            archive = self.layout.archive_path(run.run_id, chunk.chunk_id)
            if not task.full_zip_url:
                raise ProviderError("missing full_zip_url")
            self.provider.download_archive(task.full_zip_url, archive, cancel=cancel)
            result_dir = self.layout.result_dir(run.run_id, chunk.volume_number, chunk.chunk_id)
            artifacts = extract_and_register(archive, result_dir)
            mapping = PageRangeMapping(
                chunk_id=chunk.chunk_id,
                volume_number=chunk.volume_number,
                source_sha256=chunk.source_sha256,
                chunk_sha256=chunk.chunk_sha256 or "",
                original_start_page=chunk.original_start_page,
                original_end_page=chunk.original_end_page,
                chunk_page_count=chunk.chunk_page_count,
                offset=chunk.offset,
            )
            self._write_mapping(mapping)
            atomic_write_json(
                result_dir / "page_mapping.json",
                json.loads(mapping.model_dump_json()),
            )
            atomic_write_json(
                result_dir / "artifacts.json",
                {
                    "layer": TextLayer.RAW.value,
                    "note": "Raw MinerU output; not verified quotation text.",
                    "archive_sha256": sha256_file(archive),
                    "artifacts": [json.loads(item.model_dump_json()) for item in artifacts],
                },
            )
            self._remember_fingerprint(chunk.fingerprint, run.run_id, chunk.chunk_id)
            self._update_chunk(run, chunk.chunk_id, ChunkStatus.COMPLETED, error=None)
            LOGGER.info("stored %s raw artifacts for %s", len(artifacts), chunk.chunk_id)
        except (AuthenticationError, QuotaExceededError, PollTimeoutError, ExtractionCancelled):
            raise
        except ProviderError as exc:
            self._update_chunk(
                run, chunk.chunk_id, ChunkStatus.FAILED, error=redact_secrets(str(exc))
            )
            raise

    def _fingerprint_completed(self, fingerprint: str) -> bool:
        state = load_pipeline_state(self.layout)
        record = state.get("fingerprints", {}).get(fingerprint)
        if not record:
            return False
        run_id = record.get("run_id")
        chunk_id = record.get("chunk_id")
        if not run_id or not chunk_id:
            return False
        archive = self.layout.archive_path(str(run_id), str(chunk_id))
        return archive.is_file()

    def _remember_fingerprint(self, fingerprint: str | None, run_id: str, chunk_id: str) -> None:
        if not fingerprint:
            return
        with self._lock:
            state = load_pipeline_state(self.layout)
            state.setdefault("fingerprints", {})
            state["fingerprints"][fingerprint] = {"run_id": run_id, "chunk_id": chunk_id}
            save_pipeline_state(self.layout, state)

    def _update_chunk(
        self, run: ExtractionRun, chunk_id: str, status: ChunkStatus, **updates: object
    ) -> None:
        with self._lock:
            mark_chunk(run, chunk_id, status, **updates)
            state = load_pipeline_state(self.layout)
            upsert_run(state, run)
            save_pipeline_state(self.layout, state)

    def _save_run(self, run: ExtractionRun) -> None:
        with self._lock:
            run.updated_at = utcnow()
            state = load_pipeline_state(self.layout)
            upsert_run(state, run)
            save_pipeline_state(self.layout, state)

    def _write_mapping(self, mapping: PageRangeMapping) -> None:
        directory = self.layout.volume_chunk_dir(mapping.volume_number)
        atomic_write_json(
            directory / f"{mapping.chunk_id}.mapping.json", json.loads(mapping.model_dump_json())
        )

    def _write_extraction_report(self, run: ExtractionRun) -> None:
        payload = {
            "run_id": run.run_id,
            "mode": run.mode.value,
            "status": run.status.value,
            "provider": run.provider,
            "provider_version": run.provider_version,
            "raw_layer_only": True,
            "note": run.notes,
            "chunks": [json.loads(chunk.model_dump_json()) for chunk in run.chunks],
        }
        atomic_write_json(self.layout.extraction_report_path(run.run_id), payload)


def status_payload(settings: CorpusSettings) -> dict[str, Any]:
    layout = CorpusLayout(settings.corpus_data_root)
    state = load_pipeline_state(layout)
    return {
        "corpus_id": CORPUS_ID,
        "volumes": state.get("volumes", {}),
        "active_run_id": state.get("active_run_id"),
        "runs": {
            run_id: {
                "mode": payload.get("mode"),
                "status": payload.get("status"),
                "chunks": [
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "volume_number": chunk.get("volume_number"),
                        "status": chunk.get("status"),
                        "pages": (
                            f"{chunk.get('original_start_page')}-{chunk.get('original_end_page')}"
                        ),
                    }
                    for chunk in payload.get("chunks", [])
                ],
            }
            for run_id, payload in state.get("runs", {}).items()
        },
    }


def format_status(payload: dict[str, Any]) -> str:
    lines = [f"corpus: {payload.get('corpus_id')}", f"active_run: {payload.get('active_run_id')}"]
    volumes = payload.get("volumes") or {}
    for key in sorted(volumes, key=lambda item: int(item)):
        volume = volumes[key]
        lines.append(
            f"volume {key}: {volume.get('file_name')} status={volume.get('status')} "
            f"pages={volume.get('pdf_page_count')} sha256={str(volume.get('sha256', ''))[:12]}"
        )
    runs = payload.get("runs") or {}
    for run_id, run in runs.items():
        lines.append(f"run {run_id}: mode={run.get('mode')} status={run.get('status')}")
        for chunk in run.get("chunks", []):
            lines.append(
                f"  {chunk.get('chunk_id')} vol={chunk.get('volume_number')} "
                f"pages={chunk.get('pages')} status={chunk.get('status')}"
            )
    return "\n".join(lines)
