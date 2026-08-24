"""Export the deterministic OpenAPI V1 contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marx_engels.api.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    output.write_text(content, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
