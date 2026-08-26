"""Load assembled Clean artifacts for local SQLite handoff."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marx_engels.ingestion.layer_models import (
    PageMapRecord,
    PassageCandidate,
    PassagePageLink,
    ReviewIssue,
    SectionCandidate,
    WorkCandidate,
)
from marx_engels.ingestion.paths import CorpusLayout


@dataclass
class AssembleSnapshot:
    assemble_run_id: str
    works: list[WorkCandidate]
    sections: list[SectionCandidate]
    passages: list[PassageCandidate]
    page_maps: list[PageMapRecord]
    passage_pages: list[PassagePageLink]
    issues: list[ReviewIssue]
    report: dict[str, Any]


def latest_assemble_id(layout: CorpusLayout) -> str:
    latest = layout.clean_structures / "latest.json"
    if not latest.is_file():
        raise FileNotFoundError("no assemble snapshot; run assemble first")
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assemble_id = payload.get("assemble_run_id")
    if not assemble_id:
        raise FileNotFoundError("assemble latest.json is missing assemble_run_id")
    return str(assemble_id)


def load_assemble_snapshot(
    layout: CorpusLayout, assemble_run_id: str | None = None
) -> AssembleSnapshot:
    assemble_id = assemble_run_id or latest_assemble_id(layout)
    structure_dir = layout.structure_dir(assemble_id)
    report_path = layout.structure_report_path(assemble_id)
    if not report_path.is_file():
        raise FileNotFoundError(f"assemble report not found: {assemble_id}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    works = [
        WorkCandidate.model_validate(item) for item in _load_json_list(structure_dir / "works.json")
    ]
    sections = [
        SectionCandidate.model_validate(item)
        for item in _load_json_list(structure_dir / "sections.json")
    ]
    page_maps = [
        PageMapRecord.model_validate(item)
        for item in _load_json_list(structure_dir / "page_maps.json")
    ]
    passage_pages = [
        PassagePageLink.model_validate(item)
        for item in _load_json_list(structure_dir / "passage_pages.json")
    ]
    passages: list[PassageCandidate] = []
    passage_dir = layout.passage_dir(assemble_id)
    if passage_dir.is_dir():
        for path in sorted(passage_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            passages.extend(PassageCandidate.model_validate(item) for item in payload)
    issues = _load_issues(layout.review_issue_path(assemble_id))
    return AssembleSnapshot(
        assemble_run_id=assemble_id,
        works=works,
        sections=sections,
        passages=passages,
        page_maps=page_maps,
        passage_pages=passage_pages,
        issues=issues,
        report=report,
    )


def _load_json_list(path: Path) -> list[Any]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload) if isinstance(payload, list) else []


def _load_issues(path: Path) -> list[ReviewIssue]:
    if not path.is_file():
        return []
    issues: list[ReviewIssue] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            issues.append(ReviewIssue.model_validate_json(line))
    return issues
