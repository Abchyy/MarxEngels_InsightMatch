from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient, Response

from marx_engels.api.container import build_container
from marx_engels.contracts import SearchMode, SearchResponse
from marx_engels.pipelines import ClaimPipeline, ExactPipeline, ThematicPipeline, TimelinePipeline
from marx_engels.pipelines.stub import UnimplementedPipeline
from marx_engels.settings import Settings
from tests.integration.four_mode_synthetic_container import (
    FORBIDDEN_EVIDENCE_IDS,
    create_synthetic_demo_app,
    load_mode_cases,
)

SEARCH_PATH = "/api/v1/search"


def request(app: object, method: str, path: str, *, json: dict[str, object]) -> Response:
    async def send() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=json)

    return asyncio.run(send())


@pytest.mark.integration
def test_synthetic_demo_app_serves_four_modes_without_search_text(tmp_path: Path) -> None:
    app = create_synthetic_demo_app(tmp_path / "demo.db")
    cases = load_mode_cases()
    for mode in (SearchMode.EXACT, SearchMode.CLAIM, SearchMode.TIMELINE, SearchMode.THEMATIC):
        case = cases[mode]
        response = request(
            app,
            "POST",
            SEARCH_PATH,
            json={
                "query": case["query"],
                "mode": case["mode"],
                "scope": case["scope"],
                "page_size": 10,
            },
        )
        assert response.status_code == 200
        parsed = SearchResponse.model_validate(response.json())
        assert parsed.mode is mode
        ids = [item.evidence_id for item in parsed.evidence]
        assert ids
        assert FORBIDDEN_EVIDENCE_IDS.isdisjoint(ids)
        assert "search_text" not in response.text
        assert "[合成语料]" not in response.text


def test_default_application_container_stays_exact_plus_three_stubs() -> None:
    for settings in (
        Settings(app_env="production"),
        Settings(app_env="staging"),
        Settings(app_env="local"),
    ):
        container = build_container(settings)
        assert isinstance(container.pipelines.get(SearchMode.EXACT), ExactPipeline)
        assert isinstance(container.pipelines.get(SearchMode.CLAIM), UnimplementedPipeline)
        assert isinstance(container.pipelines.get(SearchMode.TIMELINE), UnimplementedPipeline)
        assert isinstance(container.pipelines.get(SearchMode.THEMATIC), UnimplementedPipeline)
        assert not isinstance(container.pipelines.get(SearchMode.CLAIM), ClaimPipeline)
        assert not isinstance(container.pipelines.get(SearchMode.TIMELINE), TimelinePipeline)
        assert not isinstance(container.pipelines.get(SearchMode.THEMATIC), ThematicPipeline)
