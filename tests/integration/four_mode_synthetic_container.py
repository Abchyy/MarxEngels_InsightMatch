"""Test-only composition of four real pipelines against a temporary SQLite corpus.

These adapters are never imported by the production ApplicationContainer.
They consume existing synthetic cases and SQLite authority records; they do
not invent corpus facts, evidence IDs, or SearchResponse quotations.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from marx_engels.api.app import create_app
from marx_engels.api.container import ApplicationContainer
from marx_engels.contracts import (
    Candidate,
    Evidence,
    ReleaseInfo,
    SearchMode,
    SearchOverview,
    SearchScope,
    SupportLabel,
)
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines import (
    ClaimPipeline,
    ExactPipeline,
    PipelineRegistry,
    ThematicPipeline,
    TimelinePipeline,
)
from marx_engels.pipelines.thematic import CountOverviewProvider, FixedReleaseProvider
from marx_engels.pipelines.thematic_types import ClusterAssignment, ThemeLabel
from marx_engels.settings import Settings
from marx_engels.storage import (
    SQLiteDatabase,
    SQLiteEvidenceRepository,
    SQLiteExactSearchIndex,
    SQLiteReleaseResolver,
    SQLiteScopeResolver,
)
from tests.synthetic_corpus.builder import FIXTURE_ROOT, build_synthetic_corpus

SYNTHETIC_TEXT_MARK = "【合成数据，非原典】"
FORBIDDEN_EVIDENCE_IDS = frozenset(
    {
        "ev_syn_unpublished_001",
        "ev_syn_unverified_001",
        "ev_syn_decoy_001",
    }
)
_RECALL_GATES = (
    "ev_syn_unpublished_001",
    "ev_syn_unverified_001",
    "ev_syn_decoy_001",
)


def load_first_case(filename: str) -> dict[str, Any]:
    path = FIXTURE_ROOT / "cases" / filename
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert isinstance(payload, dict)
    return payload


def load_mode_cases() -> dict[SearchMode, dict[str, Any]]:
    return {
        SearchMode.EXACT: load_first_case("exact_cases.jsonl"),
        SearchMode.CLAIM: load_first_case("claim_cases.jsonl"),
        SearchMode.TIMELINE: load_first_case("timeline_cases.jsonl"),
        SearchMode.THEMATIC: load_first_case("thematic_cases.jsonl"),
    }


class QueryScopedLexicalIndex:
    """Returns scripted lexical hits only for the query that owns this pipeline."""

    def __init__(self, hits_by_query: Mapping[str, Sequence[Candidate]]) -> None:
        self._hits_by_query = {query: list(hits) for query, hits in hits_by_query.items()}

    async def search_lexical(
        self, query: str, scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del scope
        return list(self._hits_by_query.get(query, []))[:limit]


class StaticVectorIndex:
    def __init__(self, hits: Sequence[Candidate]) -> None:
        self._hits = list(hits)

    async def search_vector(
        self, vector: Sequence[float], scope: SearchScope, limit: int
    ) -> list[Candidate]:
        del vector, scope
        return list(self._hits)[:limit]


class DeterministicEmbedding:
    model_version = "deterministic-4d-v1"
    dimension = 4

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.25, 0.25, 0.25, 0.25] for _ in texts]


class IdentityReranker:
    model_version = "test-rerank-passthrough"

    async def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        del query
        return list(candidates)


class CaseClassifier:
    """Labels recalled IDs from the frozen claim case; everything else is irrelevant."""

    model_version = "test-claim-classifier"

    def __init__(self, labels_by_id: Mapping[str, str], expected_query: str) -> None:
        self._labels_by_id = dict(labels_by_id)
        self._expected_query = expected_query

    async def generate_structured(
        self, task: str, payload: dict[str, object]
    ) -> dict[str, object]:
        del task
        candidates = payload.get("candidates", [])
        if payload.get("query") != self._expected_query:
            classifications = [
                {"evidence_id": item["evidence_id"], "support_label": "irrelevant"}
                for item in candidates  # type: ignore[union-attr]
            ]
            return {"classifications": classifications}
        classifications = []
        for item in candidates:  # type: ignore[union-attr]
            evidence_id = str(item["evidence_id"])
            classifications.append(
                {
                    "evidence_id": evidence_id,
                    "support_label": self._labels_by_id.get(evidence_id, "irrelevant"),
                }
            )
        return {"classifications": classifications}


class SqliteOverviewAdapter:
    """Counts works/volumes from SQLite authority records, never display titles."""

    def __init__(self, repository: SQLiteEvidenceRepository) -> None:
        self._repository = repository
        self._cache: dict[str, Any] = {}

    async def _records(self, evidence_ids: Sequence[str]) -> Mapping[str, Any]:
        missing = [item for item in evidence_ids if item not in self._cache]
        if missing:
            loaded = await self._repository.get_by_ids(missing)
            self._cache.update(loaded)
        return self._cache

    def _overview(self, evidence_ids: Sequence[str], records: Mapping[str, Any]) -> SearchOverview:
        present = [records[item] for item in evidence_ids if item in records]
        return SearchOverview(
            evidence_count=len(tuple(evidence_ids)),
            work_count=len({record.work_id for record in present}),
            volume_count=len({record.volume_id for record in present}),
        )

    async def overview_for(self, evidence_ids: Sequence[str]) -> SearchOverview:
        records = await self._records(evidence_ids)
        return self._overview(evidence_ids, records)

    def overview(self, evidence: Sequence[Evidence]) -> SearchOverview:
        evidence_ids = [item.evidence_id for item in evidence]
        return self._overview(evidence_ids, self._cache)

    async def build(self, evidence: Sequence[Evidence]) -> SearchOverview:
        evidence_ids = [item.evidence_id for item in evidence]
        records = await self._records(evidence_ids)
        return self._overview(evidence_ids, records)


class ScriptedRelevanceStage:
    def __init__(self, labels: Mapping[str, SupportLabel]) -> None:
        self._labels = dict(labels)

    async def score(
        self, query: str, candidates: Sequence[Candidate]
    ) -> list[Candidate]:
        del query
        judged: list[Candidate] = []
        for candidate in candidates:
            label = self._labels.get(candidate.evidence_id, SupportLabel.DIRECT)
            judged.append(
                candidate.model_copy(
                    update={
                        "support_label": label,
                        "rerank_score": 0.0 if label is SupportLabel.IRRELEVANT else 0.9,
                    }
                )
            )
        return judged


class ScriptedClusterer:
    def __init__(self, assignments: Sequence[ClusterAssignment]) -> None:
        self._assignments = list(assignments)

    async def cluster(
        self,
        evidence_ids: Sequence[str],
        vectors: Mapping[str, Sequence[float]],
    ) -> Sequence[ClusterAssignment]:
        del vectors
        allowed = set(evidence_ids)
        filtered: list[ClusterAssignment] = []
        for assignment in self._assignments:
            members = tuple(item for item in assignment.evidence_ids if item in allowed)
            if members:
                filtered.append(
                    ClusterAssignment(cluster_id=assignment.cluster_id, evidence_ids=members)
                )
        return filtered


class ScriptedLabeler:
    def __init__(self, labels: Mapping[str, ThemeLabel]) -> None:
        self._labels = dict(labels)

    async def label(
        self, *, cluster_id: str, query: str, evidence_ids: Sequence[str]
    ) -> ThemeLabel:
        del query, evidence_ids
        return self._labels[cluster_id]


class FrozenTimelineRelease:
    def __init__(self, release: ReleaseInfo) -> None:
        self._release = release

    def release_for(self, scope: SearchScope) -> ReleaseInfo:
        del scope
        return self._release


def _candidate(
    evidence_id: str,
    channel: str,
    rank: int,
    *,
    text_hash: str | None = None,
) -> Candidate:
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "channels": [channel],
    }
    if channel == "lexical":
        payload["lexical_rank"] = rank
    else:
        payload["vector_rank"] = rank
        if text_hash is not None:
            payload["text_hash"] = text_hash
    return Candidate.model_validate(payload)


def _ids_from_case(case: Mapping[str, Any], extra: Sequence[str] = ()) -> list[str]:
    expected = list(case["expected_evidence_ids"])
    forbidden = list(case["forbidden_evidence_ids"])
    return list(dict.fromkeys([*expected, *forbidden, *extra]))


def _assignments_from_labels(expected_labels: Mapping[str, str]) -> list[ClusterAssignment]:
    clusters: dict[str, list[str]] = {}
    for evidence_id, label in expected_labels.items():
        clusters.setdefault(label, []).append(evidence_id)
    return [
        ClusterAssignment(cluster_id=label, evidence_ids=tuple(members))
        for label, members in clusters.items()
    ]


def build_four_mode_test_container(
    database_path: Path,
    *,
    settings: Settings | None = None,
) -> ApplicationContainer:
    """Compose Exact/Claim/Timeline/Thematic against one temporary SQLite."""

    resolved = settings or Settings(
        sqlite_database_path=database_path,
        active_data_version="data_synthetic_v1",
        active_index_version="idx_synthetic_v1",
        app_env="test",
    )
    sqlite = SQLiteDatabase(
        resolved.sqlite_database_path,
        busy_timeout_ms=resolved.sqlite_busy_timeout_ms,
    )
    repository = SQLiteEvidenceRepository(sqlite)
    evidence_service = EvidenceService(repository)
    scope_resolver = SQLiteScopeResolver(sqlite)
    release_resolver = SQLiteReleaseResolver(sqlite, resolved)
    cases = load_mode_cases()
    needed_ids = list(
        dict.fromkeys(
            [
                *_ids_from_case(cases[SearchMode.EXACT], _RECALL_GATES),
                *_ids_from_case(cases[SearchMode.CLAIM], _RECALL_GATES),
                *_ids_from_case(cases[SearchMode.TIMELINE], _RECALL_GATES),
                *_ids_from_case(cases[SearchMode.THEMATIC], _RECALL_GATES),
            ]
        )
    )
    records = asyncio.run(repository.get_by_ids(needed_ids))
    overview = SqliteOverviewAdapter(repository)
    overview._cache.update(records)
    release = asyncio.run(
        release_resolver.resolve_exact(
            SearchScope.model_validate(cases[SearchMode.EXACT]["scope"])
        )
    )

    claim_case = cases[SearchMode.CLAIM]
    claim_ids = _ids_from_case(claim_case, _RECALL_GATES)
    claim_query = str(claim_case["query"])
    claim_lexical = [
        _candidate(evidence_id, "lexical", rank)
        for rank, evidence_id in enumerate(claim_ids, start=1)
    ]
    claim_vector = [
        _candidate(
            evidence_id,
            "vector",
            rank,
            text_hash=records[evidence_id].text_hash if evidence_id in records else None,
        )
        for rank, evidence_id in enumerate(claim_ids, start=1)
        if evidence_id in records
    ]

    timeline_case = cases[SearchMode.TIMELINE]
    timeline_ids = _ids_from_case(timeline_case, _RECALL_GATES)
    timeline_query = str(timeline_case["query"])
    timeline_lexical = [
        _candidate(evidence_id, "lexical", rank)
        for rank, evidence_id in enumerate(timeline_ids, start=1)
    ]
    timeline_vector = [
        _candidate(
            evidence_id,
            "vector",
            rank,
            text_hash=records[evidence_id].text_hash,
        )
        for rank, evidence_id in enumerate(
            [item for item in timeline_ids if item in records],
            start=1,
        )
    ]

    thematic_case = cases[SearchMode.THEMATIC]
    thematic_ids = _ids_from_case(thematic_case, _RECALL_GATES)
    thematic_query = str(thematic_case["query"])
    expected_labels = dict(thematic_case["expected_labels"])
    assignments = _assignments_from_labels(expected_labels)
    theme_labels = {
        label: ThemeLabel(
            cluster_id=label,
            label=label,
            evidence_ids=tuple(
                evidence_id for evidence_id, value in expected_labels.items() if value == label
            ),
        )
        for label in dict.fromkeys(expected_labels.values())
    }
    thematic_relevance_labels = {
        evidence_id: SupportLabel.IRRELEVANT
        if evidence_id in FORBIDDEN_EVIDENCE_IDS
        else SupportLabel.DIRECT
        for evidence_id in thematic_ids
    }

    pipelines = PipelineRegistry(
        {
            SearchMode.EXACT: ExactPipeline(
                scope_resolver=scope_resolver,
                exact_index=SQLiteExactSearchIndex(sqlite),
                evidence_service=evidence_service,
                release_resolver=release_resolver,
            ),
            SearchMode.CLAIM: ClaimPipeline(
                scope_resolver=scope_resolver,
                lexical_index=QueryScopedLexicalIndex({claim_query: claim_lexical}),
                vector_index=StaticVectorIndex(claim_vector),
                embedding_provider=DeterministicEmbedding(),
                reranker=IdentityReranker(),
                language_model=CaseClassifier(
                    dict(claim_case["expected_labels"]),
                    claim_query,
                ),
                evidence_service=evidence_service,
                evidence_repository=repository,
                release_provider=FixedReleaseProvider(release),
                overview_provider=overview,
            ),
            SearchMode.TIMELINE: TimelinePipeline(
                scope_resolver=scope_resolver,
                lexical_index=QueryScopedLexicalIndex({timeline_query: timeline_lexical}),
                vector_index=StaticVectorIndex(timeline_vector),
                embedding_provider=DeterministicEmbedding(),
                evidence_service=evidence_service,
                release_provider=FrozenTimelineRelease(release),
                overview_provider=overview,
            ),
            SearchMode.THEMATIC: ThematicPipeline(
                scope_resolver=scope_resolver,
                lexical_index=QueryScopedLexicalIndex(
                    {
                        thematic_query: [
                            _candidate(evidence_id, "lexical", rank)
                            for rank, evidence_id in enumerate(thematic_ids, start=1)
                        ]
                    }
                ),
                vector_index=StaticVectorIndex([]),
                embedding=DeterministicEmbedding(),
                evidence_service=evidence_service,
                relevance_stage=ScriptedRelevanceStage(thematic_relevance_labels),
                clusterer=ScriptedClusterer(assignments),
                labeler=ScriptedLabeler(theme_labels),
                release_provider=FixedReleaseProvider(release),
                overview_provider=CountOverviewProvider(repository),
            ),
        }
    )
    return ApplicationContainer(settings=resolved, pipelines=pipelines, sqlite=sqlite)


def create_synthetic_demo_app(database_path: Path) -> FastAPI:
    """Explicit demo ASGI app. Never used by the default production container."""

    build = build_synthetic_corpus(database_path)
    settings = Settings(
        sqlite_database_path=build.database.path,
        active_data_version="data_synthetic_v1",
        active_index_version="idx_synthetic_v1",
        app_env="test",
    )
    container = build_four_mode_test_container(build.database.path, settings=settings)
    return create_app(settings=settings, container=container)
