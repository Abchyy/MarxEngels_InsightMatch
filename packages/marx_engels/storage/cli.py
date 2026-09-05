"""Storage maintenance commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marx_engels.errors import DomainError
from marx_engels.settings import Settings
from marx_engels.storage.cloud_export import export_cloud_ingest
from marx_engels.storage.local_publish import init_local_corpus, verify_local_sqlite_asset
from marx_engels.storage.sqlite import SQLiteDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storage")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    subparsers.add_parser("integrity-check")
    init = subparsers.add_parser(
        "init-local-corpus",
        help="Copy Canonical seed to a Git-ignored runtime DB and publish it",
    )
    init.add_argument("--seed", type=Path)
    init.add_argument("--runtime", type=Path)
    init.add_argument("--manifest", type=Path)
    init.add_argument("--sha256", type=Path)
    init.add_argument("--replace", action="store_true")
    verify = subparsers.add_parser(
        "verify-local-asset",
        help="Fail closed unless the Canonical seed hash, integrity, and counts match",
    )
    verify.add_argument("--seed", type=Path)
    verify.add_argument("--manifest", type=Path)
    verify.add_argument("--sha256", type=Path)
    export = subparsers.add_parser(
        "export-cloud-ingest",
        help="Write deterministic retrieval-unit files for a later cloud upload (does not upload)",
    )
    export.add_argument("--seed", type=Path)
    export.add_argument("--output", type=Path)
    export.add_argument("--manifest", type=Path)
    export.add_argument("--sha256", type=Path)
    args = parser.parse_args(argv)

    if args.command == "init-local-corpus":
        try:
            report = init_local_corpus(
                seed_path=args.seed,
                runtime_path=args.runtime,
                manifest_path=args.manifest,
                sha256_path=args.sha256,
                replace=args.replace,
            )
        except DomainError as exc:
            print(f"{exc.code}: {exc.message}")
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "verify-local-asset":
        code, message = verify_local_sqlite_asset(
            seed_path=args.seed, manifest_path=args.manifest, sha256_path=args.sha256
        )
        print(message)
        return code
    if args.command == "export-cloud-ingest":
        try:
            report = export_cloud_ingest(
                seed_path=args.seed,
                output_root=args.output,
                manifest_path=args.manifest,
                sha256_path=args.sha256,
            )
        except DomainError as exc:
            print(f"{exc.code}: {exc.message}")
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    settings = Settings()
    database = SQLiteDatabase(
        settings.sqlite_database_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    if args.command == "migrate":
        applied = database.migrate(PROJECT_ROOT / "migrations")
        print(f"Applied migrations: {applied or 'none'}")
        return 0
    result = database.integrity_check()
    print(result)
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
