from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response

from marx_engels.api.app import create_app
from marx_engels.contracts import SearchMode, SearchRequest, SearchScope
from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.corpus_registry.local_asset import DEFAULT_SEED_PATH, load_local_asset_manifest
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines import ExactPipeline
from marx_engels.settings import Settings
from marx_engels.storage import (
    SQLiteDatabase,
    SQLiteEvidenceRepository,
    SQLiteExactSearchIndex,
    SQLiteReleaseResolver,
    SQLiteScopeResolver,
)
from marx_engels.storage.local_publish import init_local_corpus, verify_local_sqlite_asset

pytestmark = pytest.mark.integration

QUERY = "一般智力"
EVIDENCE_ID = "ev_3ffe94d7-69e1-4687-b274-8d22b6f5b555"


def _seed_or_skip() -> Path:
    if not DEFAULT_SEED_PATH.is_file():
        pytest.skip("local Canonical SQLite seed is not present")
    return DEFAULT_SEED_PATH


@pytest.fixture(scope="module")
def published_runtime(tmp_path_factory: pytest.TempPathFactory) -> Path:
    seed = _seed_or_skip()
    spec = load_local_asset_manifest()
    before = sha256_file(seed)
    runtime = tmp_path_factory.mktemp("real-corpus") / "corpus.db"
    report = init_local_corpus(seed_path=seed, runtime_path=runtime)
    assert report["human_reviewed"] is False
    assert report["trust_policy"] == "source_derived_trusted"
    assert sha256_file(seed) == before == spec.sha256
    return runtime


def test_verify_local_asset_matches_tracked_hash() -> None:
    _seed_or_skip()
    code, message = verify_local_sqlite_asset()
    assert code == 0
    assert "human_reviewed=false" in message
    assert "17284" in message


def test_real_exact_query_hydrates_sqlite_text(published_runtime: Path) -> None:
    spec = load_local_asset_manifest()
    database = SQLiteDatabase(published_runtime)
    pipeline = ExactPipeline(
        scope_resolver=SQLiteScopeResolver(database),
        exact_index=SQLiteExactSearchIndex(database),
        evidence_service=EvidenceService(SQLiteEvidenceRepository(database)),
        release_resolver=SQLiteReleaseResolver(
            database,
            Settings(
                sqlite_database_path=published_runtime,
                active_data_version=spec.data_version,
                app_env="test",
            ),
        ),
    )
    response = asyncio.run(
        pipeline.execute(
            SearchRequest(
                query=QUERY,
                mode=SearchMode.EXACT,
                scope=SearchScope(corpus_ids=["marx_engels_collected_works_cn"]),
            ),
            "req_real_corpus",
        )
    )
    assert response.release.data_version == spec.data_version
    assert response.evidence
    assert EVIDENCE_ID in {item.evidence_id for item in response.evidence}
    with sqlite3.connect(published_runtime) as connection:
        row = connection.execute(
            "SELECT verified_text FROM passage WHERE evidence_id = ?",
            (EVIDENCE_ID,),
        ).fetchone()
    assert row is not None
    canonical = str(row[0])
    matched = next(item for item in response.evidence if item.evidence_id == EVIDENCE_ID)
    assert matched.verified_text == canonical
    assert QUERY in matched.verified_text
    assert all(QUERY in item.verified_text for item in response.evidence)


def test_real_exact_http_binds_data_version(published_runtime: Path) -> None:
    spec = load_local_asset_manifest()
    settings = Settings(
        sqlite_database_path=published_runtime,
        active_data_version=spec.data_version,
        app_env="test",
    )
    payload = {
        "query": QUERY,
        "mode": "exact",
        "scope": {"corpus_ids": ["marx_engels_collected_works_cn"]},
    }

    async def send() -> Response:
        transport = ASGITransport(app=create_app(settings=settings))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/search", json=payload)

    response = asyncio.run(send())
    assert response.status_code == 200
    body = response.json()
    assert body["release"]["data_version"] == spec.data_version
    assert body["overview"]["evidence_count"] >= 1
    assert any(QUERY in item["verified_text"] for item in body["evidence"])
    hit = next(item for item in body["evidence"] if item["evidence_id"] == EVIDENCE_ID)
    with sqlite3.connect(published_runtime) as connection:
        canonical = connection.execute(
            "SELECT verified_text FROM passage WHERE evidence_id = ?",
            (EVIDENCE_ID,),
        ).fetchone()
    assert canonical is not None
    assert hit["verified_text"] == canonical[0]
