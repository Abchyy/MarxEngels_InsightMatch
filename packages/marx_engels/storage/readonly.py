"""Read-only SQLite connections that never create or write the Canonical seed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from marx_engels.corpus_registry.local_asset import assert_no_unhashed_wal
from marx_engels.errors import DomainError
from marx_engels.storage.sqlite_runtime import SQLITE_UNAVAILABLE_MESSAGE


def connect_readonly(path: Path, *, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    if not path.is_file():
        raise DomainError(
            "SQLITE_UNAVAILABLE",
            SQLITE_UNAVAILABLE_MESSAGE,
            details={"path": str(path)},
            retryable=True,
        )
    assert_no_unhashed_wal(path)
    # corpus.sha256 covers only this file; immutable skips WAL and does not create -wal/-shm.
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return connection
