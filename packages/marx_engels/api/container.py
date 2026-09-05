"""Minimal composition root for replaceable module implementations."""

from dataclasses import dataclass

from marx_engels.contracts import SearchMode
from marx_engels.corpus_registry.local_asset import DEFAULT_SEED_PATH, assert_not_canonical_seed
from marx_engels.evidence import EvidenceService
from marx_engels.pipelines import ExactPipeline, PipelineRegistry
from marx_engels.pipelines.stub import UnimplementedPipeline
from marx_engels.settings import Settings
from marx_engels.storage import (
    SQLiteDatabase,
    SQLiteEvidenceRepository,
    SQLiteExactSearchIndex,
    SQLiteReleaseResolver,
    SQLiteScopeResolver,
)


@dataclass(frozen=True)
class ApplicationContainer:
    settings: Settings
    pipelines: PipelineRegistry
    sqlite: SQLiteDatabase


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    resolved = settings or Settings()
    assert_not_canonical_seed(resolved.sqlite_database_path, DEFAULT_SEED_PATH)
    sqlite = SQLiteDatabase(
        resolved.sqlite_database_path,
        busy_timeout_ms=resolved.sqlite_busy_timeout_ms,
    )
    repository = SQLiteEvidenceRepository(sqlite)
    pipelines = PipelineRegistry(
        {
            SearchMode.EXACT: ExactPipeline(
                scope_resolver=SQLiteScopeResolver(sqlite),
                exact_index=SQLiteExactSearchIndex(sqlite),
                evidence_service=EvidenceService(repository),
                release_resolver=SQLiteReleaseResolver(sqlite, resolved),
            ),
            SearchMode.CLAIM: UnimplementedPipeline(SearchMode.CLAIM),
            SearchMode.TIMELINE: UnimplementedPipeline(SearchMode.TIMELINE),
            SearchMode.THEMATIC: UnimplementedPipeline(SearchMode.THEMATIC),
        }
    )
    return ApplicationContainer(settings=resolved, pipelines=pipelines, sqlite=sqlite)
