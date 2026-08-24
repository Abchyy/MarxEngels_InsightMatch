"""Write or verify the frozen JSON Schema snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marx_engels.contracts import (
    Candidate,
    ErrorResponse,
    Evidence,
    SearchRequest,
    SearchResponse,
    SearchScope,
)

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "contracts" / "schemas"
MODELS = {
    "candidate": Candidate,
    "error_response": ErrorResponse,
    "evidence": Evidence,
    "search_request": SearchRequest,
    "search_response": SearchResponse,
    "search_scope": SearchScope,
}


def render() -> dict[str, str]:
    return {
        name: json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
        for name, model in MODELS.items()
    }


def write_snapshots(rendered: dict[str, str]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (SNAPSHOT_DIR / f"{name}.v1.schema.json").write_text(content, encoding="utf-8")


def check_snapshots(rendered: dict[str, str]) -> int:
    mismatches: list[str] = []
    for name, content in rendered.items():
        path = SNAPSHOT_DIR / f"{name}.v1.schema.json"
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            mismatches.append(str(path.relative_to(ROOT)))
    if mismatches:
        print("Contract snapshots differ:")
        for mismatch in mismatches:
            print(f"- {mismatch}")
        return 1
    print("Contract snapshots match V1 sources.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.write:
        write_snapshots(rendered)
        print(f"Wrote {len(rendered)} contract snapshots.")
        return 0
    return check_snapshots(rendered)


if __name__ == "__main__":
    raise SystemExit(main())
