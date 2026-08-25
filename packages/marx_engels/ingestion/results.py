"""Discover and hash MinerU result files without assuming fixed filenames."""

from __future__ import annotations

from pathlib import Path

from marx_engels.corpus_registry.hashing import sha256_file
from marx_engels.ingestion.models import ResultArtifact, TextLayer
from marx_engels.ingestion.zipsafe import safe_extract


def classify_artifact(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if name == "full.md":
        return "full_markdown"
    if name.endswith("content_list.json"):
        return "content_list"
    if name in {"middle.json", "layout.json"} or name.endswith("middle.json"):
        return "middle"
    if name.endswith("model.json"):
        return "model"
    if name.endswith(".md"):
        return "markdown"
    if name.endswith(".json"):
        return "json"
    return "other"


def register_extracted_files(result_dir: Path) -> list[ResultArtifact]:
    artifacts: list[ResultArtifact] = []
    for path in sorted(result_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(result_dir).as_posix()
        artifacts.append(
            ResultArtifact(
                relative_path=relative,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                kind=classify_artifact(relative),
                layer=TextLayer.RAW,
            )
        )
    return artifacts


def extract_and_register(archive_path: Path, result_dir: Path) -> list[ResultArtifact]:
    safe_extract(archive_path, result_dir)
    return register_extracted_files(result_dir)
