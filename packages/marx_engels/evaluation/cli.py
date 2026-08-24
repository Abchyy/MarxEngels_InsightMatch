"""Evaluation command entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from marx_engels.evaluation.dataset import format_human_report, validate_golden_dataset


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    regression = subparsers.add_parser("regression")
    regression.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("tests/golden"),
        help="Directory containing the official golden JSONL files.",
    )
    args = parser.parse_args(argv)
    report = validate_golden_dataset(args.dataset_dir)
    print(json.dumps(report.to_summary(), ensure_ascii=False, indent=2), flush=True)
    print(format_human_report(report), file=sys.stderr, flush=True)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
