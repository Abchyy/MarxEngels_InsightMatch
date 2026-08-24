from __future__ import annotations

import json
from pathlib import Path

from marx_engels.contracts import SearchMode
from marx_engels.evaluation.cli import main
from marx_engels.evaluation.dataset import (
    CONFLICTING_EVIDENCE,
    DANGLING_LABEL,
    DUPLICATE_CASE_ID,
    EMPTY_LABEL,
    INVALID_JSON,
    INVALID_MODE,
    INVALID_SCOPE,
    MISSING_HUMAN_DATA,
    MODE_FILE_MISMATCH,
    VERSION_MISMATCH,
    GoldenValidationReport,
    format_human_report,
    validate_golden_dataset,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_GOLDEN = REPO_ROOT / "tests" / "golden"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "golden"


def _codes(report: GoldenValidationReport) -> set[str]:
    return {issue.code for issue in report.issues}


def _run_cli(dataset_dir: Path) -> tuple[int, str, str]:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(["regression", "--dataset-dir", str(dataset_dir)])
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_valid_synthetic_fixture_validates() -> None:
    report = validate_golden_dataset(FIXTURES / "valid")
    assert report.ok is True
    assert report.case_count == 6
    assert report.dataset_version == "golden_v1"
    assert report.files_found == (
        "exact_cases.jsonl",
        "claim_cases.jsonl",
        "timeline_cases.jsonl",
        "thematic_cases.jsonl",
        "evidence_gate_cases.jsonl",
    )
    gate_modes = {
        located.case.mode
        for located in report.cases
        if located.path.endswith("evidence_gate_cases.jsonl")
    }
    assert gate_modes == {SearchMode.CLAIM, SearchMode.EXACT}
    human = format_human_report(report)
    assert "structure validated" in human
    assert "regression passed" not in human.lower()

    exit_code, stdout, stderr = _run_cli(FIXTURES / "valid")
    summary = json.loads(stdout)
    assert exit_code == 0
    assert summary["ok"] is True
    assert summary["status"] == "structure_validated"
    assert summary["case_count"] == 6
    assert "regression passed" not in stdout.lower()
    assert "regression passed" not in stderr.lower()


def test_broken_json_fails_with_file_and_line() -> None:
    report = validate_golden_dataset(FIXTURES / "invalid_json")
    assert report.ok is False
    json_issues = [issue for issue in report.issues if issue.code == INVALID_JSON]
    assert len(json_issues) == 1
    assert json_issues[0].path.endswith("claim_cases.jsonl")
    assert json_issues[0].line == 2

    exit_code, stdout, stderr = _run_cli(FIXTURES / "invalid_json")
    assert exit_code != 0
    assert "INVALID_JSON" in stdout
    assert "claim_cases.jsonl:2" in stderr


def test_duplicate_case_ids_fail_closed() -> None:
    report = validate_golden_dataset(FIXTURES / "duplicate_ids")
    assert report.ok is False
    duplicates = [issue for issue in report.issues if issue.code == DUPLICATE_CASE_ID]
    assert {issue.line for issue in duplicates} >= {2}
    messages = " ".join(issue.message for issue in duplicates)
    assert "exact_synthetic_001" in messages
    assert "timeline_synthetic_001" in messages
    assert any("first seen at" in issue.message for issue in duplicates)

    exit_code, _stdout, _stderr = _run_cli(FIXTURES / "duplicate_ids")
    assert exit_code != 0


def test_conflicting_evidence_ids_fail_closed() -> None:
    report = validate_golden_dataset(FIXTURES / "conflicting_evidence")
    assert report.ok is False
    conflicts = [issue for issue in report.issues if issue.code == CONFLICTING_EVIDENCE]
    assert len(conflicts) == 1
    assert conflicts[0].path.endswith("claim_cases.jsonl")
    assert conflicts[0].line == 1
    assert "ev_synthetic_claim_001" in conflicts[0].message

    exit_code, stdout, stderr = _run_cli(FIXTURES / "conflicting_evidence")
    assert exit_code != 0
    assert "CONFLICTING_EVIDENCE" in stdout
    assert "must be disjoint" in stderr


def test_mixed_dataset_versions_fail_closed() -> None:
    report = validate_golden_dataset(FIXTURES / "mixed_versions")
    assert report.ok is False
    assert report.dataset_version is None
    mismatches = [issue for issue in report.issues if issue.code == VERSION_MISMATCH]
    assert len(mismatches) == 1
    assert mismatches[0].path.endswith("thematic_cases.jsonl")
    assert mismatches[0].line == 1
    assert "golden_v2" in mismatches[0].message
    assert "golden_v1" in mismatches[0].message

    exit_code, _stdout, _stderr = _run_cli(FIXTURES / "mixed_versions")
    assert exit_code != 0


def test_empty_dataset_is_not_a_passing_evaluation() -> None:
    report = validate_golden_dataset(FIXTURES / "empty")
    assert report.ok is False
    assert report.case_count == 0
    assert MISSING_HUMAN_DATA in _codes(report)
    human = format_human_report(report)
    assert "0 reviewed cases" in human
    assert "regression passed" not in human.lower()

    exit_code, stdout, stderr = _run_cli(FIXTURES / "empty")
    summary = json.loads(stdout)
    assert exit_code != 0
    assert summary["ok"] is False
    assert summary["status"] == "failed"
    assert summary["case_count"] == 0
    assert "regression passed" not in stdout.lower()
    assert "regression passed" not in stderr.lower()
    assert "MISSING_HUMAN_DATA" in stdout


def test_official_golden_directory_fail_closed_without_human_cases() -> None:
    report = validate_golden_dataset(OFFICIAL_GOLDEN)
    assert report.ok is False
    assert report.case_count == 0
    assert MISSING_HUMAN_DATA in _codes(report)
    human = format_human_report(report)
    assert "regression passed" not in human.lower()
    assert "0 reviewed cases" in human


def test_invalid_mode_and_scope_are_rejected(tmp_path: Path) -> None:
    for filename in (
        "exact_cases.jsonl",
        "claim_cases.jsonl",
        "timeline_cases.jsonl",
        "thematic_cases.jsonl",
        "evidence_gate_cases.jsonl",
    ):
        (tmp_path / filename).write_text("", encoding="utf-8")

    (tmp_path / "exact_cases.jsonl").write_text(
        json.dumps(
            {
                "case_id": "exact_synthetic_bad_mode",
                "query": "SYNTHETIC_EXACT_TOKEN",
                "mode": "not-a-mode",
                "scope": {"corpus_ids": ["synthetic_corpus"]},
                "expected_evidence_ids": ["ev_synthetic_exact_001"],
                "forbidden_evidence_ids": [],
                "expected_labels": {},
                "notes": "Synthetic loader fixture; not official golden data.",
                "annotator": "synthetic-annotator",
                "reviewer": "synthetic-reviewer",
                "dataset_version": "golden_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "claim_cases.jsonl").write_text(
        json.dumps(
            {
                "case_id": "claim_synthetic_bad_scope",
                "query": "SYNTHETIC_CLAIM_QUERY",
                "mode": "claim",
                "scope": {},
                "expected_evidence_ids": ["ev_synthetic_claim_001"],
                "forbidden_evidence_ids": [],
                "expected_labels": {},
                "notes": "Synthetic loader fixture; not official golden data.",
                "annotator": "synthetic-annotator",
                "reviewer": "synthetic-reviewer",
                "dataset_version": "golden_v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = validate_golden_dataset(tmp_path)
    assert report.ok is False
    assert INVALID_MODE in _codes(report)
    assert INVALID_SCOPE in _codes(report)
    mode_issue = next(issue for issue in report.issues if issue.code == INVALID_MODE)
    scope_issue = next(issue for issue in report.issues if issue.code == INVALID_SCOPE)
    assert mode_issue.line == 1
    assert scope_issue.line == 1


def test_pipeline_mode_must_match_filename() -> None:
    report = validate_golden_dataset(FIXTURES / "mode_file_mismatch")
    assert report.ok is False
    mismatches = [issue for issue in report.issues if issue.code == MODE_FILE_MISMATCH]
    assert len(mismatches) == 2
    by_file = {Path(issue.path).name: issue for issue in mismatches}
    assert by_file["exact_cases.jsonl"].line == 1
    assert "expected 'exact'" in by_file["exact_cases.jsonl"].message
    assert "claim" in by_file["exact_cases.jsonl"].message
    assert by_file["thematic_cases.jsonl"].line == 1
    assert "expected 'thematic'" in by_file["thematic_cases.jsonl"].message
    assert "exact" in by_file["thematic_cases.jsonl"].message
    assert INVALID_MODE not in _codes(report)

    exit_code, stdout, stderr = _run_cli(FIXTURES / "mode_file_mismatch")
    assert exit_code != 0
    assert "MODE_FILE_MISMATCH" in stdout
    assert "exact_cases.jsonl:1" in stderr
    assert "thematic_cases.jsonl:1" in stderr


def test_dangling_labels_fail_closed() -> None:
    report = validate_golden_dataset(FIXTURES / "dangling_labels")
    assert report.ok is False
    dangling = [issue for issue in report.issues if issue.code == DANGLING_LABEL]
    assert len(dangling) == 1
    assert dangling[0].path.endswith("claim_cases.jsonl")
    assert dangling[0].line == 1
    assert "ev_synthetic_not_in_case" in dangling[0].message

    exit_code, stdout, stderr = _run_cli(FIXTURES / "dangling_labels")
    assert exit_code != 0
    assert "DANGLING_LABEL" in stdout
    assert "claim_cases.jsonl:1" in stderr


def test_empty_labels_fail_closed() -> None:
    report = validate_golden_dataset(FIXTURES / "empty_labels")
    assert report.ok is False
    empty = [issue for issue in report.issues if issue.code == EMPTY_LABEL]
    assert len(empty) == 2
    paths = {Path(issue.path).name for issue in empty}
    assert paths == {"claim_cases.jsonl", "timeline_cases.jsonl"}
    assert all(issue.line == 1 for issue in empty)

    exit_code, stdout, stderr = _run_cli(FIXTURES / "empty_labels")
    assert exit_code != 0
    assert "EMPTY_LABEL" in stdout
    assert "claim_cases.jsonl:1" in stderr
    assert "timeline_cases.jsonl:1" in stderr
