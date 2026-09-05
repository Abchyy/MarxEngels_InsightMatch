"""Source-derived trusted local publication. Never writes the Canonical seed."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from marx_engels.corpus_registry.hashing import sha256_bytes, sha256_file
from marx_engels.corpus_registry.local_asset import (
    DEFAULT_RUNTIME_PATH,
    DEFAULT_SEED_PATH,
    QUOTATION_POLICY_SQLITE,
    TRUST_POLICY_SOURCE_DERIVED,
    LocalAssetManifest,
    LocalReleaseSidecar,
    assert_not_canonical_seed,
    load_expected_sha256,
    load_local_asset_manifest,
    sidecar_path_for,
    verify_seed_file,
)
from marx_engels.errors import DomainError
from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.state import utcnow
from marx_engels.storage.readonly import connect_readonly
from marx_engels.storage.sqlite import SQLiteDatabase

_PUBLISHED = "published"
_VERIFIED = "verified"
_OPERATOR = "local_source_derived_release"
_REASON = TRUST_POLICY_SOURCE_DERIVED
_NOT_HUMAN = "source-derived trusted local publication; not human review or collation"


def init_local_corpus(
    *,
    seed_path: Path | None = None,
    runtime_path: Path | None = None,
    manifest_path: Path | None = None,
    sha256_path: Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    spec = load_local_asset_manifest(manifest_path)
    expected = load_expected_sha256(sha256_path)
    if expected != spec.sha256:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Tracked SHA-256 file does not match the asset manifest.",
            details={"manifest_sha256": spec.sha256, "sha256_file": expected},
        )
    seed = seed_path or DEFAULT_SEED_PATH
    runtime = runtime_path or DEFAULT_RUNTIME_PATH
    assert_not_canonical_seed(runtime, seed)
    seed_digest = verify_seed_file(seed, spec)
    assert_sqlite_matches_spec(seed, spec, readonly=True)

    if runtime.is_file() and not replace:
        sidecar = _require_complete_sidecar(runtime, spec, seed_digest)
        return {
            "status": "already_initialized",
            "data_version": sidecar.data_version,
            "seed_sha256": seed_digest,
            "runtime_path": str(runtime),
            "trust_policy": sidecar.trust_policy,
            "human_reviewed": False,
        }

    runtime.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed, runtime)
    copied = sha256_file(runtime)
    if copied != seed_digest:
        runtime.unlink(missing_ok=True)
        raise DomainError(
            "RELEASE_MISMATCH",
            "Runtime copy SHA-256 drifted during copy from the Canonical seed.",
            details={"seed_sha256": seed_digest, "runtime_sha256": copied},
        )
    after_copy_seed = sha256_file(seed)
    if after_copy_seed != seed_digest:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Canonical seed SHA-256 changed during runtime copy.",
            details={"before": seed_digest, "after": after_copy_seed},
        )

    published_at = utcnow().isoformat()
    _publish_runtime(runtime, spec, published_at)
    assert_sqlite_matches_spec(runtime, spec, readonly=False, require_published=True)
    seed_after_publish = sha256_file(seed)
    if seed_after_publish != seed_digest:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Canonical seed was modified during local publication.",
            details={"before": seed_digest, "after": seed_after_publish},
        )

    sidecar = LocalReleaseSidecar(
        data_version=spec.data_version,
        corpus_id=spec.corpus_id,
        trust_policy=TRUST_POLICY_SOURCE_DERIVED,
        human_reviewed=False,
        quotation_policy=QUOTATION_POLICY_SQLITE,
        seed_sha256=seed_digest,
        init_complete=True,
        published_at=published_at,
        seed_path=str(seed),
        runtime_path=str(runtime),
    )
    atomic_write_json(sidecar_path_for(runtime), json.loads(sidecar.model_dump_json()))
    return {
        "status": "initialized",
        "data_version": spec.data_version,
        "seed_sha256": seed_digest,
        "runtime_path": str(runtime),
        "trust_policy": TRUST_POLICY_SOURCE_DERIVED,
        "human_reviewed": False,
        "quotation_policy": QUOTATION_POLICY_SQLITE,
        "published_at": published_at,
    }


def verify_local_sqlite_asset(
    *,
    seed_path: Path | None = None,
    manifest_path: Path | None = None,
    sha256_path: Path | None = None,
) -> tuple[int, str]:
    spec = load_local_asset_manifest(manifest_path)
    seed = seed_path or DEFAULT_SEED_PATH
    try:
        digest = verify_seed_file(seed, spec)
        expected = load_expected_sha256(sha256_path)
        if expected != digest:
            return 1, f"SHA-256 file {expected} != seed {digest}"
        assert_sqlite_matches_spec(seed, spec, readonly=True)
    except DomainError as exc:
        return 1, f"{exc.message} ({exc.code})"
    return (
        0,
        "Canonical SQLite seed is intact: "
        f"sha256={digest} volumes={spec.volume_count} works={spec.work_count} "
        f"sections={spec.section_count} passages={spec.passage_count} "
        f"trust_policy={spec.trust_policy} human_reviewed=false",
    )


def _require_complete_sidecar(
    runtime: Path, spec: LocalAssetManifest, seed_digest: str
) -> LocalReleaseSidecar:
    path = sidecar_path_for(runtime)
    if not path.is_file():
        raise DomainError(
            "STORAGE_NOT_CONFIGURED",
            "Runtime SQLite exists but local initialization is incomplete. "
            "Re-run init-local-corpus with --replace after backing up the file.",
            details={"runtime_path": str(runtime), "sidecar": str(path)},
        )
    sidecar = LocalReleaseSidecar.model_validate_json(path.read_text(encoding="utf-8"))
    if sidecar.seed_sha256 != seed_digest or sidecar.data_version != spec.data_version:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Existing runtime sidecar does not match the Canonical seed.",
            details={"sidecar": sidecar.model_dump(), "expected_sha256": seed_digest},
        )
    assert_sqlite_matches_spec(runtime, spec, readonly=False, require_published=True)
    return sidecar


def _publish_runtime(runtime: Path, spec: LocalAssetManifest, published_at: str) -> None:
    database = SQLiteDatabase(runtime)
    with database.connect() as connection:
        _assert_connection_matches_spec(connection, spec, require_published=False)
        connection.execute(
            "UPDATE corpus SET release_status = ?, updated_at = ? WHERE corpus_id = ?",
            (_PUBLISHED, published_at, spec.corpus_id),
        )
        connection.execute(
            "UPDATE edition SET release_status = ?, updated_at = ? WHERE edition_id = ?",
            (_PUBLISHED, published_at, spec.edition_id),
        )
        connection.execute("UPDATE volume SET release_status = ?", (_PUBLISHED,))
        connection.execute(
            "UPDATE work SET verification_status = ?, release_status = ?",
            (_VERIFIED, _PUBLISHED),
        )
        connection.execute("UPDATE section SET verification_status = ?", (_VERIFIED,))
        connection.execute(
            """
            UPDATE passage
            SET verification_status = ?, release_status = ?, updated_at = ?
            """,
            (_VERIFIED, _PUBLISHED, published_at),
        )
        connection.execute(
            """
            UPDATE data_release
            SET status = ?, published_at = ?
            WHERE data_version = ?
            """,
            (_PUBLISHED, published_at, spec.data_version),
        )
        connection.execute(
            """
            INSERT INTO verification_event(
                verification_id, target_type, target_id, field_name, before_hash,
                after_hash, reason_code, comment, operator_id, action, created_at
            ) VALUES (?, 'data_release', ?, 'release_status', ?, ?, ?, ?, ?, 'publish', ?)
            """,
            (
                f"evt_source_derived_{spec.data_version}",
                spec.data_version,
                spec.sha256,
                spec.sha256,
                _REASON,
                _NOT_HUMAN,
                _OPERATOR,
                published_at,
            ),
        )
        connection.commit()


def assert_sqlite_matches_spec(
    path: Path,
    spec: LocalAssetManifest,
    *,
    readonly: bool,
    require_published: bool = False,
) -> None:
    connection = connect_readonly(path) if readonly else SQLiteDatabase(path).connect()
    try:
        _assert_connection_matches_spec(
            connection, spec, require_published=require_published
        )
    finally:
        connection.close()


def _assert_connection_matches_spec(
    connection: sqlite3.Connection,
    spec: LocalAssetManifest,
    *,
    require_published: bool,
) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or str(integrity[0]) != "ok":
        raise DomainError(
            "RELEASE_MISMATCH",
            "SQLite integrity_check failed.",
            details={"result": None if integrity is None else str(integrity[0])},
        )
    counts = {
        "volume": _count(connection, "SELECT COUNT(*) FROM volume"),
        "work": _count(connection, "SELECT COUNT(*) FROM work"),
        "section": _count(connection, "SELECT COUNT(*) FROM section"),
        "passage": _count(connection, "SELECT COUNT(*) FROM passage"),
    }
    expected = {
        "volume": spec.volume_count,
        "work": spec.work_count,
        "section": spec.section_count,
        "passage": spec.passage_count,
    }
    if counts != expected:
        raise DomainError(
            "RELEASE_MISMATCH",
            "SQLite catalog counts do not match the Canonical asset manifest.",
            details={"actual": counts, "expected": expected},
        )
    unique_ids = _count(connection, "SELECT COUNT(DISTINCT evidence_id) FROM passage")
    if unique_ids != spec.passage_count:
        raise DomainError(
            "RELEASE_MISMATCH",
            "evidence_id values are not unique for the Canonical passage count.",
            details={"unique_ids": unique_ids, "passage_count": spec.passage_count},
        )
    corpus = connection.execute(
        "SELECT corpus_id FROM corpus"
    ).fetchall()
    edition = connection.execute("SELECT edition_id FROM edition").fetchall()
    release = connection.execute(
        "SELECT data_version, status, passage_count FROM data_release"
    ).fetchall()
    if [str(row["corpus_id"]) for row in corpus] != [spec.corpus_id]:
        raise DomainError(
            "RELEASE_MISMATCH",
            "SQLite corpus_id does not match the Canonical asset.",
            details={"expected": spec.corpus_id},
        )
    if [str(row["edition_id"]) for row in edition] != [spec.edition_id]:
        raise DomainError(
            "RELEASE_MISMATCH",
            "SQLite edition_id does not match the Canonical asset.",
            details={"expected": spec.edition_id},
        )
    if len(release) != 1 or str(release[0]["data_version"]) != spec.data_version:
        raise DomainError(
            "RELEASE_MISMATCH",
            "SQLite data_version does not match the Canonical asset.",
            details={"expected": spec.data_version},
        )
    if int(release[0]["passage_count"]) != spec.passage_count:
        raise DomainError(
            "RELEASE_MISMATCH",
            "data_release.passage_count does not match the Canonical asset.",
            details={"expected": spec.passage_count},
        )
    if require_published and str(release[0]["status"]) != _PUBLISHED:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Runtime data_release is not published.",
            details={"data_version": spec.data_version, "status": str(release[0]["status"])},
        )
    empty = _count(
        connection,
        "SELECT COUNT(*) FROM passage WHERE length(trim(verified_text)) = 0",
    )
    if empty:
        raise DomainError(
            "RELEASE_MISMATCH",
            "Canonical passages include empty verified_text.",
            details={"empty_passages": empty},
        )
    for row in connection.execute("SELECT evidence_id, verified_text, text_hash FROM passage"):
        digest = sha256_bytes(str(row["verified_text"]).encode("utf-8"))
        if digest != str(row["text_hash"]):
            raise DomainError(
                "RELEASE_MISMATCH",
                "Passage text_hash does not match SHA-256 of verified_text.",
                details={"evidence_id": str(row["evidence_id"])},
            )
    if require_published:
        unverified = _count(
            connection,
            "SELECT COUNT(*) FROM passage WHERE verification_status != 'verified' "
            "OR release_status != 'published'",
        )
        if unverified:
            raise DomainError(
                "RELEASE_MISMATCH",
                "Runtime passages are not fully source-derived published.",
                details={"not_released": unverified},
            )


def _count(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    return 0 if row is None else int(row[0])
