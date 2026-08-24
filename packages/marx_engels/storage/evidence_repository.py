"""Batch SQLite reader for authoritative passage records.

This adapter never constructs public Evidence and never reads LanceDB
``search_text`` or FTS auxiliary quotation fields.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping, Sequence

from marx_engels.retrieval_core import AuthoritativeEvidenceRecord
from marx_engels.storage.sqlite import SQLiteDatabase
from marx_engels.storage.sqlite_runtime import run_exclusive_or_unavailable

_PUBLISHED = "published"

_AUTHOR_DISPLAY = {
    "marx": "马克思",
    "engels": "恩格斯",
    "coauthored": "马克思和恩格斯",
    "attributed": "归属待考",
    "unknown": "作者不详",
}

_SELECT_PASSAGES = """
SELECT
    p.evidence_id AS evidence_id,
    p.verified_text AS verified_text,
    p.text_hash AS text_hash,
    p.verification_status AS verification_status,
    p.release_status AS release_status,
    p.content_type AS content_type,
    p.prev_id AS prev_id,
    p.next_id AS next_id,
    w.author_code AS author_code,
    w.title AS work_title,
    w.work_id AS work_id,
    w.work_date_start AS work_date_start,
    w.work_date_end AS work_date_end,
    w.date_precision AS date_precision,
    w.verification_status AS work_verification_status,
    w.release_status AS work_release_status,
    v.volume_id AS volume_id,
    v.volume_no AS volume_no,
    v.release_status AS volume_release_status,
    e.edition_id AS edition_id,
    e.edition_label AS edition_label,
    e.release_status AS edition_release_status,
    e.corpus_id AS corpus_id,
    c.name AS corpus_name,
    c.release_status AS corpus_release_status,
    s.verification_status AS section_verification_status,
    prev_p.release_status AS prev_release_status,
    prev_w.work_id AS prev_work_id,
    prev_e.corpus_id AS prev_corpus_id,
    next_p.release_status AS next_release_status,
    next_w.work_id AS next_work_id,
    next_e.corpus_id AS next_corpus_id
FROM passage AS p
JOIN section AS s ON s.section_id = p.section_id
JOIN work AS w ON w.work_id = s.work_id
JOIN volume AS v ON v.volume_id = w.volume_id
JOIN edition AS e ON e.edition_id = v.edition_id
JOIN corpus AS c ON c.corpus_id = e.corpus_id
LEFT JOIN passage AS prev_p ON prev_p.evidence_id = p.prev_id
LEFT JOIN section AS prev_s ON prev_s.section_id = prev_p.section_id
LEFT JOIN work AS prev_w ON prev_w.work_id = prev_s.work_id
LEFT JOIN volume AS prev_v ON prev_v.volume_id = prev_w.volume_id
LEFT JOIN edition AS prev_e ON prev_e.edition_id = prev_v.edition_id
LEFT JOIN passage AS next_p ON next_p.evidence_id = p.next_id
LEFT JOIN section AS next_s ON next_s.section_id = next_p.section_id
LEFT JOIN work AS next_w ON next_w.work_id = next_s.work_id
LEFT JOIN volume AS next_v ON next_v.volume_id = next_w.volume_id
LEFT JOIN edition AS next_e ON next_e.edition_id = next_v.edition_id
WHERE {evidence_filter}
"""

_SELECT_PAGES = """
SELECT
    pp.evidence_id AS evidence_id,
    pm.printed_page_label AS printed_page_label,
    pm.pdf_page AS pdf_page,
    pm.mapping_status AS mapping_status
FROM passage_page AS pp
JOIN page_map AS pm ON pm.page_id = pp.page_id
WHERE {evidence_filter}
ORDER BY pp.evidence_id ASC, pp.order_no ASC
"""


class SQLiteEvidenceRepository:
    """EvidenceRepository adapter. Returns AuthoritativeEvidenceRecord only."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> Mapping[str, AuthoritativeEvidenceRecord]:
        unique_ids = tuple(dict.fromkeys(evidence_ids))
        if not unique_ids:
            return {}
        return await asyncio.to_thread(_load_records, self._database, unique_ids)


def _load_records(
    database: SQLiteDatabase, evidence_ids: tuple[str, ...]
) -> dict[str, AuthoritativeEvidenceRecord]:
    def operation(connection: sqlite3.Connection) -> dict[str, AuthoritativeEvidenceRecord]:
        passage_filter, params = _evidence_filter("p.evidence_id", evidence_ids)
        page_filter, params = _evidence_filter("pp.evidence_id", evidence_ids)
        passage_rows = connection.execute(
            _SELECT_PASSAGES.format(evidence_filter=passage_filter),
            params,
        ).fetchall()
        page_rows = connection.execute(
            _SELECT_PAGES.format(evidence_filter=page_filter),
            params,
        ).fetchall()
        pages_by_id = _group_pages(page_rows)
        return {
            str(row["evidence_id"]): _to_record(row, pages_by_id.get(str(row["evidence_id"]), []))
            for row in passage_rows
        }

    return run_exclusive_or_unavailable(database, operation)


def _evidence_filter(
    column: str, evidence_ids: tuple[str, ...]
) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {
        f"evidence_id_{index}": value for index, value in enumerate(evidence_ids)
    }
    placeholders = ", ".join(f":evidence_id_{index}" for index in range(len(evidence_ids)))
    return f"{column} IN ({placeholders})", params


def _group_pages(rows: Sequence[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["evidence_id"]), []).append(row)
    return grouped


def _to_record(
    row: sqlite3.Row, page_rows: Sequence[sqlite3.Row]
) -> AuthoritativeEvidenceRecord:
    author_code = str(row["author_code"])
    printed_pages = tuple(str(item["printed_page_label"] or "") for item in page_rows)
    pdf_pages = tuple(int(item["pdf_page"]) for item in page_rows)
    mapping_statuses = tuple(str(item["mapping_status"]) for item in page_rows)
    prev_id = row["prev_id"]
    next_id = row["next_id"]
    return AuthoritativeEvidenceRecord(
        evidence_id=str(row["evidence_id"]),
        verified_text=str(row["verified_text"]),
        text_hash=str(row["text_hash"]),
        verification_status=str(row["verification_status"]),
        release_status=str(row["release_status"]),
        content_type=str(row["content_type"]),
        author_code=author_code,
        author=_AUTHOR_DISPLAY.get(author_code, author_code),
        work_title=str(row["work_title"]),
        corpus_id=str(row["corpus_id"]),
        corpus_name=str(row["corpus_name"]),
        edition_id=str(row["edition_id"]),
        edition_label=str(row["edition_label"] or ""),
        volume_id=str(row["volume_id"]),
        volume_no=int(row["volume_no"]),
        work_id=str(row["work_id"]),
        work_date_start=_optional_str(row["work_date_start"]),
        work_date_end=_optional_str(row["work_date_end"]),
        date_precision=str(row["date_precision"]),
        corpus_release_status=str(row["corpus_release_status"]),
        edition_release_status=str(row["edition_release_status"]),
        volume_release_status=str(row["volume_release_status"]),
        work_release_status=str(row["work_release_status"]),
        work_verification_status=str(row["work_verification_status"]),
        section_verification_status=str(row["section_verification_status"]),
        printed_pages=printed_pages,
        pdf_pages=pdf_pages,
        page_mapping_statuses=mapping_statuses,
        prev_evidence_id=_optional_str(prev_id),
        next_evidence_id=_optional_str(next_id),
        prev_is_released=_neighbor_is_public(row, "prev"),
        next_is_released=_neighbor_is_public(row, "next"),
    )


def _neighbor_is_public(row: sqlite3.Row, side: str) -> bool:
    return bool(
        row[f"{side}_release_status"] == _PUBLISHED
        and row[f"{side}_work_id"] == row["work_id"]
        and row[f"{side}_corpus_id"] == row["corpus_id"]
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
