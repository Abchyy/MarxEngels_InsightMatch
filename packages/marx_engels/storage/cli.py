"""Storage maintenance commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from marx_engels.settings import Settings
from marx_engels.storage.sqlite import SQLiteDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(prog="storage")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate")
    subparsers.add_parser("integrity-check")
    args = parser.parse_args()
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
