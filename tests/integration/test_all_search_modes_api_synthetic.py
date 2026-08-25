from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from marx_engels.api.app import create_app
from marx_engels.api.container import build_container
from marx_engels.contracts import (
    DatePrecision,
    SearchMode,
    SearchResponse,
    SearchScope,
    SupportLabel,
)
from marx_engels.pipelines import (
    ClaimPipeline,
    ExactPipeline,
    ThematicPipeline,
    TimelinePipeline,
)
from marx_engels.pipelines.stub import UnimplementedPipeline
from marx_engels.pipelines.thematic_types import CLASSIFICATION_NOTICE
from marx_engels.settings import Settings
from tests.integration.four_mode_synthetic_container import (
    FORBIDDEN_EVIDENCE_IDS,
    SYNTHETIC_TEXT_MARK,
    build_four_mode_test_container,
    load_mode_cases,
)
from tests.synthetic_corpus.builder import build_synthetic_corpus

SEARCH_PATH = "/api/v1/search"


def request(app: object, method: str, path: str, *, json: dict[str, object]) -> Response:
    async def send() -> Response:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=json)

    return asyncio.run(send())


def _payload(case: Mapping[str, Any], *, page_size: int = 10) -> dict[str, object]:
    return {
        "query": case["query"],
        "mode": case["mode"],
        "scope": case["scope"],
        "page_size": page_size,
    }


def _assert_shared_search_contract(
    response: Response,
    *,
    case: Mapping[str, Any],
    expected_mode: SearchMode,
) -> SearchResponse:
    assert response.status_code == 200
    parsed = SearchResponse.model_validate(response.json())
    assert parsed.mode is expected_mode
    assert parsed.mode.value == case["mode"]
    assert parsed.query == case["query"]
    assert parsed.scope_snapshot == SearchScope.model_validate(case["scope"])
    assert parsed.release.data_version == "data_synthetic_v1"
    assert parsed.release.index_version == "idx_synthetic_v1"
    assert parsed.release.embedding_model == "deterministic-4d-v1"
    ids = [item.evidence_id for item in parsed.evidence]
    assert FORBIDDEN_EVIDENCE_IDS.isdisjoint(ids)
    assert all(item.verified_text.startswith(SYNTHETIC_TEXT_MARK) for item in parsed.evidence)
    grouped = [evidence_id for group in parsed.groups for evidence_id in group.evidence_ids]
    assert set(grouped) <= set(ids)
    assert parsed.overview.evidence_count == len(parsed.evidence)
    dumped = response.text
    assert "search_text" not in dumped
    assert "[合成语料]" not in dumped
    return parsed


@pytest.mark.integration
def test_all_search_modes_share_one_fastapi_search_endpoint(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        active_index_version="idx_synthetic_v1",
        app_env="test",
    )
    container = build_four_mode_test_container(build.database.path, settings=settings)
    assert isinstance(container.pipelines.get(SearchMode.EXACT), ExactPipeline)
    assert isinstance(container.pipelines.get(SearchMode.CLAIM), ClaimPipeline)
    assert isinstance(container.pipelines.get(SearchMode.TIMELINE), TimelinePipeline)
    assert isinstance(container.pipelines.get(SearchMode.THEMATIC), ThematicPipeline)

    app = create_app(settings=settings, container=container)
    cases = load_mode_cases()

    exact_case = cases[SearchMode.EXACT]
    exact_response = request(app, "POST", SEARCH_PATH, json=_payload(exact_case))
    exact = _assert_shared_search_contract(
        exact_response, case=exact_case, expected_mode=SearchMode.EXACT
    )
    assert [item.evidence_id for item in exact.evidence] == list(
        exact_case["expected_evidence_ids"]
    )
    assert [item.exact_match_count for item in exact.evidence] == [2, 1]
    assert all(item.exact_match_count and item.exact_match_count >= 1 for item in exact.evidence)
    assert exact.groups == []

    paged_exact = request(
        app,
        "POST",
        SEARCH_PATH,
        json=_payload(exact_case, page_size=1),
    )
    paged_exact_parsed = _assert_shared_search_contract(
        paged_exact, case=exact_case, expected_mode=SearchMode.EXACT
    )
    assert [item.evidence_id for item in paged_exact_parsed.evidence] == ["ev_syn_early_001"]
    assert paged_exact_parsed.overview.evidence_count == 1

    claim_case = cases[SearchMode.CLAIM]
    claim_response = request(app, "POST", SEARCH_PATH, json=_payload(claim_case))
    claim = _assert_shared_search_contract(
        claim_response, case=claim_case, expected_mode=SearchMode.CLAIM
    )
    assert [item.evidence_id for item in claim.evidence] == list(
        claim_case["expected_evidence_ids"]
    )
    by_id = {item.evidence_id: item for item in claim.evidence}
    expected_labels = dict(claim_case["expected_labels"])
    assert by_id["ev_syn_early_001"].support_label is SupportLabel.DIRECT
    assert by_id["ev_syn_mid_002"].support_label is SupportLabel.COUNTER
    assert {item.support_label for item in claim.evidence} <= {
        SupportLabel.DIRECT,
        SupportLabel.INDIRECT,
        SupportLabel.CONTEXT_ONLY,
        SupportLabel.COUNTER,
    }
    assert SupportLabel.IRRELEVANT not in {item.support_label for item in claim.evidence}
    groups_by_id = {group.group_id: group for group in claim.groups}
    assert groups_by_id["direct"].evidence_ids == ["ev_syn_early_001"]
    assert groups_by_id["counter"].evidence_ids == ["ev_syn_mid_002"]
    for evidence_id, label in expected_labels.items():
        assert by_id[evidence_id].support_label.value == label

    timeline_case = cases[SearchMode.TIMELINE]
    timeline_response = request(app, "POST", SEARCH_PATH, json=_payload(timeline_case))
    timeline = _assert_shared_search_contract(
        timeline_response, case=timeline_case, expected_mode=SearchMode.TIMELINE
    )
    assert [item.evidence_id for item in timeline.evidence] == list(
        timeline_case["expected_evidence_ids"]
    )
    precision = {item.evidence_id: item.date_precision for item in timeline.evidence}
    assert precision["ev_syn_disputed_001"] is DatePrecision.DISPUTED
    assert precision["ev_syn_unknown_001"] is DatePrecision.UNKNOWN
    disputed = next(item for item in timeline.evidence if item.evidence_id == "ev_syn_disputed_001")
    unknown = next(item for item in timeline.evidence if item.evidence_id == "ev_syn_unknown_001")
    assert disputed.work_date_start is None
    assert disputed.work_date_end is None
    assert unknown.work_date_start is None
    assert unknown.work_date_end is None
    group_ids = [group.group_id for group in timeline.groups]
    assert group_ids[-2:] == ["disputed", "unknown"]
    assert timeline.groups[-2].date_start is None
    assert timeline.groups[-2].date_end is None
    assert timeline.groups[-2].date_precision is DatePrecision.DISPUTED
    assert timeline.groups[-1].date_start is None
    assert timeline.groups[-1].date_end is None
    assert timeline.groups[-1].date_precision is DatePrecision.UNKNOWN
    known_groups = timeline.groups[:-2]
    assert known_groups
    assert all(group.date_start is not None for group in known_groups)

    paged_timeline = request(
        app,
        "POST",
        SEARCH_PATH,
        json=_payload(timeline_case, page_size=3),
    )
    paged_timeline_parsed = _assert_shared_search_contract(
        paged_timeline, case=timeline_case, expected_mode=SearchMode.TIMELINE
    )
    assert [item.evidence_id for item in paged_timeline_parsed.evidence] == [
        "ev_syn_early_002",
        "ev_syn_mid_001",
        "ev_syn_late_001",
    ]
    assert "disputed" not in {group.group_id for group in paged_timeline_parsed.groups}

    thematic_case = cases[SearchMode.THEMATIC]
    thematic_response = request(app, "POST", SEARCH_PATH, json=_payload(thematic_case))
    thematic = _assert_shared_search_contract(
        thematic_response, case=thematic_case, expected_mode=SearchMode.THEMATIC
    )
    expected = list(thematic_case["expected_evidence_ids"])
    assert {item.evidence_id for item in thematic.evidence} == set(expected)
    grouped_ids = [evidence_id for group in thematic.groups for evidence_id in group.evidence_ids]
    assert len(grouped_ids) == len(set(grouped_ids))
    assert set(grouped_ids) == set(expected)
    assert thematic.classification_notice == CLASSIFICATION_NOTICE
    labels = dict(thematic_case["expected_labels"])
    by_group = {group.label: set(group.evidence_ids) for group in thematic.groups}
    assert by_group["institutions"] == {
        evidence_id for evidence_id, label in labels.items() if label == "institutions"
    }
    assert by_group["relations"] == {
        evidence_id for evidence_id, label in labels.items() if label == "relations"
    }
    for group in thematic.groups:
        assert group.evidence_ids
        assert set(group.evidence_ids) <= set(expected)


def test_default_container_does_not_enable_test_pipeline_adapters() -> None:
    production = build_container(Settings(app_env="production"))
    local = build_container(Settings(app_env="local"))
    for container in (production, local):
        assert isinstance(container.pipelines.get(SearchMode.EXACT), ExactPipeline)
        assert isinstance(container.pipelines.get(SearchMode.CLAIM), UnimplementedPipeline)
        assert isinstance(container.pipelines.get(SearchMode.TIMELINE), UnimplementedPipeline)
        assert isinstance(container.pipelines.get(SearchMode.THEMATIC), UnimplementedPipeline)
        assert not isinstance(container.pipelines.get(SearchMode.CLAIM), ClaimPipeline)
        assert not isinstance(container.pipelines.get(SearchMode.TIMELINE), TimelinePipeline)
        assert not isinstance(container.pipelines.get(SearchMode.THEMATIC), ThematicPipeline)
