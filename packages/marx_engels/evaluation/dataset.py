"""Load and fail-closed validate the official golden-dataset JSONL files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from marx_engels.contracts import SearchMode
from marx_engels.evaluation.models import GoldenCase

REQUIRED_GOLDEN_FILES: tuple[str, ...] = (
    "exact_cases.jsonl",
    "claim_cases.jsonl",
    "timeline_cases.jsonl",
    "thematic_cases.jsonl",
    "evidence_gate_cases.jsonl",
)

PIPELINE_FILE_MODES: dict[str, SearchMode] = {
    "exact_cases.jsonl": SearchMode.EXACT,
    "claim_cases.jsonl": SearchMode.CLAIM,
    "timeline_cases.jsonl": SearchMode.TIMELINE,
    "thematic_cases.jsonl": SearchMode.THEMATIC,
}

MISSING_FILE = "MISSING_FILE"
MISSING_HUMAN_DATA = "MISSING_HUMAN_DATA"
INVALID_JSON = "INVALID_JSON"
INVALID_CASE = "INVALID_CASE"
INVALID_MODE = "INVALID_MODE"
INVALID_SCOPE = "INVALID_SCOPE"
MODE_FILE_MISMATCH = "MODE_FILE_MISMATCH"
EMPTY_LABEL = "EMPTY_LABEL"
DANGLING_LABEL = "DANGLING_LABEL"
DUPLICATE_CASE_ID = "DUPLICATE_CASE_ID"
CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
VERSION_MISMATCH = "VERSION_MISMATCH"
NOT_A_DIRECTORY = "NOT_A_DIRECTORY"


@dataclass(frozen=True)
class GoldenIssue:
    code: str
    message: str
    path: str
    line: int | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "line": self.line,
        }


@dataclass(frozen=True)
class LocatedGoldenCase:
    case: GoldenCase
    path: str
    line: int


@dataclass(frozen=True)
class GoldenValidationReport:
    cases: tuple[LocatedGoldenCase, ...]
    issues: tuple[GoldenIssue, ...]
    dataset_version: str | None
    files_found: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues and len(self.cases) > 0

    @property
    def case_count(self) -> int:
        return len(self.cases)

    def to_summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": "structure_validated" if self.ok else "failed",
            "case_count": self.case_count,
            "required_files": list(REQUIRED_GOLDEN_FILES),
            "files_found": list(self.files_found),
            "dataset_version": self.dataset_version,
            "error_count": len(self.issues),
            "errors": [issue.to_dict() for issue in self.issues],
        }


def validate_golden_dataset(dataset_dir: Path) -> GoldenValidationReport:
    issues: list[GoldenIssue] = []
    cases: list[LocatedGoldenCase] = []
    files_found: list[str] = []
    seen_ids: dict[str, LocatedGoldenCase] = {}
    non_empty_rows = 0

    if not dataset_dir.exists() or not dataset_dir.is_dir():
        issues.append(
            GoldenIssue(
                code=NOT_A_DIRECTORY,
                message="golden dataset path must be an existing directory",
                path=str(dataset_dir),
            )
        )
        issues.append(_missing_human_data(dataset_dir))
        return GoldenValidationReport(
            cases=(),
            issues=tuple(issues),
            dataset_version=None,
            files_found=(),
        )

    for filename in REQUIRED_GOLDEN_FILES:
        path = dataset_dir / filename
        if not path.is_file():
            issues.append(
                GoldenIssue(
                    code=MISSING_FILE,
                    message="required official golden JSONL file is missing",
                    path=str(path),
                )
            )
            continue
        files_found.append(filename)
        file_rows, file_cases, file_issues = _load_jsonl(path)
        non_empty_rows += file_rows
        issues.extend(file_issues)
        for located in file_cases:
            previous = seen_ids.get(located.case.case_id)
            if previous is not None:
                issues.append(
                    GoldenIssue(
                        code=DUPLICATE_CASE_ID,
                        message=(
                            f"duplicate case_id '{located.case.case_id}' "
                            f"(first seen at {previous.path}:{previous.line})"
                        ),
                        path=located.path,
                        line=located.line,
                    )
                )
            else:
                seen_ids[located.case.case_id] = located
            cases.append(located)

    dataset_version = _consistent_dataset_version(cases, issues)
    if not cases and non_empty_rows == 0:
        issues.append(_missing_human_data(dataset_dir))

    return GoldenValidationReport(
        cases=tuple(cases),
        issues=tuple(issues),
        dataset_version=dataset_version,
        files_found=tuple(files_found),
    )


def format_human_report(report: GoldenValidationReport) -> str:
    if report.ok:
        version = report.dataset_version or "unknown"
        return (
            f"golden dataset structure validated: {report.case_count} cases, "
            f"dataset_version={version}"
        )
    lines = [
        f"golden dataset validation failed ({len(report.issues)} errors, "
        f"{report.case_count} cases)"
    ]
    for issue in report.issues:
        location = issue.path if issue.line is None else f"{issue.path}:{issue.line}"
        lines.append(f"  [{issue.code}] {location}: {issue.message}")
    return "\n".join(lines)


def _missing_human_data(dataset_dir: Path) -> GoldenIssue:
    return GoldenIssue(
        code=MISSING_HUMAN_DATA,
        message=(
            "golden dataset has 0 reviewed cases; annotator and reviewer labels "
            "are required. Zero cases is not a passing evaluation. Synthetic "
            "fixtures under tests/fixtures/golden/ are not official golden data."
        ),
        path=str(dataset_dir),
    )


def _load_jsonl(
    path: Path,
) -> tuple[int, list[LocatedGoldenCase], list[GoldenIssue]]:
    cases: list[LocatedGoldenCase] = []
    issues: list[GoldenIssue] = []
    non_empty_rows = 0
    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        non_empty_rows += 1
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            issues.append(
                GoldenIssue(
                    code=INVALID_JSON,
                    message=f"line is not valid JSON: {exc.msg}",
                    path=str(path),
                    line=line_number,
                )
            )
            continue
        if not isinstance(payload, dict):
            issues.append(
                GoldenIssue(
                    code=INVALID_CASE,
                    message="JSONL line must be a JSON object",
                    path=str(path),
                    line=line_number,
                )
            )
            continue
        try:
            case = GoldenCase.model_validate(payload)
        except ValidationError as exc:
            issues.append(_issue_from_validation(path, line_number, exc))
            continue
        located = LocatedGoldenCase(case=case, path=str(path), line=line_number)
        mode_issue = _mode_file_mismatch(path, located)
        if mode_issue is not None:
            issues.append(mode_issue)
        cases.append(located)
    return non_empty_rows, cases, issues


def _issue_from_validation(path: Path, line: int, exc: ValidationError) -> GoldenIssue:
    messages: list[str] = []
    code = INVALID_CASE
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"]
        messages.append(f"{location}: {message}" if location else message)
        if "must be disjoint" in message:
            code = CONFLICTING_EVIDENCE
        elif "keys and values must be non-empty" in message:
            code = EMPTY_LABEL
        elif "must belong to expected_evidence_ids or forbidden_evidence_ids" in message:
            code = DANGLING_LABEL
        elif error["loc"] and error["loc"][0] == "mode" and code == INVALID_CASE:
            code = INVALID_MODE
        elif error["loc"] and error["loc"][0] == "scope" and code == INVALID_CASE:
            code = INVALID_SCOPE
    return GoldenIssue(
        code=code,
        message="; ".join(messages),
        path=str(path),
        line=line,
    )


def _mode_file_mismatch(path: Path, located: LocatedGoldenCase) -> GoldenIssue | None:
    expected_mode = PIPELINE_FILE_MODES.get(path.name)
    if expected_mode is None or located.case.mode == expected_mode:
        return None
    return GoldenIssue(
        code=MODE_FILE_MISMATCH,
        message=(
            f"case.mode '{located.case.mode}' does not match pipeline file "
            f"'{path.name}' (expected '{expected_mode}')"
        ),
        path=located.path,
        line=located.line,
    )


def _consistent_dataset_version(
    cases: list[LocatedGoldenCase],
    issues: list[GoldenIssue],
) -> str | None:
    if not cases:
        return None
    canonical = cases[0].case.dataset_version
    mismatched = False
    for located in cases[1:]:
        if located.case.dataset_version != canonical:
            mismatched = True
            issues.append(
                GoldenIssue(
                    code=VERSION_MISMATCH,
                    message=(
                        f"dataset_version '{located.case.dataset_version}' does not "
                        f"match '{canonical}' from {cases[0].path}:{cases[0].line}"
                    ),
                    path=located.path,
                    line=located.line,
                )
            )
    if mismatched:
        return None
    return canonical
