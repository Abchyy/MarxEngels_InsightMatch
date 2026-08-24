"""Hierarchical SearchScope validation against published SQLite objects."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence

from marx_engels.contracts import SearchScope
from marx_engels.errors import DomainError
from marx_engels.storage.sqlite import SQLiteDatabase
from marx_engels.storage.sqlite_runtime import in_clause, run_exclusive_or_unavailable

_PUBLISHED = "published"


class SQLiteScopeResolver:
    """ScopeResolver adapter. Invalid hierarchy fails closed; it never becomes empty."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    async def resolve(self, scope: SearchScope) -> SearchScope:
        await asyncio.to_thread(_validate_scope, self._database, scope)
        return scope


def _validate_scope(database: SQLiteDatabase, scope: SearchScope) -> None:
    def operation(connection: sqlite3.Connection) -> None:
        _validate_corpora(connection, scope.corpus_ids)
        _validate_editions(connection, scope)
        _validate_volumes(connection, scope)
        _validate_works(connection, scope)

    run_exclusive_or_unavailable(database, operation)


def _validate_corpora(connection: sqlite3.Connection, corpus_ids: Sequence[str]) -> None:
    clause, params = in_clause("corpus_id", corpus_ids, "corpus_id")
    rows = connection.execute(
        f"SELECT corpus_id, release_status FROM corpus WHERE {clause}",
        params,
    ).fetchall()
    by_id = {str(row["corpus_id"]): str(row["release_status"]) for row in rows}
    missing = [corpus_id for corpus_id in corpus_ids if corpus_id not in by_id]
    unpublished = [
        corpus_id for corpus_id, status in by_id.items() if status != _PUBLISHED
    ]
    if missing or unpublished:
        raise DomainError(
            "CORPUS_NOT_FOUND",
            "Corpus is not available in the current published release.",
            details={"missing_corpus_ids": missing, "unpublished_corpus_ids": unpublished},
        )


def _validate_editions(connection: sqlite3.Connection, scope: SearchScope) -> None:
    if not scope.edition_ids:
        return
    clause, params = in_clause("edition_id", scope.edition_ids, "edition_id")
    rows = connection.execute(
        f"SELECT edition_id, corpus_id, release_status FROM edition WHERE {clause}",
        params,
    ).fetchall()
    by_id = {str(row["edition_id"]): row for row in rows}
    _require_all_ids(scope.edition_ids, by_id, "edition")
    allowed_corpora = set(scope.corpus_ids)
    for edition_id in scope.edition_ids:
        row = by_id[edition_id]
        if str(row["release_status"]) != _PUBLISHED:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected edition is not published.",
                details={"edition_id": edition_id},
            )
        if str(row["corpus_id"]) not in allowed_corpora:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected edition does not belong to the requested corpus.",
                details={"edition_id": edition_id, "corpus_id": str(row["corpus_id"])},
            )


def _validate_volumes(connection: sqlite3.Connection, scope: SearchScope) -> None:
    if not scope.volume_ids:
        return
    clause, params = in_clause("v.volume_id", scope.volume_ids, "volume_id")
    rows = connection.execute(
        f"""
        SELECT
            v.volume_id AS volume_id,
            v.edition_id AS edition_id,
            v.release_status AS release_status,
            e.corpus_id AS corpus_id,
            e.release_status AS edition_release_status
        FROM volume AS v
        JOIN edition AS e ON e.edition_id = v.edition_id
        WHERE {clause}
        """,
        params,
    ).fetchall()
    by_id = {str(row["volume_id"]): row for row in rows}
    _require_all_ids(scope.volume_ids, by_id, "volume")
    allowed_editions = set(scope.edition_ids)
    allowed_corpora = set(scope.corpus_ids)
    for volume_id in scope.volume_ids:
        row = by_id[volume_id]
        if str(row["release_status"]) != _PUBLISHED:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected volume is not published.",
                details={"volume_id": volume_id},
            )
        if str(row["edition_release_status"]) != _PUBLISHED:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected volume belongs to an unpublished edition.",
                details={"volume_id": volume_id, "edition_id": str(row["edition_id"])},
            )
        if allowed_editions and str(row["edition_id"]) not in allowed_editions:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected volume does not belong to the requested edition.",
                details={"volume_id": volume_id, "edition_id": str(row["edition_id"])},
            )
        if str(row["corpus_id"]) not in allowed_corpora:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected volume does not belong to the requested corpus.",
                details={"volume_id": volume_id, "corpus_id": str(row["corpus_id"])},
            )


def _validate_works(connection: sqlite3.Connection, scope: SearchScope) -> None:
    if not scope.work_ids:
        return
    clause, params = in_clause("w.work_id", scope.work_ids, "work_id")
    rows = connection.execute(
        f"""
        SELECT
            w.work_id AS work_id,
            w.volume_id AS volume_id,
            w.release_status AS release_status,
            v.edition_id AS edition_id,
            v.release_status AS volume_release_status,
            e.corpus_id AS corpus_id,
            e.release_status AS edition_release_status
        FROM work AS w
        JOIN volume AS v ON v.volume_id = w.volume_id
        JOIN edition AS e ON e.edition_id = v.edition_id
        WHERE {clause}
        """,
        params,
    ).fetchall()
    by_id = {str(row["work_id"]): row for row in rows}
    _require_all_ids(scope.work_ids, by_id, "work")
    allowed_volumes = set(scope.volume_ids)
    allowed_editions = set(scope.edition_ids)
    allowed_corpora = set(scope.corpus_ids)
    for work_id in scope.work_ids:
        row = by_id[work_id]
        if str(row["release_status"]) != _PUBLISHED:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected work is not published.",
                details={"work_id": work_id},
            )
        if str(row["volume_release_status"]) != _PUBLISHED:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected work belongs to an unpublished volume.",
                details={"work_id": work_id, "volume_id": str(row["volume_id"])},
            )
        if str(row["edition_release_status"]) != _PUBLISHED:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected work belongs to an unpublished edition.",
                details={"work_id": work_id, "edition_id": str(row["edition_id"])},
            )
        if allowed_volumes and str(row["volume_id"]) not in allowed_volumes:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected work does not belong to the requested volume.",
                details={"work_id": work_id, "volume_id": str(row["volume_id"])},
            )
        if allowed_editions and str(row["edition_id"]) not in allowed_editions:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected work does not belong to the requested edition.",
                details={"work_id": work_id, "edition_id": str(row["edition_id"])},
            )
        if str(row["corpus_id"]) not in allowed_corpora:
            raise DomainError(
                "INVALID_SCOPE",
                "Selected work does not belong to the requested corpus.",
                details={"work_id": work_id, "corpus_id": str(row["corpus_id"])},
            )


def _require_all_ids(
    requested: Sequence[str], found: dict[str, sqlite3.Row], node_type: str
) -> None:
    missing = [identifier for identifier in requested if identifier not in found]
    if missing:
        raise DomainError(
            "INVALID_SCOPE",
            f"Selected {node_type} does not exist.",
            details={"missing_ids": missing, "node_type": node_type},
        )
