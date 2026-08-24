import sqlite3
from pathlib import Path

import pytest

from marx_engels.storage import SQLiteDatabase


@pytest.mark.integration
def test_initial_migration_creates_core_schema(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    database = SQLiteDatabase(tmp_path / "corpus.db")
    assert database.migrate(root / "migrations") == [1]
    assert database.migrate(root / "migrations") == []
    assert database.integrity_check() == "ok"

    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        assert {"corpus", "passage", "data_release", "index_release", "passage_fts"} <= tables
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.integration
def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    database = SQLiteDatabase(tmp_path / "corpus.db")
    database.migrate(root / "migrations")
    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO edition(
                edition_id, corpus_id, rights_status, release_status, created_at, updated_at
            ) VALUES ('edition', 'missing', 'approved', 'draft', 'now', 'now')
            """
        )
