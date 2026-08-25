"""Write Clean assemble snapshots into local SQLite as Unverified/Draft."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from marx_engels.corpus_registry.hashing import canonical_json_sha256
from marx_engels.corpus_registry.ids import CORPUS_ID, EDITION_ID
from marx_engels.corpus_registry.manifest import CorpusManifest
from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.layer_models import PassageLifecycle
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.pipeline import load_source_records
from marx_engels.ingestion.snapshot import load_assemble_snapshot
from marx_engels.ingestion.state import utcnow
from marx_engels.ingestion.verify import DEFAULT_MANIFEST, validate_manifest
from marx_engels.storage.sqlite import SQLiteDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIGRATIONS = PROJECT_ROOT / "migrations"


def _unique_by_id(items: list[Any], attr: str) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for item in items:
        key = str(getattr(item, attr))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def ingest_sqlite(
    layout: CorpusLayout,
    database: SQLiteDatabase,
    *,
    assemble_run_id: str | None = None,
    manifest_path: Path | None = None,
    replace: bool = False,
    migrations_dir: Path | None = None,
) -> dict[str, Any]:
    snapshot = load_assemble_snapshot(layout, assemble_run_id)
    manifest = validate_manifest(manifest_path or DEFAULT_MANIFEST)
    records = {item.volume_id: item for item in load_source_records(layout)}
    if not records:
        raise FileNotFoundError("no source records; run inventory first")
    database.migrate(migrations_dir or DEFAULT_MIGRATIONS)
    now = utcnow().isoformat()
    data_version = f"data_{utcnow().strftime('%Y_%m_%d')}_{uuid4().hex[:6]}"
    active = [
        item
        for item in snapshot.passages
        if item.lifecycle is PassageLifecycle.ACTIVE and item.text.strip()
    ]
    with database.connect(create_parent=True) as connection:
        if _corpus_exists(connection, manifest.corpus_id):
            if not replace:
                raise ValueError(
                    f"corpus {manifest.corpus_id} already exists; pass replace=True to rebuild"
                )
            _delete_corpus(connection, manifest.corpus_id)
        _insert_catalog(connection, manifest, records, snapshot, now)
        _insert_structure(connection, snapshot)
        _insert_passages(connection, active, snapshot.passage_pages, now)
        _insert_release(connection, manifest.corpus_id, data_version, active, now)
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        fk_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        fts_count = connection.execute("SELECT COUNT(*) FROM passage_fts").fetchone()
    if integrity is None or str(integrity[0]) != "ok":
        raise RuntimeError(f"sqlite integrity_check failed: {integrity}")
    if fk_violations:
        raise RuntimeError(f"sqlite foreign_key_check failed: {len(fk_violations)} rows")
    report = {
        "data_version": data_version,
        "assemble_run_id": snapshot.assemble_run_id,
        "sqlite_path": str(database.path),
        "corpus_id": manifest.corpus_id,
        "edition_id": manifest.edition_id,
        "volumes": len(records),
        "works_ingested": len(_unique_by_id(list(snapshot.works), "work_id")),
        "sections_ingested": len(_unique_by_id(list(snapshot.sections), "section_id")),
        "page_maps": len(snapshot.page_maps),
        "passages_ingested": len(active),
        "passages_verified": 0,
        "passages_unverified": len(active),
        "local_fts_rows": int(fts_count[0]) if fts_count else 0,
        "index_outbox": 0,
        "release_status": "draft",
        "quotation_policy": "unverified_not_formal_quotation",
    }
    atomic_write_json(layout.publication_report_path(data_version), report)
    atomic_write_json(layout.publication_reports / "latest.json", report)
    return report


def _corpus_exists(connection: sqlite3.Connection, corpus_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM corpus WHERE corpus_id = ?", (corpus_id,)
    ).fetchone()
    return row is not None


def _delete_corpus(connection: sqlite3.Connection, corpus_id: str) -> None:
    connection.execute(
        """
        DELETE FROM index_outbox WHERE data_version IN (
            SELECT data_version FROM data_release WHERE corpus_id = ?
        )
        """,
        (corpus_id,),
    )
    connection.execute("DELETE FROM data_release WHERE corpus_id = ?", (corpus_id,))
    volume_ids = [
        row[0]
        for row in connection.execute(
            """
            SELECT volume_id FROM volume
            WHERE edition_id IN (SELECT edition_id FROM edition WHERE corpus_id = ?)
            """,
            (corpus_id,),
        )
    ]
    for volume_id in volume_ids:
        evidence_ids = [
            row[0]
            for row in connection.execute(
                """
                SELECT p.evidence_id FROM passage AS p
                JOIN section AS s ON s.section_id = p.section_id
                JOIN work AS w ON w.work_id = s.work_id
                WHERE w.volume_id = ?
                """,
                (volume_id,),
            )
        ]
        if evidence_ids:
            placeholders = ",".join("?" * len(evidence_ids))
            connection.execute(
                f"DELETE FROM passage_fts WHERE evidence_id IN ({placeholders})",
                evidence_ids,
            )
            connection.execute(
                f"DELETE FROM passage_page WHERE evidence_id IN ({placeholders})",
                evidence_ids,
            )
            connection.execute(
                f"UPDATE passage SET prev_id = NULL, next_id = NULL, supersedes_id = NULL "
                f"WHERE evidence_id IN ({placeholders})",
                evidence_ids,
            )
            connection.execute(
                f"DELETE FROM passage WHERE evidence_id IN ({placeholders})",
                evidence_ids,
            )
        connection.execute(
            """
            DELETE FROM section WHERE work_id IN (
                SELECT work_id FROM work WHERE volume_id = ?
            )
            """,
            (volume_id,),
        )
        connection.execute("DELETE FROM work WHERE volume_id = ?", (volume_id,))
        connection.execute("DELETE FROM page_map WHERE volume_id = ?", (volume_id,))
        connection.execute("DELETE FROM volume WHERE volume_id = ?", (volume_id,))
    connection.execute("DELETE FROM edition WHERE corpus_id = ?", (corpus_id,))
    connection.execute("DELETE FROM corpus WHERE corpus_id = ?", (corpus_id,))
    connection.execute(
        "DELETE FROM asset WHERE asset_id LIKE ?",
        (f"asset_{corpus_id}_%",),
    )


def _insert_catalog(
    connection: sqlite3.Connection,
    manifest: CorpusManifest,
    records: dict[str, Any],
    snapshot: Any,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO corpus(
            corpus_id, name, language, schema_version, rights_status, release_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            manifest.corpus_id,
            manifest.display_name,
            manifest.language,
            manifest.schema_version,
            manifest.rights_status,
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO edition(
            edition_id, corpus_id, publisher, publish_year, isbn, edition_label,
            rights_status, release_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, NULL, ?, ?, 'draft', ?, ?)
        """,
        (
            manifest.edition_id,
            manifest.corpus_id,
            manifest.publisher,
            manifest.publish_year,
            manifest.edition_id,
            manifest.rights_status,
            now,
            now,
        ),
    )
    seen_hashes: dict[str, str] = {}
    volumes = sorted(records.values(), key=lambda item: item.volume_number)
    for record in volumes:
        asset_id = seen_hashes.get(record.sha256)
        if asset_id is None:
            asset_id = f"asset_{CORPUS_ID}_v{record.volume_number:02d}"
            connection.execute(
                """
                INSERT INTO asset(
                    asset_id, asset_type, storage_uri, sha256, byte_size, mime_type, created_at
                ) VALUES (?, 'pdf', ?, ?, ?, 'application/pdf', ?)
                """,
                (asset_id, record.source_uri, record.sha256, record.file_size_bytes, now),
            )
            seen_hashes[record.sha256] = asset_id
        connection.execute(
            """
            INSERT INTO volume(
                volume_id, edition_id, volume_no, title, pdf_asset_id, release_status
            ) VALUES (?, ?, ?, ?, ?, 'draft')
            """,
            (
                record.volume_id,
                EDITION_ID,
                record.volume_number,
                record.file_name,
                asset_id,
            ),
        )
    for page in _unique_by_id(list(snapshot.page_maps), "page_id"):
        connection.execute(
            """
            INSERT INTO page_map(
                page_id, volume_id, pdf_page, printed_page_label, printed_page_number,
                page_type, mapping_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                page.page_id,
                page.volume_id,
                page.pdf_page,
                page.printed_page_label,
                page.printed_page_number,
                page.page_type.value,
                page.mapping_status.value,
            ),
        )


def _insert_structure(connection: sqlite3.Connection, snapshot: Any) -> None:
    works_by_volume: dict[str, list[Any]] = defaultdict(list)
    for work in _unique_by_id(list(snapshot.works), "work_id"):
        works_by_volume[work.volume_id].append(work)
    for volume_id, works in works_by_volume.items():
        ordered = sorted(works, key=lambda item: (item.pdf_page_start, item.work_id))
        for order_no, work in enumerate(ordered, start=1):
            connection.execute(
                """
                INSERT INTO work(
                    work_id, volume_id, title, author_code, work_date_start, work_date_end,
                    date_precision, date_source, first_publication_date, order_no,
                    verification_status, release_status
                ) VALUES (
                    ?, ?, ?, 'unknown', NULL, NULL, 'unknown', NULL, NULL, ?,
                    'unverified', 'draft'
                )
                """,
                (work.work_id, volume_id, work.title, order_no),
            )
    pending = _unique_by_id(list(snapshot.sections), "section_id")
    inserted: set[str] = set()
    guard = 0
    while pending:
        guard += 1
        if guard > len(snapshot.sections) + 2:
            raise RuntimeError("section parent cycle or missing parent_id")
        remaining: list[Any] = []
        ready_by_parent: dict[tuple[str, str | None], list[Any]] = defaultdict(list)
        for section in pending:
            if section.parent_id is None or section.parent_id in inserted:
                ready_by_parent[(section.work_id, section.parent_id)].append(section)
            else:
                remaining.append(section)
        if not ready_by_parent:
            raise RuntimeError("section parent_id does not exist in snapshot")
        for (work_id, parent_id), group in ready_by_parent.items():
            ordered = sorted(group, key=lambda item: (item.pdf_page_start, item.section_id))
            for order_no, section in enumerate(ordered, start=1):
                connection.execute(
                    """
                    INSERT INTO section(
                        section_id, work_id, parent_id, title, level, order_no,
                        verification_status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'unverified')
                    """,
                    (
                        section.section_id,
                        work_id,
                        parent_id,
                        section.title,
                        0 if parent_id is None else 1,
                        order_no,
                    ),
                )
                inserted.add(section.section_id)
        pending = remaining


def _insert_passages(
    connection: sqlite3.Connection,
    passages: list[Any],
    links: list[Any],
    now: str,
) -> None:
    by_section: dict[str, list[Any]] = defaultdict(list)
    for passage in _unique_by_id(list(passages), "evidence_id"):
        by_section[passage.section_id].append(passage)
    order_by_id: dict[str, int] = {}
    rows: list[tuple[Any, ...]] = []
    fts_rows: list[tuple[str, str]] = []
    for section_id, group in by_section.items():
        ordered = sorted(group, key=lambda item: (item.pdf_page_start, item.evidence_id))
        for order_no, passage in enumerate(ordered, start=1):
            order_by_id[passage.evidence_id] = order_no
            rows.append(
                (
                    passage.evidence_id,
                    section_id,
                    passage.content_type.value,
                    passage.text,
                    passage.text_hash,
                    order_no,
                    now,
                    now,
                )
            )
            fts_rows.append((passage.evidence_id, passage.text))
    connection.executemany(
        """
        INSERT INTO passage(
            evidence_id, section_id, content_type, verified_text, text_hash,
            prev_id, next_id, order_no, verification_status, release_status,
            revision_no, supersedes_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 'unverified', 'draft', 1, NULL, ?, ?)
        """,
        rows,
    )
    connection.executemany(
        "UPDATE passage SET prev_id = ?, next_id = ? WHERE evidence_id = ?",
        [
            (
                passage.prev_id if passage.prev_id in order_by_id else None,
                passage.next_id if passage.next_id in order_by_id else None,
                passage.evidence_id,
            )
            for passage in passages
        ],
    )
    seen: set[tuple[str, str]] = set()
    page_rows: list[tuple[Any, ...]] = []
    for link in links:
        if link.evidence_id not in order_by_id:
            continue
        key = (link.evidence_id, link.page_id)
        if key in seen:
            continue
        seen.add(key)
        page_rows.append(
            (link.evidence_id, link.page_id, link.order_no, link.start_offset, link.end_offset)
        )
    connection.executemany(
        """
        INSERT INTO passage_page(evidence_id, page_id, order_no, start_offset, end_offset)
        VALUES (?, ?, ?, ?, ?)
        """,
        page_rows,
    )
    connection.executemany(
        "INSERT INTO passage_fts(evidence_id, search_text) VALUES (?, ?)",
        fts_rows,
    )


def _insert_release(
    connection: sqlite3.Connection,
    corpus_id: str,
    data_version: str,
    passages: list[Any],
    now: str,
) -> None:
    payload: dict[str, object] = {
        "corpus_id": corpus_id,
        "data_version": data_version,
        "verification_status": "unverified",
        "release_status": "draft",
        "passages": [
            {"evidence_id": item.evidence_id, "text_hash": item.text_hash}
            for item in sorted(passages, key=lambda row: row.evidence_id)
        ],
    }
    connection.execute(
        """
        INSERT INTO data_release(
            data_version, corpus_id, passage_count, manifest_hash, status, created_at,
            published_at
        ) VALUES (?, ?, ?, ?, 'draft', ?, NULL)
        """,
        (
            data_version,
            corpus_id,
            len(passages),
            canonical_json_sha256(payload),
            now,
        ),
    )
