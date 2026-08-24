"""Minimal composition root for replaceable module implementations."""

from dataclasses import dataclass

from marx_engels.contracts import SearchMode
from marx_engels.pipelines import PipelineRegistry
from marx_engels.pipelines.stub import UnimplementedPipeline
from marx_engels.settings import Settings
from marx_engels.storage import SQLiteDatabase


@dataclass(frozen=True)
class ApplicationContainer:
    settings: Settings
    pipelines: PipelineRegistry
    sqlite: SQLiteDatabase


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    resolved = settings or Settings()
    pipelines = PipelineRegistry(
        {mode: UnimplementedPipeline(mode) for mode in SearchMode}
    )
    sqlite = SQLiteDatabase(
        resolved.sqlite_database_path,
        busy_timeout_ms=resolved.sqlite_busy_timeout_ms,
    )
    return ApplicationContainer(settings=resolved, pipelines=pipelines, sqlite=sqlite)
