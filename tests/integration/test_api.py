import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response

from marx_engels.api.app import create_app
from marx_engels.contracts import SearchMode, SearchResponse
from marx_engels.settings import Settings
from marx_engels.storage import SQLiteDatabase
from tests.synthetic_corpus.builder import build_synthetic_corpus

FORBIDDEN_EVIDENCE_IDS = {
    "ev_syn_unpublished_001",
    "ev_syn_unverified_001",
    "ev_syn_decoy_001",
}


def request(app, method: str, path: str, *, json: dict[str, object] | None = None) -> Response:  # type: ignore[no-untyped-def]
    async def send() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=json)

    return asyncio.run(send())


def test_live_and_openapi_contract() -> None:
    app = create_app()
    response = request(app, "GET", "/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    paths = request(app, "GET", "/openapi.json").json()["paths"]
    operation_ids = {
        operation[method]["operationId"]
        for operation in paths.values()
        for method in operation
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert {"health_live", "search", "suggest_query_mode", "get_evidence"} <= operation_ids
    search_operation = paths["/api/v1/search"]["post"]
    assert search_operation["operationId"] == "search"


@pytest.mark.integration
def test_ready_after_migration(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "corpus.db"
    SQLiteDatabase(database_path).migrate(root / "migrations")
    settings = Settings(sqlite_database_path=database_path)
    response = request(create_app(settings=settings), "GET", "/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"sqlite": True, "contract_v1": True},
    }


@pytest.mark.integration
def test_exact_without_data_version_fails_closed(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version=None,
        active_index_version=None,
    )
    payload = {
        "query": "劳动",
        "mode": "exact",
        "scope": {"corpus_ids": ["synthetic_mecw_test"]},
    }
    response = request(create_app(settings=settings), "POST", "/api/v1/search", json=payload)
    assert response.status_code == 501
    body = response.json()
    assert body["error"]["code"] == "STORAGE_NOT_CONFIGURED"
    assert body["request_id"].startswith("req_")


@pytest.mark.integration
def test_unimplemented_modes_keep_uniform_error_contract() -> None:
    payload_scope = {"corpus_ids": ["synthetic_mecw_test"]}
    app = create_app()
    for mode in ("claim", "timeline", "thematic"):
        response = request(
            app,
            "POST",
            "/api/v1/search",
            json={"query": "劳动", "mode": mode, "scope": payload_scope},
        )
        assert response.status_code == 501
        body = response.json()
        assert body["error"]["code"] == "PIPELINE_NOT_IMPLEMENTED"
        assert body["error"]["details"]["mode"] == mode
        assert body["request_id"].startswith("req_")


@pytest.mark.integration
def test_exact_search_returns_two_synthetic_authoritative_evidence(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        active_index_version=None,
        app_env="test",
    )
    app = create_app(settings=settings)
    response = request(
        app,
        "POST",
        "/api/v1/search",
        json={
            "query": "劳动",
            "mode": "exact",
            "scope": {"corpus_ids": ["synthetic_mecw_test"]},
        },
    )
    assert response.status_code == 200
    parsed = SearchResponse.model_validate(response.json())
    ids = [item.evidence_id for item in parsed.evidence]
    assert ids == ["ev_syn_early_001", "ev_syn_mid_002"]
    assert parsed.mode is SearchMode.EXACT
    assert parsed.query == "劳动"
    assert parsed.scope_snapshot.corpus_ids == ["synthetic_mecw_test"]
    assert parsed.release.data_version == "data_synthetic_v1"
    assert parsed.release.index_version is None
    assert parsed.next_cursor is None
    assert parsed.overview.evidence_count == 2
    assert parsed.overview.work_count == 2
    assert parsed.overview.volume_count == 1
    assert [item.exact_match_count for item in parsed.evidence] == [2, 1]
    assert all(item.verified_text.startswith("【合成数据，非原典】") for item in parsed.evidence)
    assert FORBIDDEN_EVIDENCE_IDS.isdisjoint(ids)
    dumped = response.text
    assert "search_text" not in dumped
    assert "[合成语料]" not in dumped

    for mode in ("claim", "timeline", "thematic"):
        other = request(
            app,
            "POST",
            "/api/v1/search",
            json={
                "query": "劳动",
                "mode": mode,
                "scope": {"corpus_ids": ["synthetic_mecw_test"]},
            },
        )
        assert other.status_code == 501
        assert other.json()["error"]["code"] == "PIPELINE_NOT_IMPLEMENTED"


@pytest.mark.integration
def test_exact_search_invalid_scope_is_not_an_empty_hit_list(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        app_env="test",
    )
    response = request(
        create_app(settings=settings),
        "POST",
        "/api/v1/search",
        json={
            "query": "劳动",
            "mode": "exact",
            "scope": {
                "corpus_ids": ["synthetic_mecw_test"],
                "volume_ids": ["syn_v01"],
                "work_ids": ["syn_work_late"],
            },
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SCOPE"


@pytest.mark.integration
def test_decoy_scope_with_main_data_release_is_mismatch(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        app_env="test",
    )
    response = request(
        create_app(settings=settings),
        "POST",
        "/api/v1/search",
        json={
            "query": "劳动",
            "mode": "exact",
            "scope": {"corpus_ids": ["synthetic_scope_decoy"]},
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "RELEASE_MISMATCH"
    assert body["error"]["details"]["data_version"] == "data_synthetic_v1"
    assert "evidence" not in body
    assert "ev_syn_decoy_001" not in response.text
    assert "data_synthetic_decoy_v1" not in response.text
