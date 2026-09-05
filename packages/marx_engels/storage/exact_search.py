"""Authoritative exact search over SQLite verified_text."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping, Sequence

from marx_engels.contracts import Candidate, SearchScope
from marx_engels.storage.sqlite import SQLiteDatabase
from marx_engels.storage.sqlite_runtime import run_exclusive_or_unavailable

_CHANNEL = "exact"

_SELECT_EXACT_MATCHES = """
SELECT
    matched.evidence_id AS evidence_id,
    matched.exact_match_count AS exact_match_count
FROM (
    SELECT
        p.evidence_id AS evidence_id,
        CAST(
            (
                length(p.verified_text)
                - length(replace(p.verified_text, :query, ''))
            ) / length(:query)
            AS INTEGER
        ) AS exact_match_count,
        length(p.verified_text) AS text_length,
        v.volume_no AS volume_no,
        w.order_no AS work_order_no,
        s.order_no AS section_order_no,
        p.order_no AS passage_order_no
    FROM passage AS p
    JOIN section AS s ON s.section_id = p.section_id
    JOIN work AS w ON w.work_id = s.work_id
    JOIN volume AS v ON v.volume_id = w.volume_id
    JOIN edition AS e ON e.edition_id = v.edition_id
    JOIN corpus AS c ON c.corpus_id = e.corpus_id
    WHERE p.verification_status = 'verified'
      AND p.release_status = 'published'
      AND s.verification_status = 'verified'
      AND w.verification_status = 'verified'
      AND w.release_status = 'published'
      AND v.release_status = 'published'
      AND e.release_status = 'published'
      AND c.release_status = 'published'
      AND instr(p.verified_text, :query) > 0
"""

_ORDER_AND_LIMIT = """
) AS matched
ORDER BY
    matched.exact_match_count DESC,
    (CAST(matched.exact_match_count AS REAL) / matched.text_length) DESC,
    matched.volume_no ASC,
    matched.work_order_no ASC,
    matched.section_order_no ASC,
    matched.passage_order_no ASC,
    matched.evidence_id ASC
LIMIT :limit
"""


class SQLiteExactSearchIndex:
    """ExactSearchIndex adapter. Returns Candidate rows, never Evidence."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    async def search_exact(self, query: str, scope: SearchScope, limit: int) -> list[Candidate]:
        if query == "" or limit <= 0 or not scope.corpus_ids:
            return []

        filters, params = _scope_filter_clause(scope)
        params["query"] = query
        params["limit"] = int(limit)
        sql = _SELECT_EXACT_MATCHES
        if filters:
            sql += "  AND " + "\n  AND ".join(filters) + "\n"
        sql += _ORDER_AND_LIMIT

        rows = await asyncio.to_thread(_query_exact_matches, self._database, sql, params)
        return [
            Candidate(
                evidence_id=evidence_id,
                channels=[_CHANNEL],
                exact_match_count=match_count,
            )
            for evidence_id, match_count in rows
        ]


def _query_exact_matches(
    database: SQLiteDatabase, sql: str, parameters: Mapping[str, object]
) -> list[tuple[str, int]]:
    def operation(connection: sqlite3.Connection) -> list[tuple[str, int]]:
        rows = connection.execute(sql, parameters).fetchall()
        return [(str(row["evidence_id"]), int(row["exact_match_count"])) for row in rows]

    return run_exclusive_or_unavailable(database, operation)


def _scope_filter_clause(scope: SearchScope) -> tuple[list[str], dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}
    _bind_in(clauses, params, "e.corpus_id", scope.corpus_ids, "corpus_id")
    _bind_in(clauses, params, "e.edition_id", scope.edition_ids, "edition_id")
    _bind_in(clauses, params, "v.volume_id", scope.volume_ids, "volume_id")
    _bind_in(clauses, params, "w.work_id", scope.work_ids, "work_id")
    _bind_in(clauses, params, "w.author_code", [str(item) for item in scope.authors], "author")
    _bind_in(
        clauses,
        params,
        "p.content_type",
        [str(item) for item in scope.content_types],
        "content_type",
    )
    return clauses, params


def _bind_in(
    clauses: list[str],
    params: dict[str, object],
    column: str,
    values: Sequence[str],
    prefix: str,
) -> None:
    if not values:
        return
    placeholders: list[str] = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        params[key] = value
        placeholders.append(f":{key}")
    clauses.append(f"{column} IN ({', '.join(placeholders)})")
