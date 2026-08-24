"""Evaluation command entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("regression")
    args = parser.parse_args()
    cases = list(Path("tests/golden").glob("*.jsonl"))
    print(f"{args.command}: discovered {len(cases)} golden dataset files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
