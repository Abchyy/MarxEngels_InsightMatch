from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from marx_engels.contracts import (
    Candidate,
    ReleaseInfo,
    SearchMode,
    SearchOptions,
    SearchRequest,
    SearchResponse,
)
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines.thematic import (
    CountOverviewProvider,
    FixedReleaseProvider,
    ThematicPipeline,
)
from marx_engels.pipelines.thematic_types import (
    CLASSIFICATION_NOTICE,
    ClusterAssignment,
    ThemeLabel,
)
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord
from tests.synthetic_corpus.builder import FIXTURE_ROOT, build_synthetic_corpus, load_fixture
from tests.unit.test_thematic_pipeline import (
    FakeEmbedding,
    FakeLexicalIndex,
    FakeScopeResolver,
    FakeVectorIndex,
    ScriptedClusterer,
    ScriptedLabeler,
    ScriptedRelevanceStage,
)

pytestmark = pytest.mark.integration

THEMATIC_CASES = FIXTURE_ROOT / "cases" / "thematic_cases.jsonl"


def _load_thematic_case() -> dict[str, object]:
    payload = json.loads(THEMATIC_CASES.read_text(encoding="utf-8").splitlines()[0])
    assert isinstance(payload, dict)
    return payload


def _records_for_case(evidence_ids: Sequence[str]) -> dict[str, AuthoritativeEvidenceRecord]:
    fixture = load_fixture()
    passages = {row["evidence_id"]: row for row in fixture["passages"]}
    sections = {row["section_id"]: row for row in fixture["sections"]}
    works = {row["work_id"]: row for row in fixture["works"]}
    volumes = {row["volume_id"]: row for row in fixture["volumes"]}
    editions = {row["edition_id"]: row for row in fixture["editions"]}
    corpora = {row["corpus_id"]: row for row in fixture["corpora"]}
    pages_by_id = {row["page_id"]: row for row in fixture["pages"]}
    passage_pages: dict[str, list[dict[str, object]]] = {}
    for row in fixture["passage_pages"]:
        passage_pages.setdefault(str(row["evidence_id"]), []).append(row)

    records: dict[str, AuthoritativeEvidenceRecord] = {}
    for evidence_id in evidence_ids:
        passage = passages[evidence_id]
        section = sections[str(passage["section_id"])]
        work = works[str(section["work_id"])]
        volume = volumes[str(work["volume_id"])]
        edition = editions[str(volume["edition_id"])]
        corpus = corpora[str(edition["corpus_id"])]
        mapped = sorted(passage_pages[evidence_id], key=lambda row: int(row["order_no"]))  # type: ignore[arg-type,call-overload]
        page_rows = [pages_by_id[str(item["page_id"])] for item in mapped]
        records[evidence_id] = AuthoritativeEvidenceRecord(
            evidence_id=evidence_id,
            verified_text=str(passage["verified_text"]),
            text_hash=f"hash_{evidence_id}",
            verification_status=str(passage["verification_status"]),
            release_status=str(passage["release_status"]),
            content_type=str(passage["content_type"]),
            author_code=str(work["author_code"]),
            author=str(work["author_code"]),
            work_title=str(work["title"]),
            corpus_id=str(corpus["corpus_id"]),
            corpus_name=str(corpus["name"]),
            edition_id=str(edition["edition_id"]),
            edition_label=str(edition["edition_label"]),
            volume_id=str(volume["volume_id"]),
            volume_no=int(volume["volume_no"]),
            work_id=str(work["work_id"]),
            work_date_start=work.get("work_date_start"),  # type: ignore[arg-type]
            work_date_end=work.get("work_date_end"),  # type: ignore[arg-type]
            date_precision=str(work["date_precision"]),
            corpus_release_status=str(corpus["release_status"]),
            edition_release_status=str(edition["release_status"]),
            volume_release_status=str(volume["release_status"]),
            work_release_status=str(work["release_status"]),
            work_verification_status=str(work["verification_status"]),
            section_verification_status=str(section["verification_status"]),
            printed_pages=tuple(str(row["printed_page_label"]) for row in page_rows),
            pdf_pages=tuple(int(row["pdf_page"]) for row in page_rows),
            page_mapping_statuses=tuple(str(row["mapping_status"]) for row in page_rows),
            prev_evidence_id=passage.get("prev_id"),  # type: ignore[arg-type]
            next_evidence_id=passage.get("next_id"),  # type: ignore[arg-type]
            prev_is_released=True,
            next_is_released=True,
        )
    return records


class FixtureEvidenceRepository:
    def __init__(self, records: Mapping[str, AuthoritativeEvidenceRecord]) -> None:
        self.records = dict(records)

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        return {
            evidence_id: self.records[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.records
        }


def _assignments_from_labels(expected_labels: Mapping[str, str]) -> list[ClusterAssignment]:
    clusters: dict[str, list[str]] = {}
    for evidence_id, label in expected_labels.items():
        clusters.setdefault(label, []).append(evidence_id)
    return [
        ClusterAssignment(cluster_id=label, evidence_ids=tuple(members))
        for label, members in clusters.items()
    ]


def _pipeline_for_case(
    case: Mapping[str, object],
    *,
    assignments: Sequence[ClusterAssignment] | Exception | None = None,
    labels: Mapping[str, ThemeLabel] | Exception | None = None,
) -> ThematicPipeline:
    expected = list(case["expected_evidence_ids"])  # type: ignore[arg-type]
    forbidden = list(case["forbidden_evidence_ids"])  # type: ignore[arg-type]
    expected_labels = dict(case["expected_labels"])  # type: ignore[arg-type]
    records = _records_for_case([*expected, *forbidden])
    repository = FixtureEvidenceRepository(records)
    resolved_assignments = (
        _assignments_from_labels(expected_labels) if assignments is None else assignments
    )
    resolved_labels: Mapping[str, ThemeLabel] | Exception | None
    if labels is None:
        resolved_labels = {
            label: ThemeLabel(
                cluster_id=label,
                label=label,
                evidence_ids=tuple(
                    evidence_id for evidence_id, value in expected_labels.items() if value == label
                ),
            )
            for label in dict.fromkeys(expected_labels.values())
        }
    else:
        resolved_labels = labels
    lexical = [Candidate(evidence_id=evidence_id, channels=["lexical"]) for evidence_id in expected]
    lexical.append(Candidate(evidence_id=forbidden[0], channels=["lexical"]))
    return ThematicPipeline(
        scope_resolver=FakeScopeResolver(),
        lexical_index=FakeLexicalIndex(lexical),
        vector_index=FakeVectorIndex([]),
        embedding=FakeEmbedding(),
        evidence_service=EvidenceService(repository),
        relevance_stage=ScriptedRelevanceStage(),
        clusterer=ScriptedClusterer(resolved_assignments),
        labeler=None if resolved_labels is None else ScriptedLabeler(resolved_labels),
        release_provider=FixedReleaseProvider(
            ReleaseInfo(
                data_version="data_synthetic_v1",
                index_version="idx_synthetic_v1",
                embedding_model="deterministic-4d-v1",
            )
        ),
        overview_provider=CountOverviewProvider(repository),
    )


def _execute(pipeline: ThematicPipeline, case: Mapping[str, object]) -> SearchResponse:
    request = SearchRequest.model_validate(
        {
            "query": case["query"],
            "mode": SearchMode.THEMATIC,
            "scope": case["scope"],
        }
    )
    return asyncio.run(pipeline.execute(request, "req_synthetic_thematic"))


def test_synthetic_thematic_case_is_exclusive_and_scope_safe(tmp_path: Path) -> None:
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    assert build.fixture_version == "synthetic_corpus_v1"
    case = _load_thematic_case()
    response = _execute(_pipeline_for_case(case), case)
    SearchResponse.model_validate(response.model_dump())

    expected = set(case["expected_evidence_ids"])  # type: ignore[arg-type]
    forbidden = set(case["forbidden_evidence_ids"])  # type: ignore[arg-type]
    grouped = [evidence_id for group in response.groups for evidence_id in group.evidence_ids]
    assert set(grouped) == expected
    assert len(grouped) == len(expected)
    assert forbidden.isdisjoint(grouped)
    assert {item.evidence_id for item in response.evidence} == expected
    assert response.classification_notice == CLASSIFICATION_NOTICE
    labels = dict(case["expected_labels"])  # type: ignore[arg-type]
    by_group = {group.label: set(group.evidence_ids) for group in response.groups}
    assert by_group["institutions"] == {
        evidence_id for evidence_id, label in labels.items() if label == "institutions"
    }
    assert by_group["relations"] == {
        evidence_id for evidence_id, label in labels.items() if label == "relations"
    }


def test_synthetic_other_related_keeps_unclustered_expected_ids() -> None:
    case = _load_thematic_case()
    expected = list(case["expected_evidence_ids"])  # type: ignore[arg-type]
    pipeline = _pipeline_for_case(
        case,
        assignments=[ClusterAssignment("institutions", (expected[0], expected[1]))],
        labels={
            "institutions": ThemeLabel(
                cluster_id="institutions",
                label="institutions",
                evidence_ids=(expected[0], expected[1]),
            )
        },
    )
    response = _execute(pipeline, case)
    leftover = expected[2]
    assert response.groups[-1].group_id == "other_related"
    assert leftover in response.groups[-1].evidence_ids
    assert leftover in {item.evidence_id for item in response.evidence}


def test_synthetic_model_off_keeps_evidence_with_fallback_labels() -> None:
    case = _load_thematic_case()
    pipeline = _pipeline_for_case(case)
    request = SearchRequest.model_validate(
        {
            "query": case["query"],
            "mode": SearchMode.THEMATIC,
            "scope": case["scope"],
            "options": SearchOptions(include_generated_summaries=False),
        }
    )
    response = asyncio.run(pipeline.execute(request, "req_synthetic_thematic_off"))
    assert all(
        group.label.startswith("主题 ") or group.group_id == "other_related"
        for group in response.groups
    )
    assert {item.evidence_id for item in response.evidence} == set(case["expected_evidence_ids"])  # type: ignore[arg-type]
    assert all(group.summary is None for group in response.groups)
    assert response.classification_notice == CLASSIFICATION_NOTICE


def test_synthetic_clusterer_failure_is_partial_not_empty() -> None:
    case = _load_thematic_case()
    pipeline = _pipeline_for_case(case, assignments=RuntimeError("synthetic clusterer down"))
    response = _execute(pipeline, case)
    assert response.groups[0].group_id == "other_related"
    assert set(response.groups[0].evidence_ids) == set(case["expected_evidence_ids"])  # type: ignore[arg-type]
    assert any(warning.code == "CLUSTERING_UNAVAILABLE" for warning in response.warnings)
    assert response.classification_notice == CLASSIFICATION_NOTICE
    assert response.insufficiency is None
