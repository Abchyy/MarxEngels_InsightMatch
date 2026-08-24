"""Build the deterministic synthetic corpus in a caller-owned temporary path."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from marx_engels.storage import SQLiteDatabase

FIXTURE_ROOT = Path(__file__).resolve().parent
FIXTURE_PATH = FIXTURE_ROOT / "fixture.yaml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SyntheticCorpusBuild:
    database: SQLiteDatabase
    fixture_version: str
    notice: str
    vector_records: tuple[dict[str, object], ...]


TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "corpus": (
        "corpus_id",
        "name",
        "language",
        "schema_version",
        "rights_status",
        "release_status",
        "created_at",
        "updated_at",
    ),
    "edition": (
        "edition_id",
        "corpus_id",
        "publisher",
        "publish_year",
        "isbn",
        "edition_label",
        "rights_status",
        "release_status",
        "created_at",
        "updated_at",
    ),
    "asset": (
        "asset_id",
        "asset_type",
        "storage_uri",
        "sha256",
        "byte_size",
        "mime_type",
        "created_at",
    ),
    "volume": (
        "volume_id",
        "edition_id",
        "volume_no",
        "title",
        "pdf_asset_id",
        "release_status",
    ),
    "work": (
        "work_id",
        "volume_id",
        "title",
        "author_code",
        "work_date_start",
        "work_date_end",
        "date_precision",
        "date_source",
        "first_publication_date",
        "order_no",
        "verification_status",
        "release_status",
    ),
    "section": (
        "section_id",
        "work_id",
        "parent_id",
        "title",
        "level",
        "order_no",
        "verification_status",
    ),
    "page_map": (
        "page_id",
        "volume_id",
        "pdf_page",
        "printed_page_label",
        "printed_page_number",
        "page_type",
        "mapping_status",
    ),
    "passage": (
        "evidence_id",
        "section_id",
        "content_type",
        "verified_text",
        "text_hash",
        "prev_id",
        "next_id",
        "order_no",
        "verification_status",
        "release_status",
        "revision_no",
        "supersedes_id",
        "created_at",
        "updated_at",
    ),
    "passage_page": (
        "evidence_id",
        "page_id",
        "order_no",
        "start_offset",
        "end_offset",
    ),
    "data_release": (
        "data_version",
        "corpus_id",
        "passage_count",
        "manifest_hash",
        "status",
        "created_at",
        "published_at",
    ),
    "index_release": (
        "index_version",
        "data_version",
        "embedding_provider",
        "embedding_model",
        "embedding_dimension",
        "config_hash",
        "row_count",
        "status",
        "created_at",
        "published_at",
    ),
}


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("synthetic fixture root must be a mapping")
    return payload


def build_synthetic_corpus(
    database_path: Path,
    *,
    migrations_dir: Path | None = None,
) -> SyntheticCorpusBuild:
    """Migrate and seed a new temporary SQLite database.

    The caller owns ``database_path``. Existing files are rejected so this helper
    cannot accidentally overwrite a developer or production database.
    """

    if database_path.exists():
        raise FileExistsError(f"refusing to overwrite existing database: {database_path}")
    payload = load_fixture()
    database = SQLiteDatabase(database_path)
    database.migrate(migrations_dir or PROJECT_ROOT / "migrations")
    created_at = "2026-08-24T00:00:00Z"

    passages = []
    for source in payload["passages"]:
        row = dict(source)
        row.update(
            text_hash=_text_hash(str(row["verified_text"])),
            revision_no=1,
            supersedes_id=None,
            created_at=created_at,
            updated_at=created_at,
        )
        passages.append(row)

    passage_by_id = {row["evidence_id"]: row for row in passages}
    vectors = _materialize_vector_records(payload, passage_by_id)
    _validate_fixture(payload, passages, vectors)

    with database.connect() as connection:
        _insert_rows(connection, "corpus", payload["corpora"])
        _insert_rows(connection, "edition", payload["editions"])
        _insert_rows(connection, "asset", payload["assets"])
        _insert_rows(connection, "volume", payload["volumes"])
        _insert_rows(connection, "work", payload["works"])
        _insert_rows(connection, "section", payload["sections"])
        _insert_rows(connection, "page_map", payload["pages"])
        passage_insert_rows = [
            {**row, "prev_id": None, "next_id": None} for row in passages
        ]
        _insert_rows(connection, "passage", passage_insert_rows)
        connection.executemany(
            "UPDATE passage SET prev_id = ?, next_id = ? WHERE evidence_id = ?",
            [
                (row["prev_id"], row["next_id"], row["evidence_id"])
                for row in passages
            ],
        )
        _insert_rows(connection, "passage_page", payload["passage_pages"])
        _insert_rows(connection, "data_release", payload["data_releases"])
        _insert_rows(connection, "index_release", payload["index_releases"])
        connection.executemany(
            "INSERT INTO passage_fts(evidence_id, search_text) VALUES (?, ?)",
            [(row["evidence_id"], row["search_text"]) for row in vectors],
        )
        connection.executemany(
            """
            INSERT INTO index_outbox(
                event_id, evidence_id, operation, data_version, text_hash, status,
                attempt_count, last_error, created_at, processed_at
            ) VALUES (?, ?, 'upsert', ?, ?, 'processed', 1, NULL, ?, ?)
            """,
            [
                (
                    f"evt_{row['retrieval_unit_id']}",
                    row["evidence_id"],
                    row["data_version"],
                    row["text_hash"],
                    created_at,
                    created_at,
                )
                for row in vectors
            ],
        )

    return SyntheticCorpusBuild(
        database=database,
        fixture_version=str(payload["fixture_version"]),
        notice=str(payload["notice"]),
        vector_records=tuple(vectors),
    )


def _materialize_vector_records(
    payload: dict[str, Any],
    passage_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    section_by_id = {row["section_id"]: row for row in payload["sections"]}
    work_by_id = {row["work_id"]: row for row in payload["works"]}
    volume_by_id = {row["volume_id"]: row for row in payload["volumes"]}
    edition_by_id = {row["edition_id"]: row for row in payload["editions"]}
    data_by_corpus = {row["corpus_id"]: row for row in payload["data_releases"]}
    index_by_data = {row["data_version"]: row for row in payload["index_releases"]}
    embedding = payload["embedding"]
    records: list[dict[str, object]] = []

    for source in payload["vectors"]:
        passage = passage_by_id[source["evidence_id"]]
        section = section_by_id[passage["section_id"]]
        work = work_by_id[section["work_id"]]
        volume = volume_by_id[work["volume_id"]]
        edition = edition_by_id[volume["edition_id"]]
        data_release = data_by_corpus[edition["corpus_id"]]
        index_release = index_by_data[data_release["data_version"]]
        records.append(
            {
                "retrieval_unit_id": source["retrieval_unit_id"],
                "evidence_id": passage["evidence_id"],
                "corpus_id": edition["corpus_id"],
                "edition_id": edition["edition_id"],
                "volume_id": volume["volume_id"],
                "work_id": work["work_id"],
                "content_type": passage["content_type"],
                "search_text": (
                    f"[合成语料] {work['title']} [正文] {passage['verified_text']}"
                ),
                "vector": list(source["vector"]),
                "text_hash": passage["text_hash"],
                "embedding_provider": embedding["provider"],
                "embedding_model": embedding["model"],
                "data_version": data_release["data_version"],
                "index_version": index_release["index_version"],
                "release_status": "published",
            }
        )
    return records


def _validate_fixture(
    payload: dict[str, Any],
    passages: list[dict[str, Any]],
    vectors: list[dict[str, object]],
) -> None:
    notice = str(payload["notice"])
    if "非马克思恩格斯原典" not in notice or "禁止作为引文" not in notice:
        raise ValueError("synthetic fixture notice must explicitly forbid citation")
    if any(not str(row["verified_text"]).startswith("【合成数据，非原典】") for row in passages):
        raise ValueError("every synthetic passage must carry the non-source prefix")

    passage_ids = [str(row["evidence_id"]) for row in passages]
    if len(passage_ids) != len(set(passage_ids)):
        raise ValueError("synthetic evidence IDs must be unique")
    vector_ids = [str(row["retrieval_unit_id"]) for row in vectors]
    if len(vector_ids) != len(set(vector_ids)):
        raise ValueError("synthetic retrieval unit IDs must be unique")

    dimension = int(payload["embedding"]["dimension"])
    for row in vectors:
        if len(row["vector"]) != dimension:  # type: ignore[arg-type]
            raise ValueError("synthetic vector dimension mismatch")
        passage = next(item for item in passages if item["evidence_id"] == row["evidence_id"])
        if (
            passage["verification_status"] != "verified"
            or passage["release_status"] != "published"
        ):
            raise ValueError("only verified and published passages may have vectors")

    expected_by_data = {row["data_version"]: row["row_count"] for row in payload["index_releases"]}
    actual_by_data: dict[str, int] = {}
    for row in vectors:
        key = str(row["data_version"])
        actual_by_data[key] = actual_by_data.get(key, 0) + 1
    if actual_by_data != expected_by_data:
        raise ValueError("index release row counts do not match synthetic vectors")


def _insert_rows(connection: Any, table: str, rows: list[dict[str, Any]]) -> None:
    columns = TABLE_COLUMNS[table]
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    connection.executemany(
        f"INSERT INTO {table}({column_sql}) VALUES ({placeholders})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
