"""Small, explicit SQLite connection and migration boundary."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

MIGRATION_PATTERN = re.compile(r"^(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.sql$")


class SQLiteDatabase:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    def connect(self, *, create_parent: bool = False) -> sqlite3.Connection:
        if create_parent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        return connection

    def migrate(self, migrations_dir: Path) -> list[int]:
        migrations = list(_discover_migrations(migrations_dir))
        applied_now: list[int] = []
        with self.connect(create_parent=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migration (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migration")
            }
            for version, name, path in migrations:
                if version in applied:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO schema_migration(version, name, applied_at)
                    VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    """,
                    (version, name),
                )
                connection.commit()
                applied_now.append(version)
        return applied_now

    def healthcheck(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with self.connect() as connection:
                value = connection.execute("SELECT 1").fetchone()
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
                return bool(value and value[0] == 1 and foreign_keys and foreign_keys[0] == 1)
        except sqlite3.Error:
            return False

    def integrity_check(self) -> str:
        with self.connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            return str(row[0]) if row else "no result"


def _discover_migrations(directory: Path) -> Iterable[tuple[int, str, Path]]:
    discovered: list[tuple[int, str, Path]] = []
    for path in directory.glob("*.sql"):
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            raise ValueError(f"invalid migration filename: {path.name}")
        discovered.append((int(match["version"]), match["name"], path))
    versions = [item[0] for item in discovered]
    if len(versions) != len(set(versions)):
        raise ValueError("duplicate migration version")
    return sorted(discovered)
