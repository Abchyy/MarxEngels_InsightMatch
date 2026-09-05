"""Configured data/index release binding against published SQLite rows."""

from __future__ import annotations

import asyncio
import sqlite3

from marx_engels.contracts import ReleaseInfo, SearchScope
from marx_engels.corpus_registry.local_asset import load_release_sidecar
from marx_engels.errors import DomainError
from marx_engels.settings import Settings
from marx_engels.storage.sqlite import SQLiteDatabase
from marx_engels.storage.sqlite_runtime import run_exclusive_or_unavailable

_PUBLISHED = "published"


class SQLiteReleaseResolver:
    """Fail-closed release snapshot for Exact. Never invents version identifiers."""

    def __init__(self, database: SQLiteDatabase, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    async def resolve_exact(self, scope: SearchScope) -> ReleaseInfo:
        data_version = _configured_version(self._settings.active_data_version)
        if data_version is None:
            sidecar = load_release_sidecar(self._database.path)
            if sidecar is None or not sidecar.init_complete:
                raise DomainError(
                    "STORAGE_NOT_CONFIGURED",
                    "Active data version is not configured and local corpus init is incomplete. "
                    "Run `make init-local-corpus` or set ACTIVE_DATA_VERSION.",
                    details={"setting": "active_data_version"},
                )
            data_version = sidecar.data_version
        index_version = _configured_version(self._settings.active_index_version)
        return await asyncio.to_thread(
            _load_exact_release,
            self._database,
            data_version,
            index_version,
            tuple(scope.corpus_ids),
        )


def _configured_version(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _load_exact_release(
    database: SQLiteDatabase,
    data_version: str,
    index_version: str | None,
    corpus_ids: tuple[str, ...],
) -> ReleaseInfo:
    def operation(connection: sqlite3.Connection) -> ReleaseInfo:
        data_row = connection.execute(
            """
            SELECT data_version, corpus_id, status, published_at
            FROM data_release
            WHERE data_version = ?
            """,
            (data_version,),
        ).fetchone()
        if data_row is None or str(data_row["status"]) != _PUBLISHED:
            raise DomainError(
                "RELEASE_MISMATCH",
                "Configured data release is missing or not published.",
                details={"data_version": data_version},
            )
        release_corpus_id = str(data_row["corpus_id"])
        requested = set(corpus_ids)
        if requested != {release_corpus_id}:
            raise DomainError(
                "RELEASE_MISMATCH",
                "Configured data release does not cover the requested corpus scope.",
                details={
                    "data_version": data_version,
                    "release_corpus_id": release_corpus_id,
                    "requested_corpus_ids": list(corpus_ids),
                },
            )
        embedding_model: str | None = None
        if index_version is not None:
            index_row = connection.execute(
                """
                SELECT index_version, data_version, status, embedding_model
                FROM index_release
                WHERE index_version = ?
                """,
                (index_version,),
            ).fetchone()
            if (
                index_row is None
                or str(index_row["status"]) != _PUBLISHED
                or str(index_row["data_version"]) != data_version
            ):
                raise DomainError(
                    "RELEASE_MISMATCH",
                    "Configured index release is missing, unpublished, or not bound.",
                    details={
                        "data_version": data_version,
                        "index_version": index_version,
                    },
                )
            embedding_model = str(index_row["embedding_model"])
        published_at = data_row["published_at"]
        return ReleaseInfo(
            data_version=str(data_row["data_version"]),
            index_version=index_version,
            embedding_model=embedding_model,
            released_at=None if published_at is None else str(published_at),
        )

    return run_exclusive_or_unavailable(database, operation)
