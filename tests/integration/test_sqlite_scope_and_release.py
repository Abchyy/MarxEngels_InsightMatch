from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from marx_engels.contracts import SearchScope
from marx_engels.errors import DomainError
from marx_engels.settings import Settings
from marx_engels.storage import SQLiteDatabase, SQLiteReleaseResolver, SQLiteScopeResolver
from tests.synthetic_corpus.builder import build_synthetic_corpus

pytestmark = pytest.mark.integration

MAIN_SCOPE = SearchScope(corpus_ids=["synthetic_mecw_test"])
DECOY_SCOPE = SearchScope(corpus_ids=["synthetic_scope_decoy"])


def _resolver(tmp_path: Path) -> tuple[SQLiteScopeResolver, Path]:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    return SQLiteScopeResolver(build.database), build.database.path


def test_valid_scope_returns_stable_snapshot(tmp_path: Path) -> None:
    resolver, _path = _resolver(tmp_path)
    scope = SearchScope(
        corpus_ids=["synthetic_mecw_test"],
        edition_ids=["synthetic_edition_v1"],
        volume_ids=["syn_v01"],
        work_ids=["syn_work_early"],
    )
    snapshot = asyncio.run(resolver.resolve(scope))
    assert snapshot is scope
    assert snapshot.corpus_ids == ["synthetic_mecw_test"]
    assert snapshot.work_ids == ["syn_work_early"]


def test_invalid_hierarchy_fails_closed(tmp_path: Path) -> None:
    resolver, _path = _resolver(tmp_path)
    scope = SearchScope(
        corpus_ids=["synthetic_mecw_test"],
        volume_ids=["syn_v01"],
        work_ids=["syn_work_late"],
    )
    with pytest.raises(DomainError) as error:
        asyncio.run(resolver.resolve(scope))
    assert error.value.code == "INVALID_SCOPE"


def test_unknown_corpus_is_not_an_empty_result(tmp_path: Path) -> None:
    resolver, _path = _resolver(tmp_path)
    scope = SearchScope(corpus_ids=["does_not_exist"])
    with pytest.raises(DomainError) as error:
        asyncio.run(resolver.resolve(scope))
    assert error.value.code == "CORPUS_NOT_FOUND"


def test_release_requires_configured_published_data_version(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    missing = SQLiteReleaseResolver(
        build.database, Settings(sqlite_database_path=build.database.path)
    )
    with pytest.raises(DomainError) as error:
        asyncio.run(missing.resolve_exact(MAIN_SCOPE))
    assert error.value.code == "STORAGE_NOT_CONFIGURED"

    published = SQLiteReleaseResolver(
        build.database,
        Settings(
            sqlite_database_path=build.database.path,
            active_data_version="data_synthetic_v1",
        ),
    )
    release = asyncio.run(published.resolve_exact(MAIN_SCOPE))
    assert release.data_version == "data_synthetic_v1"
    assert release.index_version is None
    assert release.released_at == "2026-08-24T00:00:00Z"

    mismatched = SQLiteReleaseResolver(
        build.database,
        Settings(
            sqlite_database_path=build.database.path,
            active_data_version="data_synthetic_v1",
            active_index_version="idx_synthetic_decoy_v1",
        ),
    )
    with pytest.raises(DomainError) as index_error:
        asyncio.run(mismatched.resolve_exact(MAIN_SCOPE))
    assert index_error.value.code == "RELEASE_MISMATCH"


def test_missing_sqlite_file_is_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "missing.db"
    resolver = SQLiteReleaseResolver(
        SQLiteDatabase(database_path),
        Settings(sqlite_database_path=database_path, active_data_version="data_synthetic_v1"),
    )
    with pytest.raises(DomainError) as error:
        asyncio.run(resolver.resolve_exact(MAIN_SCOPE))
    assert error.value.code == "SQLITE_UNAVAILABLE"


def test_decoy_scope_does_not_use_main_data_release(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    resolver = SQLiteReleaseResolver(
        build.database,
        Settings(
            sqlite_database_path=build.database.path,
            active_data_version="data_synthetic_v1",
        ),
    )
    with pytest.raises(DomainError) as error:
        asyncio.run(resolver.resolve_exact(DECOY_SCOPE))
    assert error.value.code == "RELEASE_MISMATCH"
    assert error.value.details["data_version"] == "data_synthetic_v1"
    assert error.value.details["release_corpus_id"] == "synthetic_mecw_test"

    multi = SearchScope(corpus_ids=["synthetic_mecw_test", "synthetic_scope_decoy"])
    with pytest.raises(DomainError) as multi_error:
        asyncio.run(resolver.resolve_exact(multi))
    assert multi_error.value.code == "RELEASE_MISMATCH"
