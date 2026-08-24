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
    SearchOverview,
    SearchRequest,
    SearchScope,
    SupportLabel,
)
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines.claim import ClaimPipeline
from marx_engels.retrieval_core import AuthoritativeEvidenceRecord
from marx_engels.storage import SQLiteDatabase
from tests.synthetic_corpus.builder import FIXTURE_ROOT, build_synthetic_corpus

pytestmark = pytest.mark.integration

_AUTHOR_NAMES = {
    "marx": "马克思",
    "engels": "恩格斯",
    "coauthored": "马克思和恩格斯",
}


class _IdentityScopeResolver:
    async def resolve(self, scope: SearchScope) -> SearchScope:
        return scope


class _StaticLexicalIndex:
    def __init__(self, hits: Sequence[Candidate]) -> None:
        self.hits = list(hits)

    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del query, scope, limit
        return list(self.hits)


class _StaticVectorIndex:
    def __init__(self, hits: Sequence[Candidate]) -> None:
        self.hits = list(hits)

    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del vector, scope, limit
        return list(self.hits)


class _StaticEmbedding:
    def __init__(self, vector: Sequence[float]) -> None:
        self.vector = list(vector)

    @property
    def model_version(self) -> str:
        return "synthetic-embed"

    @property
    def dimension(self) -> int:
        return len(self.vector)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        del texts
        return [list(self.vector)]


class _IdentityReranker:
    @property
    def model_version(self) -> str:
        return "synthetic-rerank"

    async def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        del query
        return list(candidates)


class _StaticClassifier:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = dict(payload)

    @property
    def model_version(self) -> str:
        return "synthetic-llm"

    async def generate_structured(
        self, task: str, payload: dict[str, object]
    ) -> dict[str, object]:
        del task, payload
        return dict(self.payload)


class _StaticRelease:
    async def snapshot_for(self, scope: SearchScope) -> ReleaseInfo:
        del scope
        return ReleaseInfo(
            data_version="data_synthetic_v1",
            index_version="idx_synthetic_v1",
            embedding_model="deterministic-4d-v1",
            released_at="2026-08-24T00:00:00Z",
        )


class _IdOverview:
    def __init__(self, work_ids: Mapping[str, str], volume_ids: Mapping[str, str]) -> None:
        self.work_ids = dict(work_ids)
        self.volume_ids = dict(volume_ids)
        self.calls: list[tuple[str, ...]] = []

    async def overview_for(self, evidence_ids: Sequence[str]) -> SearchOverview:
        self.calls.append(tuple(evidence_ids))
        return SearchOverview(
            evidence_count=len(tuple(evidence_ids)),
            work_count=len({self.work_ids[item] for item in evidence_ids if item in self.work_ids}),
            volume_count=len(
                {self.volume_ids[item] for item in evidence_ids if item in self.volume_ids}
            ),
        )


class SyntheticSqliteRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    async def get_by_ids(
        self, evidence_ids: Sequence[str]
    ) -> dict[str, AuthoritativeEvidenceRecord]:
        if not evidence_ids:
            return {}
        placeholders = ",".join("?" * len(evidence_ids))
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    p.evidence_id,
                    p.verified_text,
                    p.text_hash,
                    p.verification_status,
                    p.release_status,
                    p.content_type,
                    w.author_code,
                    w.title AS work_title,
                    w.work_id,
                    w.work_date_start,
                    w.work_date_end,
                    w.date_precision,
                    w.verification_status AS work_verification_status,
                    w.release_status AS work_release_status,
                    s.verification_status AS section_verification_status,
                    c.corpus_id,
                    c.name AS corpus_name,
                    c.release_status AS corpus_release_status,
                    e.edition_id,
                    e.edition_label,
                    e.release_status AS edition_release_status,
                    v.volume_id,
                    v.volume_no,
                    v.release_status AS volume_release_status,
                    p.prev_id,
                    p.next_id,
                    prev.release_status AS prev_release_status,
                    nxt.release_status AS next_release_status
                FROM passage AS p
                JOIN section AS s ON s.section_id = p.section_id
                JOIN work AS w ON w.work_id = s.work_id
                JOIN volume AS v ON v.volume_id = w.volume_id
                JOIN edition AS e ON e.edition_id = v.edition_id
                JOIN corpus AS c ON c.corpus_id = e.corpus_id
                LEFT JOIN passage AS prev ON prev.evidence_id = p.prev_id
                LEFT JOIN passage AS nxt ON nxt.evidence_id = p.next_id
                WHERE p.evidence_id IN ({placeholders})
                """,
                tuple(evidence_ids),
            ).fetchall()
            page_rows = connection.execute(
                f"""
                SELECT
                    pp.evidence_id,
                    pm.printed_page_label,
                    pm.pdf_page,
                    pm.mapping_status,
                    pp.order_no
                FROM passage_page AS pp
                JOIN page_map AS pm ON pm.page_id = pp.page_id
                WHERE pp.evidence_id IN ({placeholders})
                ORDER BY pp.evidence_id, pp.order_no
                """,
                tuple(evidence_ids),
            ).fetchall()
        pages: dict[str, list[tuple[str, int, str]]] = {}
        for row in page_rows:
            pages.setdefault(str(row["evidence_id"]), []).append(
                (str(row["printed_page_label"]), int(row["pdf_page"]), str(row["mapping_status"]))
            )
        records: dict[str, AuthoritativeEvidenceRecord] = {}
        for row in rows:
            evidence_id = str(row["evidence_id"])
            page_list = pages.get(evidence_id, [])
            records[evidence_id] = AuthoritativeEvidenceRecord(
                evidence_id=evidence_id,
                verified_text=str(row["verified_text"]),
                text_hash=str(row["text_hash"]),
                verification_status=str(row["verification_status"]),
                release_status=str(row["release_status"]),
                content_type=str(row["content_type"]),
                author_code=str(row["author_code"]),
                author=_AUTHOR_NAMES.get(str(row["author_code"]), str(row["author_code"])),
                work_title=str(row["work_title"]),
                corpus_id=str(row["corpus_id"]),
                corpus_name=str(row["corpus_name"]),
                edition_id=str(row["edition_id"]),
                edition_label=str(row["edition_label"]),
                volume_id=str(row["volume_id"]),
                volume_no=int(row["volume_no"]),
                work_id=str(row["work_id"]),
                work_date_start=row["work_date_start"],
                work_date_end=row["work_date_end"],
                date_precision=str(row["date_precision"]),
                corpus_release_status=str(row["corpus_release_status"]),
                edition_release_status=str(row["edition_release_status"]),
                volume_release_status=str(row["volume_release_status"]),
                work_release_status=str(row["work_release_status"]),
                work_verification_status=str(row["work_verification_status"]),
                section_verification_status=str(row["section_verification_status"]),
                printed_pages=tuple(item[0] for item in page_list),
                pdf_pages=tuple(item[1] for item in page_list),
                page_mapping_statuses=tuple(item[2] for item in page_list),
                prev_evidence_id=row["prev_id"],
                next_evidence_id=row["next_id"],
                prev_is_released=row["prev_release_status"] == "published",
                next_is_released=row["next_release_status"] == "published",
            )
        return records


def _load_claim_case() -> dict[str, object]:
    path = FIXTURE_ROOT / "cases" / "claim_cases.jsonl"
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


def test_synthetic_claim_case_groups_direct_and_counter_and_blocks_decoy(
    tmp_path: Path,
) -> None:
    case = _load_claim_case()
    build = build_synthetic_corpus(tmp_path / "synthetic.db")
    repository = SyntheticSqliteRepository(build.database)
    hashes = asyncio.run(
        repository.get_by_ids(
            ["ev_syn_early_001", "ev_syn_mid_002", "ev_syn_decoy_001"]
        )
    )
    lexical = [
        Candidate(evidence_id="ev_syn_early_001", channels=["lexical"]),
        Candidate(evidence_id="ev_syn_mid_002", channels=["lexical"]),
        Candidate(evidence_id="ev_syn_decoy_001", channels=["lexical"]),
    ]
    vector = [
        Candidate(
            evidence_id="ev_syn_mid_002",
            channels=["vector"],
            vector_rank=1,
            text_hash=hashes["ev_syn_mid_002"].text_hash,
        ),
        Candidate(
            evidence_id="ev_syn_early_001",
            channels=["vector"],
            vector_rank=2,
            text_hash=hashes["ev_syn_early_001"].text_hash,
        ),
        Candidate(
            evidence_id="ev_syn_decoy_001",
            channels=["vector"],
            vector_rank=3,
            text_hash=hashes["ev_syn_decoy_001"].text_hash,
        ),
    ]
    labels = {
        "classifications": [
            {"evidence_id": evidence_id, "support_label": label}
            for evidence_id, label in dict(case["expected_labels"]).items()
        ]
        + [{"evidence_id": "ev_syn_decoy_001", "support_label": "direct"}]
    }
    overview = _IdOverview(
        {
            evidence_id: record.work_id
            for evidence_id, record in hashes.items()
        },
        {
            evidence_id: record.volume_id
            for evidence_id, record in hashes.items()
        },
    )
    pipeline = ClaimPipeline(
        scope_resolver=_IdentityScopeResolver(),
        lexical_index=_StaticLexicalIndex(lexical),
        vector_index=_StaticVectorIndex(vector),
        embedding_provider=_StaticEmbedding((0.95, 0.05, 0.0, 0.0)),
        reranker=_IdentityReranker(),
        language_model=_StaticClassifier(labels),
        evidence_service=EvidenceService(repository),
        evidence_repository=repository,
        release_provider=_StaticRelease(),
        overview_provider=overview,
    )
    request = SearchRequest.model_validate(
        {
            "query": case["query"],
            "mode": case["mode"],
            "scope": case["scope"],
        }
    )
    response = asyncio.run(pipeline.execute(request, "req_synthetic_claim"))

    assert response.mode is SearchMode.CLAIM
    assert response.query == case["query"]
    assert response.scope_snapshot == SearchScope.model_validate(case["scope"])
    assert [item.evidence_id for item in response.evidence] == list(case["expected_evidence_ids"])
    assert all(
        forbidden not in [item.evidence_id for item in response.evidence]
        for forbidden in list(case["forbidden_evidence_ids"])
    )
    by_id = {item.evidence_id: item for item in response.evidence}
    expected_labels = {
        evidence_id: SupportLabel(label)
        for evidence_id, label in dict(case["expected_labels"]).items()
    }
    assert {key: by_id[key].support_label for key in expected_labels} == expected_labels
    assert [group.group_id for group in response.groups] == ["direct", "counter"]
    assert response.groups[0].evidence_ids == ["ev_syn_early_001"]
    assert response.groups[1].evidence_ids == ["ev_syn_mid_002"]
    assert all(group.summary is None for group in response.groups)
    assert response.insufficiency is None
    assert overview.calls
    assert all(
        item.verified_text.startswith("【合成数据，非原典】") for item in response.evidence
    )
    assert all("search_text" not in item.model_dump() for item in response.evidence)
