from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from marx_engels.contracts import AuthorCode, Candidate, ContentType, SearchScope
from marx_engels.storage import SQLiteDatabase, SQLiteExactSearchIndex
from marx_engels.storage import sqlite as sqlite_adapter
from marx_engels.storage.exact_search import _SELECT_EXACT_MATCHES

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-01-01T00:00:00Z"
QUERY_PERSON = "人"
SQL_LITERAL = "'; DROP TABLE passage; --"
WILDCARD_TEXT = "百分号%和下划线_字面量"


@dataclass(frozen=True)
class PassageSeed:
    evidence_id: str
    verified_text: str
    corpus_id: str = "corpus_a"
    edition_id: str = "edition_a1"
    volume_id: str = "volume_a1"
    volume_no: int = 1
    work_id: str = "work_marx"
    author_code: str = "marx"
    work_order_no: int = 1
    section_id: str = "section_marx"
    section_order_no: int = 1
    passage_order_no: int = 1
    content_type: str = "main_text"
    verification_status: str = "verified"
    release_status: str = "published"


SEEDS = (
    PassageSeed("p_sort_b", "人人abcdefgh", passage_order_no=1),
    PassageSeed("p_sort_g", "人人abcdefgh", passage_order_no=2),
    PassageSeed(
        "p_footnote",
        "人在脚注中出现",
        passage_order_no=3,
        content_type="footnote",
    ),
    PassageSeed("p_draft", "人未发布段落", passage_order_no=4, release_status="draft"),
    PassageSeed(
        "p_unverified",
        "人未校验段落",
        passage_order_no=5,
        verification_status="unverified",
    ),
    PassageSeed("p_special", f"前缀{SQL_LITERAL}后缀", passage_order_no=6),
    PassageSeed("p_wildcard", WILDCARD_TEXT, passage_order_no=7),
    PassageSeed("p_ascii", "The word Force appears.", passage_order_no=8),
    PassageSeed(
        "p_sort_f",
        "人人abcdefgh",
        work_id="work_marx_later",
        work_order_no=2,
        section_id="section_marx_later",
        passage_order_no=1,
    ),
    PassageSeed(
        "p_engels",
        "人属于恩格斯著作",
        work_id="work_engels",
        author_code="engels",
        work_order_no=3,
        section_id="section_engels",
        passage_order_no=1,
    ),
    PassageSeed(
        "p_sort_a",
        "人人人",
        volume_id="volume_a2",
        volume_no=2,
        work_id="work_marx_v2",
        section_id="section_marx_v2",
        passage_order_no=1,
    ),
    PassageSeed(
        "p_sort_c",
        "人人",
        volume_id="volume_a2",
        volume_no=2,
        work_id="work_marx_v2",
        section_id="section_marx_v2",
        passage_order_no=2,
    ),
    PassageSeed(
        "p_other_edition",
        "人在另一版本出现",
        edition_id="edition_a2",
        volume_id="volume_a2e2",
        volume_no=3,
        work_id="work_other_edition",
        section_id="section_other_edition",
    ),
    PassageSeed(
        "p_other_corpus",
        "人在另一文献集出现",
        corpus_id="corpus_b",
        edition_id="edition_b1",
        volume_id="volume_b1",
        volume_no=1,
        work_id="work_corpus_b",
        section_id="section_corpus_b",
    ),
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _count_non_overlapping(text: str, query: str) -> int:
    count = 0
    start = 0
    while True:
        found = text.find(query, start)
        if found < 0:
            return count
        count += 1
        start = found + len(query)


def _scope(**overrides: object) -> SearchScope:
    payload: dict[str, object] = {"corpus_ids": ["corpus_a"]}
    payload.update(overrides)
    return SearchScope.model_validate(payload)


def _search(
    index: SQLiteExactSearchIndex, query: str, scope: SearchScope, limit: int = 50
) -> list[Candidate]:
    return asyncio.run(index.search_exact(query, scope, limit))


def _ids(candidates: list[Candidate]) -> list[str]:
    return [candidate.evidence_id for candidate in candidates]


def _insert_seed(connection: sqlite3.Connection, seed: PassageSeed) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO corpus(
            corpus_id, name, language, schema_version, rights_status,
            release_status, created_at, updated_at
        ) VALUES (?, ?, 'zh', 1, 'approved', 'published', ?, ?)
        """,
        (seed.corpus_id, seed.corpus_id, NOW, NOW),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO edition(
            edition_id, corpus_id, publisher, edition_label, rights_status,
            release_status, created_at, updated_at
        ) VALUES (?, ?, 'test', 'test-edition', 'approved', 'published', ?, ?)
        """,
        (seed.edition_id, seed.corpus_id, NOW, NOW),
    )
    asset_id = f"asset_{seed.volume_id}"
    connection.execute(
        """
        INSERT OR IGNORE INTO asset(
            asset_id, asset_type, storage_uri, sha256, byte_size, mime_type, created_at
        ) VALUES (?, 'pdf', ?, ?, 1, 'application/pdf', ?)
        """,
        (asset_id, f"file://{asset_id}", _sha(asset_id), NOW),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO volume(
            volume_id, edition_id, volume_no, title, pdf_asset_id, release_status
        ) VALUES (?, ?, ?, ?, ?, 'published')
        """,
        (seed.volume_id, seed.edition_id, seed.volume_no, seed.volume_id, asset_id),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO work(
            work_id, volume_id, title, author_code, date_precision, order_no,
            verification_status, release_status
        ) VALUES (?, ?, ?, ?, 'unknown', ?, 'verified', 'published')
        """,
        (seed.work_id, seed.volume_id, seed.work_id, seed.author_code, seed.work_order_no),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO section(
            section_id, work_id, title, level, order_no, verification_status
        ) VALUES (?, ?, ?, 0, ?, 'verified')
        """,
        (seed.section_id, seed.work_id, seed.section_id, seed.section_order_no),
    )
    connection.execute(
        """
        INSERT INTO passage(
            evidence_id, section_id, content_type, verified_text, text_hash,
            order_no, verification_status, release_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            seed.evidence_id,
            seed.section_id,
            seed.content_type,
            seed.verified_text,
            _sha(seed.verified_text),
            seed.passage_order_no,
            seed.verification_status,
            seed.release_status,
            NOW,
            NOW,
        ),
    )


@pytest.fixture
def exact_index(tmp_path: Path) -> tuple[SQLiteExactSearchIndex, SQLiteDatabase]:
    database = SQLiteDatabase(tmp_path / "corpus.db")
    database.migrate(ROOT / "migrations")
    with database.connect() as connection:
        for seed in SEEDS:
            _insert_seed(connection, seed)
    return SQLiteExactSearchIndex(database), database


def _verified_text(database: SQLiteDatabase, evidence_id: str) -> str:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT verified_text FROM passage WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
    assert row is not None
    return str(row["verified_text"])


def test_short_query_returns_literal_hits_with_non_overlapping_counts(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, database = exact_index
    candidates = _search(index, QUERY_PERSON, _scope())
    assert candidates
    assert all("verified_text" not in candidate.model_dump() for candidate in candidates)
    assert all(candidate.channels == ["exact"] for candidate in candidates)
    for candidate in candidates:
        text = _verified_text(database, candidate.evidence_id)
        assert QUERY_PERSON in text
        assert candidate.exact_match_count == _count_non_overlapping(text, QUERY_PERSON)
    by_id = {candidate.evidence_id: candidate for candidate in candidates}
    assert by_id["p_sort_a"].exact_match_count == 3
    overlapping = _search(index, "人人", _scope(work_ids=["work_marx_v2"]))
    assert _ids(overlapping) == ["p_sort_c", "p_sort_a"]
    assert overlapping[0].exact_match_count == 1
    assert overlapping[1].exact_match_count == 1


def test_unpublished_and_unverified_passages_are_excluded(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, _database = exact_index
    ids = set(_ids(_search(index, QUERY_PERSON, _scope())))
    assert "p_draft" not in ids
    assert "p_unverified" not in ids
    assert "p_sort_a" in ids


def test_scope_filters_isolate_corpus_edition_volume_work_author_and_content_type(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, _database = exact_index
    corpus_a = set(_ids(_search(index, QUERY_PERSON, _scope())))
    corpus_b = set(_ids(_search(index, QUERY_PERSON, _scope(corpus_ids=["corpus_b"]))))
    assert "p_other_corpus" not in corpus_a
    assert corpus_b == {"p_other_corpus"}
    assert "p_other_edition" not in set(
        _ids(_search(index, QUERY_PERSON, _scope(edition_ids=["edition_a1"])))
    )
    volume_ids = set(_ids(_search(index, QUERY_PERSON, _scope(volume_ids=["volume_a1"]))))
    assert volume_ids == {"p_sort_b", "p_sort_g", "p_sort_f", "p_engels"}
    work_ids = set(_ids(_search(index, QUERY_PERSON, _scope(work_ids=["work_marx"]))))
    assert work_ids == {"p_sort_b", "p_sort_g"}
    marx_only = set(_ids(_search(index, QUERY_PERSON, _scope(authors=[AuthorCode.MARX]))))
    assert "p_engels" not in marx_only
    assert "p_sort_a" in marx_only
    footnotes = set(
        _ids(_search(index, QUERY_PERSON, _scope(content_types=[ContentType.FOOTNOTE])))
    )
    assert footnotes == {"p_footnote"}
    assert "p_footnote" not in corpus_a


def test_sql_metacharacters_are_bound_literals(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, database = exact_index
    traced: list[str] = []

    original_connect = database.connect

    def connect(*, create_parent: bool = False) -> sqlite3.Connection:
        connection = original_connect(create_parent=create_parent)
        connection.set_trace_callback(traced.append)
        return connection

    database.connect = connect  # type: ignore[method-assign]
    assert "instr(p.verified_text, :query) > 0" in _SELECT_EXACT_MATCHES
    candidates = _search(index, SQL_LITERAL, _scope())
    assert _ids(candidates) == ["p_special"]
    joined = "\n".join(traced)
    assert "passage_fts" not in joined.lower()
    assert "instr(" in joined.lower()
    assert not any(statement.lstrip().lower().startswith("drop ") for statement in traced)
    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
    assert "passage" in tables
    percent = _search(index, "%", _scope())
    underscore = _search(index, "_", _scope())
    assert _ids(percent) == ["p_wildcard"]
    assert _ids(underscore) == ["p_wildcard"]
    assert _ids(_search(index, "force", _scope())) == []
    assert _ids(_search(index, "Force", _scope())) == ["p_ascii"]


def test_ranking_is_stable_and_respects_limit(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, _database = exact_index
    ordered = _ids(_search(index, QUERY_PERSON, _scope()))
    assert ordered == [
        "p_sort_a",
        "p_sort_c",
        "p_sort_b",
        "p_sort_g",
        "p_sort_f",
        "p_engels",
        "p_other_edition",
    ]
    limited = _ids(_search(index, QUERY_PERSON, _scope(), limit=3))
    assert limited == ["p_sort_a", "p_sort_c", "p_sort_b"]
    assert _search(index, QUERY_PERSON, _scope(), limit=0) == []


def test_empty_result_when_query_is_absent(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, _database = exact_index
    assert _search(index, "不存在的逐字查询xyz", _scope()) == []
    assert _search(index, QUERY_PERSON, _scope(work_ids=["work_corpus_b"])) == []


def test_sqlite_work_runs_on_one_worker_not_the_event_loop(
    exact_index: tuple[SQLiteExactSearchIndex, SQLiteDatabase],
) -> None:
    index, database = exact_index
    observed: dict[str, int] = {}
    original_connect = database.connect
    original_sqlite_connect = sqlite_adapter.sqlite3.connect

    class TracingConnection(sqlite3.Connection):
        def execute(self, *args: object, **kwargs: object) -> sqlite3.Cursor:
            observed["execute"] = threading.get_ident()
            cursor = super().execute(*args, **kwargs)
            original_fetchall = cursor.fetchall

            def fetchall() -> list[sqlite3.Row]:
                observed["fetchall"] = threading.get_ident()
                return original_fetchall()

            try:
                cursor.fetchall = fetchall  # type: ignore[method-assign]
            except AttributeError:
                observed["fetchall"] = observed["execute"]
            return cursor

        def close(self) -> None:
            observed["close"] = threading.get_ident()
            super().close()

    def sqlite_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = TracingConnection
        return original_sqlite_connect(*args, **kwargs)

    def connect(*, create_parent: bool = False) -> sqlite3.Connection:
        observed["connect"] = threading.get_ident()
        return original_connect(create_parent=create_parent)

    database.connect = connect  # type: ignore[method-assign]
    sqlite_adapter.sqlite3.connect = sqlite_connect  # type: ignore[method-assign]

    async def run_from_event_loop() -> tuple[int, list[Candidate]]:
        loop_ident = threading.get_ident()
        candidates = await index.search_exact(QUERY_PERSON, _scope(), 1)
        return loop_ident, candidates

    try:
        loop_ident, candidates = asyncio.run(run_from_event_loop())
    finally:
        sqlite_adapter.sqlite3.connect = original_sqlite_connect  # type: ignore[method-assign]

    assert candidates
    worker_ids = {observed[key] for key in ("connect", "execute", "fetchall", "close")}
    assert len(worker_ids) == 1
    assert loop_ident not in worker_ids
