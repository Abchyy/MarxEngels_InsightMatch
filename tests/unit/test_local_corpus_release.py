from __future__ import annotations

import asyncio
import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient, Response

from marx_engels.api.app import create_app
from marx_engels.api.container import build_container
from marx_engels.contracts import Candidate, SearchMode, SearchScope
from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.corpus_registry.local_asset import DEFAULT_SEED_PATH, wal_sidecar_path
from marx_engels.errors import DomainError
from marx_engels.evidence import EvidenceExclusionReason, EvidenceService
from marx_engels.settings import Settings
from marx_engels.storage import SQLiteDatabase, SQLiteEvidenceRepository, SQLiteExactSearchIndex
from marx_engels.storage.cli import main as storage_main
from marx_engels.storage.cloud_export import export_cloud_ingest
from marx_engels.storage.local_publish import init_local_corpus, verify_local_sqlite_asset
from marx_engels.storage.readonly import connect_readonly
from marx_engels.storage.retrievers import ExactSearchRetriever

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-09-03T00:00:00Z"
DATA_VERSION = "data_test_v1"
CORPUS_ID = "marx_engels_collected_works_cn"
EDITION_ID = "people_press_2009_cn"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _finalize_db(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.commit()
    finally:
        connection.close()
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)
    return sha256_file(path)


def _write_manifest(
    directory: Path, digest: str, size: int, *, passage_count: int = 2
) -> tuple[Path, Path]:
    manifest = {
        "schema_version": 1,
        "corpus_id": CORPUS_ID,
        "edition_id": EDITION_ID,
        "data_version": DATA_VERSION,
        "sqlite_filename": "corpus.db",
        "sha256": digest,
        "byte_size": size,
        "volume_count": 1,
        "work_count": 1,
        "section_count": 1,
        "passage_count": passage_count,
        "trust_policy": "source_derived_trusted",
        "human_reviewed": False,
        "quotation_policy": "sqlite_canonical_text_only",
        "git_tracked": False,
    }
    manifest_path = directory / "local_asset.yaml"
    sha_path = directory / "corpus.sha256"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=True), encoding="utf-8")
    sha_path.write_text(f"{digest}  corpus.db\n", encoding="utf-8")
    return manifest_path, sha_path


def _build_seed(path: Path, *, extra_draft: bool = False) -> None:
    database = SQLiteDatabase(path)
    database.migrate(ROOT / "migrations")
    texts = [
        ("ev_main", "一般智力出现在正文中。"),
        ("ev_note", "另一段也包含一般智力。"),
    ]
    if extra_draft:
        texts.append(("ev_extra_draft", "这段是额外 draft，不能被无条件放行。"))
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO corpus(
                corpus_id, name, language, schema_version, rights_status,
                release_status, created_at, updated_at
            ) VALUES (?, '马克思恩格斯文集', 'zh-CN', 1, 'pending_review', 'draft', ?, ?)
            """,
            (CORPUS_ID, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO edition(
                edition_id, corpus_id, publisher, edition_label, rights_status,
                release_status, created_at, updated_at
            ) VALUES (?, ?, '人民出版社', '人民出版社2009年版', 'pending_review', 'draft', ?, ?)
            """,
            (EDITION_ID, CORPUS_ID, NOW, NOW),
        )
        connection.execute(
            """
            INSERT INTO asset(
                asset_id, asset_type, storage_uri, sha256, byte_size, mime_type, created_at
            ) VALUES ('asset_v01', 'pdf', 'internal://v01', ?, 1, 'application/pdf', ?)
            """,
            (_sha("asset_v01"), NOW),
        )
        connection.execute(
            """
            INSERT INTO volume(
                volume_id, edition_id, volume_no, title, pdf_asset_id, release_status
            ) VALUES ('vol_1', ?, 1, '第一卷', 'asset_v01', 'draft')
            """,
            (EDITION_ID,),
        )
        connection.execute(
            """
            INSERT INTO work(
                work_id, volume_id, title, author_code, date_precision, order_no,
                verification_status, release_status
            ) VALUES ('work_1', 'vol_1', '大纲', 'marx', 'unknown', 1, 'unverified', 'draft')
            """
        )
        connection.execute(
            """
            INSERT INTO section(
                section_id, work_id, title, level, order_no, verification_status
            ) VALUES ('sec_1', 'work_1', '正文', 0, 1, 'unverified')
            """
        )
        for order_no, (evidence_id, text) in enumerate(texts, start=1):
            connection.execute(
                """
                INSERT INTO passage(
                    evidence_id, section_id, content_type, verified_text, text_hash,
                    order_no, verification_status, release_status, created_at, updated_at
                ) VALUES (?, 'sec_1', 'main_text', ?, ?, ?, 'unverified', 'draft', ?, ?)
                """,
                (evidence_id, text, _sha(text), order_no, NOW, NOW),
            )
        connection.execute(
            """
            INSERT INTO data_release(
                data_version, corpus_id, passage_count, manifest_hash, status,
                created_at, published_at
            ) VALUES (?, ?, ?, ?, 'draft', ?, NULL)
            """,
            (DATA_VERSION, CORPUS_ID, 2 if not extra_draft else 3, _sha("manifest"), NOW),
        )
        connection.commit()


def _prepare_asset(tmp_path: Path, *, extra_draft: bool = False) -> tuple[Path, Path, Path]:
    seed = tmp_path / "seed" / "corpus.db"
    seed.parent.mkdir()
    _build_seed(seed, extra_draft=extra_draft)
    digest = _finalize_db(seed)
    manifest_path, sha_path = _write_manifest(
        tmp_path,
        digest,
        seed.stat().st_size,
        passage_count=3 if extra_draft else 2,
    )
    return seed, manifest_path, sha_path


def _shm_path(database_path: Path) -> Path:
    return Path(str(database_path) + "-shm")


def _seed_with_unhashed_wal(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    digest = sha256_file(seed)
    dirty = tmp_path / "dirty" / "corpus.db"
    dirty.parent.mkdir()
    shutil.copy2(seed, dirty)
    frozen = tmp_path / "wal-seed" / "corpus.db"
    frozen.parent.mkdir()
    connection = sqlite3.connect(dirty)
    try:
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute(
            "UPDATE passage SET verified_text = verified_text || ' WAL-ONLY' "
            "WHERE evidence_id = 'ev_main'"
        )
        connection.commit()
        wal = wal_sidecar_path(dirty)
        assert wal.is_file() and wal.stat().st_size > 0
        shutil.copy2(dirty, frozen)
        shutil.copy2(wal, wal_sidecar_path(frozen))
    finally:
        connection.close()
    assert sha256_file(frozen) == digest
    assert wal_sidecar_path(frozen).stat().st_size > 0
    return frozen, manifest_path, sha_path, digest


def test_gitignore_does_not_force_track_sqlite() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.db" in text
    assert "!corpora/marx_engels_collected_works_cn/sqlite/corpus.db" not in text


def test_missing_seed_fails_closed(tmp_path: Path) -> None:
    digest = "0" * 64
    manifest_path, sha_path = _write_manifest(tmp_path, digest, 10)
    code, message = verify_local_sqlite_asset(
        seed_path=tmp_path / "missing.db",
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    assert code == 1
    assert "missing" in message.lower() or "SQLITE_UNAVAILABLE" in message


def test_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    seed, manifest_path, _sha_path = _prepare_asset(tmp_path)
    bad = tmp_path / "bad.sha256"
    bad.write_text(f"{'a' * 64}  corpus.db\n", encoding="utf-8")
    code, message = verify_local_sqlite_asset(
        seed_path=seed, manifest_path=manifest_path, sha256_path=bad
    )
    assert code == 1
    assert "SHA-256" in message or "RELEASE_MISMATCH" in message


def test_readonly_verify_does_not_create_wal_or_shm(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    assert not wal_sidecar_path(seed).exists()
    assert not _shm_path(seed).exists()
    connection = connect_readonly(seed)
    try:
        row = connection.execute("SELECT COUNT(*) AS n FROM passage").fetchone()
        assert row is not None
        assert int(row["n"]) == 2
    finally:
        connection.close()
    code, message = verify_local_sqlite_asset(
        seed_path=seed, manifest_path=manifest_path, sha256_path=sha_path
    )
    assert code == 0
    assert "human_reviewed=false" in message
    assert not wal_sidecar_path(seed).exists()
    assert not _shm_path(seed).exists()


def test_nonempty_wal_rejected_when_main_hash_unchanged(tmp_path: Path) -> None:
    seed, manifest_path, sha_path, digest = _seed_with_unhashed_wal(tmp_path)
    assert sha256_file(seed) == digest
    code, message = verify_local_sqlite_asset(
        seed_path=seed, manifest_path=manifest_path, sha256_path=sha_path
    )
    assert code == 1
    assert "WAL" in message
    assert "RELEASE_MISMATCH" in message

    runtime = tmp_path / "runtime.db"
    with pytest.raises(DomainError) as init_error:
        init_local_corpus(
            seed_path=seed,
            runtime_path=runtime,
            manifest_path=manifest_path,
            sha256_path=sha_path,
        )
    assert init_error.value.code == "RELEASE_MISMATCH"
    assert "WAL" in init_error.value.message
    assert not runtime.exists()

    with pytest.raises(DomainError) as export_error:
        export_cloud_ingest(
            seed_path=seed,
            output_root=tmp_path / "export-wal",
            manifest_path=manifest_path,
            sha256_path=sha_path,
        )
    assert export_error.value.code == "RELEASE_MISMATCH"
    assert "WAL" in export_error.value.message
    assert not (tmp_path / "export-wal").exists()


def test_empty_wal_sidecar_does_not_fail_closed(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    isolated = tmp_path / "isolated" / "corpus.db"
    isolated.parent.mkdir()
    shutil.copy2(seed, isolated)
    wal_sidecar_path(isolated).write_bytes(b"")
    code, _message = verify_local_sqlite_asset(
        seed_path=isolated, manifest_path=manifest_path, sha256_path=sha_path
    )
    assert code == 0
    assert wal_sidecar_path(isolated).stat().st_size == 0
    assert not _shm_path(isolated).exists()


def test_extra_draft_rows_cannot_be_published(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path, extra_draft=True)
    # Spec from builder uses passage_count=3, but data_release.passage_count is 3
    # while Canonical policy is exact expected counts. Force the tracked spec to 2.
    digest = sha256_file(seed)
    manifest_path, sha_path = _write_manifest(
        tmp_path, digest, seed.stat().st_size, passage_count=2
    )
    with pytest.raises(DomainError) as error:
        init_local_corpus(
            seed_path=seed,
            runtime_path=tmp_path / "runtime.db",
            manifest_path=manifest_path,
            sha256_path=sha_path,
        )
    assert error.value.code == "RELEASE_MISMATCH"


def test_source_derived_publish_does_not_rewrite_text(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    seed_hash = sha256_file(seed)
    runtime = tmp_path / "runtime.db"
    report = init_local_corpus(
        seed_path=seed,
        runtime_path=runtime,
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    assert report["trust_policy"] == "source_derived_trusted"
    assert report["human_reviewed"] is False
    assert sha256_file(seed) == seed_hash
    with sqlite3.connect(runtime) as connection:
        rows = list(
            connection.execute(
                """
                SELECT evidence_id, verified_text, text_hash,
                       verification_status, release_status
                FROM passage ORDER BY evidence_id
                """
            )
        )
        seed_rows = list(
            sqlite3.connect(seed).execute(
                "SELECT evidence_id, verified_text, text_hash FROM passage ORDER BY evidence_id"
            )
        )
        actual = [(row[0], row[1], row[2]) for row in rows]
        expected = [(row[0], row[1], row[2]) for row in seed_rows]
        assert actual == expected
        assert {row[3] for row in rows} == {"verified"}
        assert {row[4] for row in rows} == {"published"}
        comment = connection.execute(
            "SELECT comment, reason_code FROM verification_event"
        ).fetchone()
        assert comment is not None
        assert "not human" in comment[0]
        assert comment[1] == "source_derived_trusted"


def test_unknown_draft_still_cannot_pass_evidence_service(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    runtime = tmp_path / "runtime.db"
    init_local_corpus(
        seed_path=seed,
        runtime_path=runtime,
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    with SQLiteDatabase(runtime).connect() as connection:
        connection.execute(
            """
            INSERT INTO passage(
                evidence_id, section_id, content_type, verified_text, text_hash,
                order_no, verification_status, release_status, created_at, updated_at
            ) VALUES (
                'ev_injected_draft', 'sec_1', 'main_text', '注入 draft', ?,
                99, 'unverified', 'draft', ?, ?
            )
            """,
            (_sha("注入 draft"), NOW, NOW),
        )
        connection.commit()
    repository = SQLiteEvidenceRepository(SQLiteDatabase(runtime))
    service = EvidenceService(repository)

    async def run() -> EvidenceExclusionReason:
        result = await service.hydrate(
            [Candidate(evidence_id="ev_injected_draft", channels=["lexical"])],
            SearchScope(corpus_ids=[CORPUS_ID]),
        )
        assert result.evidence == ()
        return result.exclusions[0].reason

    assert asyncio.run(run()) in {
        EvidenceExclusionReason.NOT_VERIFIED,
        EvidenceExclusionReason.NOT_PUBLISHED,
    }


def test_init_refuses_to_write_canonical_seed(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    with pytest.raises(DomainError) as error:
        init_local_corpus(
            seed_path=seed,
            runtime_path=seed,
            manifest_path=manifest_path,
            sha256_path=sha_path,
        )
    assert error.value.code == "STORAGE_NOT_CONFIGURED"


def test_export_is_deterministic_and_maps_to_evidence_id(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    first = export_cloud_ingest(
        seed_path=seed,
        output_root=tmp_path / "export-a",
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    second = export_cloud_ingest(
        seed_path=seed,
        output_root=tmp_path / "export-b",
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    assert first["units_sha256"] == second["units_sha256"]
    assert first["mapping_sha256"] == second["mapping_sha256"]
    assert first["upload"] is False
    assert first["human_reviewed"] is False
    mapping = (Path(first["mapping_path"])).read_text(encoding="utf-8").strip().splitlines()
    units = (Path(first["units_path"])).read_text(encoding="utf-8")
    assert "ru_ev_main_1" in units
    assert any('"evidence_id":"ev_main"' in line for line in mapping)
    assert "search_text_is_not_quotation" in units
    seed_hash = sha256_file(seed)
    first_again = export_cloud_ingest(
        seed_path=seed,
        output_root=tmp_path / "export-c",
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    assert sha256_file(seed) == seed_hash
    assert first_again["units_sha256"] == first["units_sha256"]


def test_retriever_returns_candidates_without_search_text(tmp_path: Path) -> None:
    seed, manifest_path, sha_path = _prepare_asset(tmp_path)
    runtime = tmp_path / "runtime.db"
    init_local_corpus(
        seed_path=seed,
        runtime_path=runtime,
        manifest_path=manifest_path,
        sha256_path=sha_path,
    )
    retriever = ExactSearchRetriever(SQLiteExactSearchIndex(SQLiteDatabase(runtime)))

    async def run() -> list[Candidate]:
        return await retriever.retrieve("一般智力", SearchScope(corpus_ids=[CORPUS_ID]), 10)

    candidates = asyncio.run(run())
    assert candidates
    assert all("search_text" not in item.model_dump() for item in candidates)
    assert {item.evidence_id for item in candidates} == {"ev_main", "ev_note"}


def test_container_rejects_canonical_seed_as_runtime() -> None:
    settings = Settings(sqlite_database_path=DEFAULT_SEED_PATH)
    with pytest.raises(DomainError) as error:
        build_container(settings)
    assert error.value.code == "STORAGE_NOT_CONFIGURED"


def _request(
    app: object, method: str, path: str, *, json: dict[str, object] | None = None
) -> Response:
    async def send() -> Response:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=json)

    return asyncio.run(send())


def test_missing_runtime_sqlite_does_not_create_empty_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "corpus.db"
    settings = Settings(sqlite_database_path=missing, active_data_version=DATA_VERSION)
    payload = {
        "query": "一般智力",
        "mode": SearchMode.EXACT.value,
        "scope": {"corpus_ids": [CORPUS_ID]},
    }
    response = _request(create_app(settings=settings), "POST", "/api/v1/search", json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SQLITE_UNAVAILABLE"
    assert not missing.exists()


def test_storage_cli_verify_missing_seed(tmp_path: Path) -> None:
    digest = "0" * 64
    manifest_path, sha_path = _write_manifest(tmp_path, digest, 10)
    assert (
        storage_main(
            [
                "verify-local-asset",
                "--seed",
                str(tmp_path / "no.db"),
                "--manifest",
                str(manifest_path),
                "--sha256",
                str(sha_path),
            ]
        )
        == 1
    )
