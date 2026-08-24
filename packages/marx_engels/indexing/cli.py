"""Safe index command placeholders for later worktree implementation."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="indexing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("build-index")
    subparsers.add_parser("verify-index")
    args = parser.parse_args()
    print(f"{args.command} boundary is ready; no published corpus is configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
