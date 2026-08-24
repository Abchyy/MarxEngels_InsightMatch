"""Shared blocking-SQLite helpers for authoritative adapters."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence

from marx_engels.errors import DomainError
from marx_engels.storage.sqlite import SQLiteDatabase

SQLITE_UNAVAILABLE_MESSAGE = "The authoritative SQLite store is unavailable."


def require_existing_database(database: SQLiteDatabase) -> None:
    if not database.path.exists():
        raise DomainError(
            "SQLITE_UNAVAILABLE",
            SQLITE_UNAVAILABLE_MESSAGE,
            details={"path": str(database.path)},
            retryable=True,
        )


def run_exclusive_or_unavailable[T](
    database: SQLiteDatabase, operation: Callable[[sqlite3.Connection], T]
) -> T:
    require_existing_database(database)
    try:
        return database.run_exclusive(operation)
    except sqlite3.Error as exc:
        raise DomainError(
            "SQLITE_UNAVAILABLE",
            SQLITE_UNAVAILABLE_MESSAGE,
            details={"sqlite_error": type(exc).__name__},
            retryable=True,
        ) from exc


def in_clause(column: str, values: Sequence[str], prefix: str) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {}
    placeholders: list[str] = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        params[key] = value
        placeholders.append(f":{key}")
    return f"{column} IN ({', '.join(placeholders)})", params
