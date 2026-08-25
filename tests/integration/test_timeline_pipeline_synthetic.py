import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from marx_engels.contracts import (
    AuthorCode,
    Candidate,
    ContentType,
    DatePrecision,
    Evidence,
    ReleaseInfo,
    SearchMode,
    SearchOverview,
    SearchRequest,
    SearchResponse,
    SearchScope,
)
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines.timeline import TimelinePipeline
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord
from tests.synthetic_corpus.builder import FIXTURE_ROOT

CASE_PATH = FIXTURE_ROOT / "cases" / "timeline_cases.jsonl"
CORPUS_ID = "synthetic_mecw_test"


class IdentityResolver:
    async def resolve(self, scope: SearchScope) -> SearchScope:
        return scope


class ScriptedLexical:
    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self.candidates = list(candidates)

    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del query, scope, limit
        return list(self.candidates)


class ScriptedVector:
    def __init__(self, candidates: Sequence[Candidate]) -> None:
        self.candidates = list(candidates)

    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del vector, scope, limit
        return list(self.candidates)


class ScriptedEmbedding:
    model_version = "deterministic-4d-v1"
    dimension = 4

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.05, 0.95, 0.0, 0.0] for _ in texts]


class ScriptedRelease:
    def release_for(self, scope: SearchScope) -> ReleaseInfo:
        del scope
        return ReleaseInfo(
            data_version="data_synthetic_v1",
            index_version="idx_synthetic_v1",
            embedding_model="deterministic-4d-v1",
        )


@dataclass
class ScriptedOverview:
    work_ids: dict[str, str]
    volume_ids: dict[str, str]

    def overview(self, evidence: Sequence[Evidence]) -> SearchOverview:
        return SearchOverview(
            evidence_count=len(evidence),
            work_count=len({self.work_ids[item.evidence_id] for item in evidence}),
            volume_count=len({self.volume_ids[item.evidence_id] for item in evidence}),
        )


class ScriptedRepository:
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


def _record(evidence_id: str, **overrides: object) -> AuthoritativeEvidenceRecord:
    record = AuthoritativeEvidenceRecord(
        evidence_id=evidence_id,
        verified_text="【合成数据，非原典】公共讨论。",
        text_hash=f"hash_{evidence_id}",
        verification_status="verified",
        release_status="published",
        content_type=ContentType.MAIN_TEXT.value,
        author_code=AuthorCode.MARX.value,
        author="马克思",
        work_title="合成著作",
        corpus_id=CORPUS_ID,
        corpus_name="合成测试语料",
        edition_id="synthetic_edition_v1",
        edition_label="合成测试版",
        volume_id="syn_v01",
        volume_no=1,
        work_id="syn_work_early",
        work_date_start="1845",
        work_date_end="1845",
        date_precision=DatePrecision.YEAR.value,
        corpus_release_status="published",
        edition_release_status="published",
        volume_release_status="published",
        work_release_status="published",
        work_verification_status="verified",
        section_verification_status="verified",
        printed_pages=("1",),
        pdf_pages=(10,),
        page_mapping_statuses=("verified",),
        prev_evidence_id=None,
        next_evidence_id=None,
        prev_is_released=False,
        next_is_released=False,
    )
    return replace(record, **overrides)  # type: ignore[arg-type]


def _candidate(evidence_id: str, channel: str, rank: int) -> Candidate:
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "channels": [channel],
        "text_hash": f"hash_{evidence_id}",
    }
    if channel == "lexical":
        payload["lexical_rank"] = rank
    else:
        payload["vector_rank"] = rank
    return Candidate.model_validate(payload)


def synthetic_records() -> dict[str, AuthoritativeEvidenceRecord]:
    return {
        "ev_syn_early_002": _record("ev_syn_early_002", work_id="syn_work_early"),
        "ev_syn_mid_001": _record(
            "ev_syn_mid_001",
            work_id="syn_work_mid",
            work_date_start="1852-01",
            work_date_end="1852-12",
            date_precision=DatePrecision.RANGE.value,
        ),
        "ev_syn_late_001": _record(
            "ev_syn_late_001",
            work_id="syn_work_late",
            volume_id="syn_v02",
            volume_no=2,
            work_date_start="1878",
            work_date_end=None,
            date_precision=DatePrecision.APPROXIMATE.value,
        ),
        "ev_syn_disputed_001": _record(
            "ev_syn_disputed_001",
            work_id="syn_work_disputed",
            work_date_start=None,
            work_date_end=None,
            date_precision=DatePrecision.DISPUTED.value,
        ),
        "ev_syn_unknown_001": _record(
            "ev_syn_unknown_001",
            work_id="syn_work_unknown",
            volume_id="syn_v02",
            volume_no=2,
            work_date_start=None,
            work_date_end=None,
            date_precision=DatePrecision.UNKNOWN.value,
        ),
        "ev_syn_decoy_001": _record(
            "ev_syn_decoy_001",
            corpus_id="synthetic_scope_decoy",
            work_id="syn_decoy_work",
            volume_id="syn_decoy_v01",
        ),
        "ev_syn_unpublished_001": _record(
            "ev_syn_unpublished_001",
            work_id="syn_work_unknown",
            release_status="draft",
        ),
        "ev_syn_unverified_001": _record(
            "ev_syn_unverified_001",
            work_id="syn_work_unknown",
            verification_status="initial_review",
        ),
    }


def load_timeline_case() -> dict[str, object]:
    line = Path(CASE_PATH).read_text(encoding="utf-8").splitlines()[0]
    return json.loads(line)


@pytest.mark.integration
def test_synthetic_timeline_case_orders_known_dates_before_disputed_and_unknown() -> None:
    case = load_timeline_case()
    records = synthetic_records()
    recalled = [
        "ev_syn_unknown_001",
        "ev_syn_decoy_001",
        "ev_syn_late_001",
        "ev_syn_unpublished_001",
        "ev_syn_early_002",
        "ev_syn_disputed_001",
        "ev_syn_mid_001",
        "ev_syn_unverified_001",
    ]
    lexical = [
        _candidate(evidence_id, "lexical", rank)
        for rank, evidence_id in enumerate(recalled, start=1)
    ]
    vector = [
        _candidate("ev_syn_early_002", "vector", 1),
        _candidate("ev_syn_late_001", "vector", 2),
    ]
    work_ids = {evidence_id: record.work_id for evidence_id, record in records.items()}
    volume_ids = {evidence_id: record.volume_id for evidence_id, record in records.items()}
    pipeline = TimelinePipeline(
        scope_resolver=IdentityResolver(),
        lexical_index=ScriptedLexical(lexical),
        vector_index=ScriptedVector(vector),
        embedding_provider=ScriptedEmbedding(),
        evidence_service=EvidenceService(ScriptedRepository(records)),
        release_provider=ScriptedRelease(),
        overview_provider=ScriptedOverview(work_ids, volume_ids),
    )
    request = SearchRequest(
        query=str(case["query"]),
        mode=SearchMode.TIMELINE,
        scope=SearchScope.model_validate(case["scope"]),
    )
    response = asyncio.run(pipeline.execute(request, "req_synthetic_timeline"))

    expected = list(case["expected_evidence_ids"])
    assert [item.evidence_id for item in response.evidence] == expected
    forbidden = set(case["forbidden_evidence_ids"])
    assert forbidden.isdisjoint({item.evidence_id for item in response.evidence})
    assert "ev_syn_unpublished_001" not in {item.evidence_id for item in response.evidence}
    assert "ev_syn_unverified_001" not in {item.evidence_id for item in response.evidence}

    labels = {item.evidence_id: item.date_precision.value for item in response.evidence}
    assert labels["ev_syn_disputed_001"] == case["expected_labels"]["ev_syn_disputed_001"]
    assert labels["ev_syn_unknown_001"] == case["expected_labels"]["ev_syn_unknown_001"]
    assert response.groups[-2].date_start is None
    assert response.groups[-1].date_start is None
    assert response.groups[-2].date_precision is DatePrecision.DISPUTED
    assert response.groups[-1].date_precision is DatePrecision.UNKNOWN
    assert response.mode is SearchMode.TIMELINE
    assert response.release.data_version == "data_synthetic_v1"
    assert response.overview.evidence_count == 5
    assert response.insufficiency is None
    SearchRequest.model_validate(request.model_dump())
    SearchResponse.model_validate(response.model_dump())
