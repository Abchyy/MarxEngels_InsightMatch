"""Corpus command slots owned by the corpus-pipeline worktree."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from marx_engels.corpus_registry.inventory import InventoryError
from marx_engels.ingestion.assemble import assemble_corpus
from marx_engels.ingestion.cancel import CancellationToken, ExtractionCancelled
from marx_engels.ingestion.cleaning import clean_merged_pages
from marx_engels.ingestion.config import CorpusSettings
from marx_engels.ingestion.models import RunMode
from marx_engels.ingestion.page_merge import merge_raw_pages
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.pipeline import (
    ExtractionPipeline,
    PipelineStop,
    format_status,
    inventory_volumes,
    preflight_all,
    status_payload,
)
from marx_engels.ingestion.preflight import report_to_dict
from marx_engels.ingestion.providers.errors import AuthenticationError
from marx_engels.ingestion.providers.mineru import MinerUClient
from marx_engels.ingestion.secrets import redact_secrets
from marx_engels.ingestion.sqlite_ingest import ingest_sqlite
from marx_engels.ingestion.verify import verify_corpus
from marx_engels.settings import Settings
from marx_engels.storage.sqlite import SQLiteDatabase


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _settings_from_args(args: argparse.Namespace) -> CorpusSettings:
    settings = CorpusSettings()
    updates: dict[str, Path] = {}
    if getattr(args, "asset_root", None):
        updates["pdf_asset_root"] = args.asset_root
    if getattr(args, "data_root", None):
        updates["corpus_data_root"] = args.data_root
    if updates:
        settings = settings.model_copy(update=updates)
    return settings


def _add_root_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--asset-root", type=Path, help="Override PDF_ASSET_ROOT")
    parser.add_argument("--data-root", type=Path, help="Override CORPUS_DATA_ROOT")


def build_provider(settings: CorpusSettings) -> MinerUClient:
    if not settings.token_configured() or settings.mineru_api_token is None:
        raise AuthenticationError("MINERU_API_TOKEN is missing")
    return MinerUClient(settings.mineru_api_token, base_url=settings.mineru_base_url)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-corpus")
    verify.add_argument("--manifest", type=Path)
    _add_root_flags(verify)

    inventory = subparsers.add_parser(
        "inventory", help="Register local volumes without calling MinerU"
    )
    _add_root_flags(inventory)

    preflight = subparsers.add_parser(
        "preflight", help="Inspect local PDFs and write reports without calling MinerU"
    )
    _add_root_flags(preflight)

    extract = subparsers.add_parser("extract", help="Run MinerU raw extraction")
    extract_mode = extract.add_mutually_exclusive_group(required=True)
    extract_mode.add_argument(
        "--pilot", action="store_true", help="Extract a small derived page window from volume 1"
    )
    extract_mode.add_argument(
        "--all", action="store_true", dest="extract_all", help="Extract all ten volumes"
    )
    extract.add_argument("--max-wait-seconds", type=float, default=None)
    _add_root_flags(extract)

    resume = subparsers.add_parser(
        "resume", help="Continue an unfinished batch without re-uploading completed chunks"
    )
    resume.add_argument("--run-id", dest="run_id")
    resume.add_argument("--max-wait-seconds", type=float, default=None)
    _add_root_flags(resume)

    status = subparsers.add_parser(
        "status", help="Show per-volume and per-chunk status without secrets"
    )
    _add_root_flags(status)

    merge = subparsers.add_parser(
        "merge-pages", help="Rebuild unique PDF pages from a completed ALL MinerU run"
    )
    merge.add_argument("--run-id", dest="run_id")
    _add_root_flags(merge)

    clean = subparsers.add_parser("clean-pages", help="Write Clean pages from merged Raw pages")
    clean.add_argument("--merge-run-id")
    _add_root_flags(clean)

    assemble = subparsers.add_parser(
        "assemble",
        help="Merge, clean, and structure a completed ALL run without calling MinerU",
    )
    assemble.add_argument("--run-id", dest="run_id")
    assemble.add_argument("--rules-dir", type=Path)
    _add_root_flags(assemble)

    ingest = subparsers.add_parser(
        "ingest-sqlite",
        help="Write Clean Unverified/Draft snapshot to local SQLite for display and search",
    )
    ingest.add_argument("--assemble-run-id")
    ingest.add_argument("--sqlite", type=Path)
    ingest.add_argument("--manifest", type=Path)
    ingest.add_argument("--replace", action="store_true")
    _add_root_flags(ingest)
    return parser


def _run_extract(
    settings: CorpusSettings, mode: RunMode, *, resume_run_id: str | None, max_wait: float | None
) -> int:
    try:
        provider = build_provider(settings)
    except AuthenticationError:
        print("需要在 .env 中更新 MINERU_API_TOKEN", file=sys.stderr)
        return 2
    pipeline = ExtractionPipeline(settings, provider)
    cancel = CancellationToken()
    try:
        run = pipeline.extract(
            mode, cancel=cancel, max_wait_seconds=max_wait, resume_run_id=resume_run_id
        )
    except ExtractionCancelled:
        print("Extraction cancelled; progress was saved.")
        return 130
    except PipelineStop as exc:
        print(redact_secrets(str(exc)))
        print("Progress was saved under CORPUS_DATA_ROOT/state.")
        if exc.exit_code == 2:
            print("需要在 .env 中更新 MINERU_API_TOKEN")
        return exc.exit_code
    except AuthenticationError:
        print("需要在 .env 中更新 MINERU_API_TOKEN", file=sys.stderr)
        return 2
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    print(f"run {run.run_id} status={run.status.value} mode={run.mode.value}")
    for chunk in run.chunks:
        print(
            f"  {chunk.chunk_id} vol={chunk.volume_number} "
            f"{chunk.original_start_page}-{chunk.original_end_page} {chunk.status.value}"
        )
    return 0 if run.status.value in {"completed", "paused"} else 1


def main(argv: Sequence[str] | None = None) -> int:
    _configure_logging()
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "verify-corpus":
        settings = _settings_from_args(args)
        code, message = verify_corpus(args.manifest, settings)
        print(message)
        return code
    settings = _settings_from_args(args)
    try:
        if args.command == "inventory":
            records = inventory_volumes(settings)
            for record in records:
                print(
                    f"v{record.volume_number:02d} {record.file_name} "
                    f"{record.file_size_bytes} {record.sha256}"
                )
            return 0
        if args.command == "preflight":
            reports = preflight_all(settings)
            for report in reports:
                payload = report_to_dict(report)
                print(
                    f"v{report.volume_number:02d} pages={payload['page_count']} "
                    f"size={payload['file_size_bytes']} ocr={payload['needs_ocr']} "
                    f"split={payload['requires_split']} sha256={payload['sha256'][:12]}"
                )
            print(f"report: {settings.corpus_data_root / 'reports' / 'preflight.json'}")
            return 0
        if args.command == "extract":
            mode = RunMode.PILOT if args.pilot else RunMode.ALL
            return _run_extract(settings, mode, resume_run_id=None, max_wait=args.max_wait_seconds)
        if args.command == "resume":
            return _run_extract(
                settings,
                RunMode.ALL,
                resume_run_id=args.run_id,
                max_wait=args.max_wait_seconds,
            )
        if args.command == "status":
            print(format_status(status_payload(settings)))
            return 0
        if args.command == "merge-pages":
            manifest = merge_raw_pages(
                CorpusLayout(settings.corpus_data_root), extraction_run_id=args.run_id
            )
            print(f"merge {manifest['merge_run_id']} pages={manifest['recovered_pages']}")
            return 0
        if args.command == "clean-pages":
            layout = CorpusLayout(settings.corpus_data_root)
            merge_id = args.merge_run_id
            if not merge_id:
                latest = layout.raw_pages / "latest.json"
                merge_id = json.loads(latest.read_text(encoding="utf-8"))["merge_run_id"]
            clean_report = clean_merged_pages(layout, str(merge_id))
            print(
                f"clean {clean_report['clean_run_id']} pages={clean_report['pages']} "
                f"transforms={clean_report['transformations']}"
            )
            return 0
        if args.command == "assemble":
            assemble_report = assemble_corpus(
                CorpusLayout(settings.corpus_data_root),
                extraction_run_id=args.run_id,
                rules_dir=args.rules_dir,
            )
            print(
                f"assemble {assemble_report['assemble_run_id']} "
                f"pages={assemble_report['clean_pages']} "
                f"works={assemble_report['works']} "
                f"passages={assemble_report['passages']} "
                f"issues={assemble_report['review_issues']}"
            )
            return 0
        if args.command == "ingest-sqlite":
            sqlite_path = args.sqlite or Settings().sqlite_database_path
            ingest_report = ingest_sqlite(
                CorpusLayout(settings.corpus_data_root),
                SQLiteDatabase(sqlite_path),
                assemble_run_id=args.assemble_run_id,
                manifest_path=args.manifest,
                replace=args.replace,
            )
            print(
                f"ingest-sqlite {ingest_report['data_version']} "
                f"passages={ingest_report['passages_ingested']} "
                f"unverified={ingest_report['passages_unverified']} "
                f"fts={ingest_report['local_fts_rows']} "
                f"outbox={ingest_report['index_outbox']}"
            )
            return 0
    except InventoryError as exc:
        for issue in exc.issues:
            print(issue.message, file=sys.stderr)
        return 1
    except Exception as exc:
        print(redact_secrets(str(exc)), file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
