"""Atomic pipeline state stored under CORPUS_DATA_ROOT/state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marx_engels.ingestion.atomic import atomic_write_json
from marx_engels.ingestion.models import ChunkStatus, ExtractionChunk, ExtractionRun, RunStatus
from marx_engels.ingestion.paths import CorpusLayout


def utcnow() -> datetime:
    return datetime.now(UTC)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def save_pipeline_state(layout: CorpusLayout, payload: dict[str, Any]) -> None:
    atomic_write_json(layout.pipeline_state_path(), payload)


def load_pipeline_state(layout: CorpusLayout) -> dict[str, Any]:
    payload = load_json(layout.pipeline_state_path())
    if not payload:
        return {
            "schema_version": 1,
            "corpus_id": "marx_engels_collected_works_cn",
            "active_run_id": None,
            "volumes": {},
            "runs": {},
        }
    return payload


def run_to_dict(run: ExtractionRun) -> dict[str, Any]:
    payload = json.loads(run.model_dump_json())
    if not isinstance(payload, dict):
        raise TypeError("extraction run JSON must be an object")
    return payload


def chunk_by_id(run: ExtractionRun, chunk_id: str) -> ExtractionChunk:
    for chunk in run.chunks:
        if chunk.chunk_id == chunk_id:
            return chunk
    raise KeyError(chunk_id)


def upsert_run(state: dict[str, Any], run: ExtractionRun) -> dict[str, Any]:
    state.setdefault("runs", {})
    state["runs"][run.run_id] = run_to_dict(run)
    state["active_run_id"] = run.run_id
    return state


def mark_chunk(
    run: ExtractionRun, chunk_id: str, status: ChunkStatus, **updates: object
) -> ExtractionRun:
    updated: list[ExtractionChunk] = []
    found = False
    for chunk in run.chunks:
        if chunk.chunk_id != chunk_id:
            updated.append(chunk)
            continue
        found = True
        payload = chunk.model_dump()
        payload.update(updates)
        payload["status"] = status
        updated.append(ExtractionChunk.model_validate(payload))
    if not found:
        raise KeyError(chunk_id)
    run.chunks = updated
    run.updated_at = utcnow()
    if all(chunk.status == ChunkStatus.COMPLETED for chunk in run.chunks):
        run.status = RunStatus.COMPLETED
    elif any(chunk.status == ChunkStatus.FAILED for chunk in run.chunks) and all(
        chunk.status in {ChunkStatus.COMPLETED, ChunkStatus.FAILED, ChunkStatus.SKIPPED}
        for chunk in run.chunks
    ):
        run.status = RunStatus.FAILED
    return run
