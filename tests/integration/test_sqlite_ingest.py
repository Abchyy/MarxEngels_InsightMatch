from pathlib import Path

import pytest

from marx_engels.ingestion.assemble import assemble_corpus
from marx_engels.ingestion.paths import CorpusLayout
from marx_engels.ingestion.sqlite_ingest import ingest_sqlite
from marx_engels.storage.sqlite import SQLiteDatabase
from tests.helpers import seed_completed_all_run
from tests.integration.test_assemble import _work_pages


@pytest.mark.integration
def test_ingest_sqlite_keeps_unverified_draft_and_local_fts(tmp_path: Path) -> None:
    seed_completed_all_run(tmp_path / "corpus", volume_pages={1: _work_pages()}, chunk_size=3)
    layout = CorpusLayout(tmp_path / "corpus")
    assemble_corpus(layout, extraction_run_id="run_test_all")
    database = SQLiteDatabase(tmp_path / "corpus.db")
    report = ingest_sqlite(layout, database, replace=True)
    assert report["passages_ingested"] >= 1
    assert report["passages_verified"] == 0
    assert report["passages_unverified"] == report["passages_ingested"]
    assert report["index_outbox"] == 0
    assert report["local_fts_rows"] == report["passages_ingested"]
    assert report["quotation_policy"] == "unverified_not_formal_quotation"
    with database.connect() as connection:
        statuses = {
            row[0] for row in connection.execute("SELECT verification_status FROM passage")
        }
        releases = {row[0] for row in connection.execute("SELECT release_status FROM passage")}
        outbox = connection.execute("SELECT COUNT(*) FROM index_outbox").fetchone()
        release = connection.execute("SELECT status FROM data_release").fetchone()
        fts = connection.execute("SELECT COUNT(*) FROM passage_fts").fetchone()
        verified = connection.execute(
            "SELECT COUNT(*) FROM passage WHERE verification_status = 'verified'"
        ).fetchone()
        assert statuses == {"unverified"}
        assert releases == {"draft"}
        assert outbox is not None and outbox[0] == 0
        assert release is not None and release[0] == "draft"
        assert verified is not None and verified[0] == 0
        assert fts is not None and fts[0] == report["passages_ingested"]
        assert connection.execute("SELECT COUNT(*) FROM page_map").fetchone()[0] >= 1
        assert connection.execute("SELECT COUNT(*) FROM work").fetchone()[0] >= 1
        assert connection.execute("SELECT COUNT(*) FROM section").fetchone()[0] >= 1
