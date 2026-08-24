"""Corpus command slots owned by the corpus-pipeline worktree."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from marx_engels.corpus_registry import CorpusManifest


def main() -> int:
    parser = argparse.ArgumentParser(prog="ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-corpus")
    verify.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.manifest is None:
        print("Corpus verifier boundary is ready; pass --manifest when corpus data is available.")
        return 0
    payload = yaml.safe_load(args.manifest.read_text(encoding="utf-8"))
    manifest = CorpusManifest.model_validate(payload)
    print(f"Validated manifest contract for {manifest.corpus_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
