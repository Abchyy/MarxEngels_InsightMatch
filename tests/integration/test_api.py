import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response

from marx_engels.api.app import create_app
from marx_engels.settings import Settings
from marx_engels.storage import SQLiteDatabase


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
def test_search_stub_uses_uniform_error_contract() -> None:
    payload = {
        "query": "舆论",
        "mode": "exact",
        "scope": {"corpus_ids": ["marx_engels_collected_works_cn"]},
    }
    response = request(create_app(), "POST", "/api/v1/search", json=payload)
    assert response.status_code == 501
    body = response.json()
    assert body["error"]["code"] == "PIPELINE_NOT_IMPLEMENTED"
    assert body["request_id"].startswith("req_")
